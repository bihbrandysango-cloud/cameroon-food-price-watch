"""Build the Power BI project (PBIP) for Cameroon Food Price Watch.

    python powerbi/build/build_pbip.py

Writes powerbi/Cameroon Food Price Watch.pbip with its semantic model (TMDL)
and report (PBIR). Open the .pbip in Power BI Desktop. Everything here is
generated: change this script and rebuild rather than editing the output.

Images come from powerbi/out/ (render them first with render_images.ps1).
Data comes from powerbi/data/ (python -m src.export.export_powerbi).
"""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

POWERBI = Path(__file__).resolve().parents[1]
NAME = "Cameroon Food Price Watch"
DATA_FOLDER = str(POWERBI / "data") + "\\"
IMAGES = POWERBI / "out"
BASE_THEME = (Path.home() / "Desktop" / "Github Projects" / "01-published" / "vitalis-healthcare" / "final-pack"
              / "04 Power BI Report" / "Vitalis Healthcare.Report" / "StaticResources" / "SharedResources"
              / "BaseThemes" / "CY24SU10.json")

# Fresh Field "Green Sidebar" design: dark text on white cards. Three alert colours,
# validated for colour blindness on white: direction only; how big the change is
# shows as dot size and bar length. Order: 1 alert high ... 5 alert low, 6 not judged.
HIGH, NORMAL, LOW, NOT_JUDGED = "#C8372D", "#8F8A7E", "#2864A8", "#C9C6BB"
COLOURS = {1: HIGH, 2: HIGH, 3: NORMAL, 4: LOW, 5: LOW, 6: NOT_JUDGED}
INK, MUTED, GOLD, GREEN = "#1E3A22", "#6A7C62", "#F2C230", "#2E7D32"
FONT = "Segoe UI"
BACKGROUND = "bg_overview_sidebar.png"
MAP_IMAGE = "map_outline_light.png"

# Map plot-area image extent: must match powerbi/design/map-outline.html
LON, LAT = (8.0, 16.6), (1.5, 13.2)


# ----------------------------------------------------------------------------- model

def tmdl_table(name: str, columns: list[tuple], partition: str, extra: str = "") -> str:
    """columns: (name, dataType, formatString or None, hidden?)"""
    out = [f"table {q(name)}", ""]
    for col, dtype, fmt, hidden in columns:
        out.append(f"\tcolumn {q(col)}")
        out.append(f"\t\tdataType: {dtype}")
        if fmt:
            out.append(f"\t\tformatString: {fmt}")
        if hidden:
            out.append("\t\tisHidden")
        out.append("\t\tsummarizeBy: none")
        out.append(f"\t\tsourceColumn: {col}")
        out.append("")
    out.append(extra) if extra else None
    out.append(partition)
    return "\n".join(out) + "\n"


def q(name: str) -> str:
    return f"'{name}'" if any(c in name for c in " -()&/") else name


def csv_partition(table: str, file: str, types: dict[str, str]) -> str:
    cols = ",".join(f'"{c}"' for c in types)
    conv = ",".join(f'{{"{c}", {t}}}' for c, t in types.items())
    return (f"\tpartition {q(table)} = m\n\t\tmode: import\n\t\tsource =\n"
            f"\t\t\t\tlet\n"
            f"\t\t\t\t    Source = Csv.Document(File.Contents(DataFolder & \"{file}\"),[Delimiter=\",\", Encoding=65001, QuoteStyle=QuoteStyle.Csv]),\n"
            f"\t\t\t\t    H = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),\n"
            f"\t\t\t\t    K = Table.SelectColumns(H,{{{cols}}}),\n"
            f"\t\t\t\t    T = Table.TransformColumnTypes(K,{{{conv}}}, \"en-US\")\n"
            f"\t\t\t\tin\n\t\t\t\t    T\n")


M_TYPE = {"string": "type text", "int64": "Int64.Type", "double": "type number", "dateTime": "type date", "boolean": "type logical"}


def csv_table(name: str, file: str, columns: list[tuple]) -> str:
    return tmdl_table(name, columns, csv_partition(name, file, {c[0]: M_TYPE[c[1]] for c in columns}))


MEASURES = {
    # ---- the month being shown: the latest month in the current filters
    "Latest Month": ("CALCULATE ( MAX ( Prices[price_month] ), REMOVEFILTERS ( Markets ) )", "mmmm yyyy"),
    "Food Label": ('SELECTEDVALUE ( Commodities[commodity], "the selected foods" )', None),
    "Month Label": ('"Prices for " & FORMAT ( [Latest Month], "MMMM yyyy" )', None),
    # ---- market counts in the latest month
    "Markets Reporting": ("VAR m = [Latest Month]\nRETURN CALCULATE ( DISTINCTCOUNT ( Prices[market_code] ), Prices[price_month] = m )", "#,0"),
    "Markets Judged": ('VAR m = [Latest Month]\nRETURN CALCULATE ( DISTINCTCOUNT ( Prices[market_code] ), Prices[price_month] = m, Prices[direction] <> "Not enough history" )', "#,0"),
    "Markets Too Cheap": ('VAR m = [Latest Month]\nRETURN COALESCE ( CALCULATE ( DISTINCTCOUNT ( Prices[market_code] ), Prices[price_month] = m, Prices[direction] = "Too cheap" ), 0 )', "#,0"),
    "Markets Too Expensive": ('VAR m = [Latest Month]\nRETURN COALESCE ( CALCULATE ( DISTINCTCOUNT ( Prices[market_code] ), Prices[price_month] = m, Prices[direction] = "Too expensive" ), 0 )', "#,0"),
    # ---- headline card: whichever side has more markets leads
    "Headline Fraction": ('VAR c = [Markets Too Cheap]\nVAR e = [Markets Too Expensive]\nRETURN FORMAT ( MAX ( c, e ), "0" ) & " / " & FORMAT ( [Markets Judged], "0" )', None),
    "Headline Text": ('VAR c = [Markets Too Cheap]\nVAR e = [Markets Too Expensive]\nVAR food = LOWER ( [Food Label] )\nRETURN\n    IF ( c >= e,\n        "markets selling " & food & " well below normal. " & e & " above.",\n        "markets where " & food & " costs well above normal. " & c & " below." )', None),
    "Reporting Text": ('[Markets Reporting] & " markets reported prices in " & FORMAT ( [Latest Month], "MMMM yyyy" ) & ". Markets need three years of history to be judged."', None),
    # ---- spotlight: the market furthest from normal
    "Spotlight Market": ("VAR m = [Latest Month]\nVAR t = ADDCOLUMNS ( VALUES ( Markets[market] ), \"@gap\", CALCULATE ( MAX ( Prices[gap_from_normal] ), Prices[price_month] = m ) )\nVAR best = TOPN ( 1, FILTER ( t, NOT ISBLANK ( [@gap] ) ), ABS ( [@gap] ), DESC )\nRETURN MAXX ( best, Markets[market] )", None),
    "Spotlight Title": ("VAR mk = [Spotlight Market]\nRETURN mk & \" · \" & CALCULATE ( MAX ( Markets[region] ), Markets[market] = mk )", None),
    "FCFA per kg now": ("VAR m = [Latest Month]\nVAR mk = [Spotlight Market]\nRETURN CALCULATE ( MAX ( Prices[price_per_unit] ), Prices[price_month] = m, Markets[market] = mk )", "#,0"),
    "Usual for this month": ("VAR m = [Latest Month]\nVAR mk = [Spotlight Market]\nRETURN CALCULATE ( MAX ( Prices[normal_price] ), Prices[price_month] = m, Markets[market] = mk )", "#,0"),
    "Spotlight Gap": ("VAR m = [Latest Month]\nVAR mk = [Spotlight Market]\nRETURN CALCULATE ( MAX ( Prices[gap_from_normal] ), Prices[price_month] = m, Markets[market] = mk )", '+0%;-0%;0%'),
    "Spotlight Note": ('IF ( [Spotlight Gap] < 0,\n    "Cheap for buyers, hard on farmers.",\n    "Dear for buyers, good for sellers." )', None),
    # ---- one market in the latest month (map and bar chart)
    "Market Price": ("VAR m = [Latest Month]\nRETURN CALCULATE ( MAX ( Prices[price_per_unit] ), Prices[price_month] = m )", "#,0"),
    "Market Normal": ("VAR m = [Latest Month]\nRETURN CALCULATE ( MAX ( Prices[normal_price] ), Prices[price_month] = m )", "#,0"),
    "Market Alert Order": ("VAR m = [Latest Month]\nRETURN CALCULATE ( MIN ( Prices[alert_order] ), Prices[price_month] = m )", "0"),
    "Gap From Normal": ("VAR m = [Latest Month]\nVAR o = [Market Alert Order]\nRETURN IF ( o < 6, CALCULATE ( MAX ( Prices[gap_from_normal] ), Prices[price_month] = m ) )", '+0%;-0%;0%'),
    "Market Status": ('SWITCH ( [Market Alert Order], 1, "Alert: too expensive", 2, "Watch: rising", 3, "Normal", 4, "Watch: falling", 5, "Alert: too cheap", 6, "Not enough history" )', None),
    "Market Colour": ("SWITCH ( [Market Alert Order], " + ", ".join(f'{k}, "{v}"' for k, v in COLOURS.items() if k < 6) + f', "{COLOURS[6]}" )', None),
    "Map Longitude": ("IF ( NOT ISBLANK ( [Market Price] ), MAX ( Markets[lon] ) )", "0.00"),
    "Map Latitude": ("IF ( NOT ISBLANK ( [Market Price] ), MAX ( Markets[lat] ) )", "0.00"),
    "Map Dot Size": ("SWITCH ( [Market Alert Order], 1, 4, 5, 4, 2, 2, 4, 2, 3, 1.4, 1 )", "0.0"),
    # ---- Green Sidebar page: title strip, KPI row, markets-to-watch table
    "Page Title": ('[Food Label] & " prices this month"', None),
    "Page Subtitle": ('SELECTEDVALUE ( PriceType[Price type], "All" ) & " prices · " & FORMAT ( [Latest Month], "MMMM yyyy" ) & " · compared with the same month in the last five years"', None),
    "Cheap Fraction": ('[Markets Too Cheap] & " of " & [Markets Judged]', None),
    "Biggest Change Label": ('"biggest: " & [Spotlight Market]', None),
    "Spotlight Gap Colour": (f'IF ( [Spotlight Gap] < 0, "{LOW}", "{HIGH}" )', None),
    "Watch Rank": ("VAR g = [Gap From Normal]\nRETURN\n    IF ( NOT ISBLANK ( g ),\n        RANKX ( FILTER ( ALLSELECTED ( Markets[market] ), NOT ISBLANK ( [Gap From Normal] ) ), ABS ( [Gap From Normal] ), ABS ( g ), DESC ) )", "0"),
    "Now": ("VAR r = [Watch Rank]\nRETURN IF ( NOT ISBLANK ( r ) && r <= 7, [Market Price] )", "#,0"),
    "Usual": ("VAR r = [Watch Rank]\nRETURN IF ( NOT ISBLANK ( r ) && r <= 7, [Market Normal] )", "#,0"),
    "Change": ("VAR r = [Watch Rank]\nRETURN IF ( NOT ISBLANK ( r ) && r <= 7, [Gap From Normal] )", '+0%;-0%;0%'),
}


def colour_rule(expr: str) -> str:
    """DAX that turns a gap from normal into the report's three colours (grey-beige when unknown)."""
    return (f"VAR g = {expr}\nRETURN SWITCH ( TRUE (), ISBLANK ( g ), \"{NOT_JUDGED}\", g >= 0.2, \"{HIGH}\", "
            f"g <= -0.2, \"{LOW}\", \"{NORMAL}\" )")


def latest(agg: str) -> str:
    """An aggregate of Prices in the latest month of the current filters."""
    return f"VAR m = [Latest Month]\nRETURN CALCULATE ( {agg}, Prices[price_month] = m )"


def status_count(direction: str) -> str:
    """Markets in a direction in the latest month, blank (not 0) when none, so empty rows drop out."""
    return f'VAR m = [Latest Month]\nRETURN CALCULATE ( DISTINCTCOUNT ( Prices[market_code] ), Prices[price_month] = m, Prices[direction] = "{direction}" )'


MEASURES.update({
    # ---- shared
    "Price Type Label": ('SELECTEDVALUE ( PriceType[Price type], "All" )', None),
    "Cheaper Markets": (status_count("Too cheap"), "#,0"),
    "Normal Markets": (status_count("Normal"), "#,0"),
    "Dearer Markets": (status_count("Too expensive"), "#,0"),
    "Market Colour Light": (colour_rule("[Gap From Normal]"), None),

    # ---- page 2: one market over time
    "Selected Market": ('SELECTEDVALUE ( Markets[market], "all markets" )', None),
    "Market Page Title": ('[Selected Market] & " · " & [Food Label]', None),
    "Market Page Subtitle": ('VAR r = SELECTEDVALUE ( Markets[region] )\nRETURN IF ( NOT ISBLANK ( r ), r & " region · ", "" ) & [Price Type Label] & " prices over time, FCFA per kg"', None),
    "Market Last Month": ("CALCULATE ( MAX ( Prices[price_month] ) )", "mmmm yyyy"),
    "Latest Price": ("VAR m = [Market Last Month]\nRETURN CALCULATE ( AVERAGE ( Prices[price_per_unit] ), Prices[price_month] = m )", "#,0"),
    "Latest Usual": ("VAR m = [Market Last Month]\nRETURN CALCULATE ( AVERAGE ( Prices[normal_price] ), Prices[price_month] = m )", "#,0"),
    "Latest Change": ("VAR m = [Market Last Month]\nRETURN CALCULATE ( AVERAGE ( Prices[gap_from_normal] ), Prices[price_month] = m )", '+0%;-0%;0%'),
    "Latest Change Colour": (colour_rule("[Latest Change]"), None),
    "Months With Prices": ("DISTINCTCOUNT ( Prices[price_month] )", "#,0"),
    "Monthly Price": ("AVERAGE ( Prices[price_per_unit] )", "#,0"),
    "Monthly Usual": ("AVERAGE ( Prices[normal_price] )", "#,0"),
    "Gap Last 12 Months": ("VAR last = CALCULATE ( MAX ( Prices[price_month] ), ALLSELECTED ( Calendar ) )\nVAR d = MAX ( Calendar[Date] )\n"
                           "RETURN IF ( d > EOMONTH ( last, -12 ) && d <= EOMONTH ( last, 0 ), AVERAGE ( Prices[gap_from_normal] ) )", '+0%;-0%;0%'),
    "Gap 12 Colour": (colour_rule("[Gap Last 12 Months]"), None),
    # four short lines: a multi-row card does not wrap long text
    "Market Facts 1": ('IF ( ISBLANK ( SELECTEDVALUE ( Markets[market] ) ), "Choose one market to see its details.",\n'
                       '    SELECTEDVALUE ( Markets[region] ) & " region, " & SELECTEDVALUE ( Markets[department] ) & " department" )', None),
    "Market Facts 2": ('IF ( NOT ISBLANK ( SELECTEDVALUE ( Markets[market] ) ),\n'
                       '    "Prices from " & FORMAT ( SELECTEDVALUE ( Markets[first_month] ), "MMM yyyy" ) & " to " & FORMAT ( SELECTEDVALUE ( Markets[last_month] ), "MMM yyyy" ) )', None),
    "Market Facts 3": ('IF ( NOT ISBLANK ( SELECTEDVALUE ( Markets[market] ) ),\n'
                       '    SELECTEDVALUE ( Markets[months_with_prices] ) & " months with a price, " & FORMAT ( SELECTEDVALUE ( Markets[coverage] ), "0%" ) & " of that time" )', None),
    "Market Facts 4": ('IF ( NOT ISBLANK ( SELECTEDVALUE ( Markets[market] ) ),\n'
                       '    IF ( SELECTEDVALUE ( Markets[is_reporting_now] ), "Still reporting", "Has stopped reporting" ) )', None),

    # ---- page 3: all foods, judged in the report month
    "Report Month": ("CALCULATE ( MAX ( Prices[price_month] ), REMOVEFILTERS ( Markets ), REMOVEFILTERS ( Commodities ) )", "mmmm yyyy"),
    "Food Typical Gap": ("VAR m = [Report Month]\nRETURN CALCULATE ( MEDIAN ( Prices[gap_from_normal] ), Prices[price_month] = m )", '+0%;-0%;0%'),
    "Food Gap Colour": (colour_rule("[Food Typical Gap]"), None),
    "Food Typical Price": ("VAR m = [Report Month]\nRETURN CALCULATE ( MEDIAN ( Prices[price_per_unit] ), Prices[price_month] = m )", "#,0"),
    "Food Usual": ("VAR m = [Report Month]\nRETURN CALCULATE ( MEDIAN ( Prices[normal_price] ), Prices[price_month] = m )", "#,0"),
    "Food Unit": ('VAR m = [Report Month]\nRETURN CALCULATE ( MAX ( Prices[standard_unit] ), Prices[price_month] = m )', None),
    "Food Cheaper": ('VAR m = [Report Month]\nRETURN CALCULATE ( DISTINCTCOUNT ( Prices[market_code] ), Prices[price_month] = m, Prices[direction] = "Too cheap" )', "#,0"),
    "Food Normal": ('VAR m = [Report Month]\nRETURN CALCULATE ( DISTINCTCOUNT ( Prices[market_code] ), Prices[price_month] = m, Prices[direction] = "Normal" )', "#,0"),
    "Food Dearer": ('VAR m = [Report Month]\nRETURN CALCULATE ( DISTINCTCOUNT ( Prices[market_code] ), Prices[price_month] = m, Prices[direction] = "Too expensive" )', "#,0"),
    "Foods Mostly Cheaper": ("COALESCE ( COUNTROWS ( FILTER ( VALUES ( Commodities[commodity] ), [Food Typical Gap] <= -0.2 ) ), 0 )", "#,0"),
    "Foods Mostly Dearer": ("COALESCE ( COUNTROWS ( FILTER ( VALUES ( Commodities[commodity] ), [Food Typical Gap] >= 0.2 ) ), 0 )", "#,0"),
    "Foods Judged": ("COALESCE ( COUNTROWS ( FILTER ( VALUES ( Commodities[commodity] ), NOT ISBLANK ( [Food Typical Gap] ) ) ), 0 )", "#,0"),
    "Biggest Food Mover": ('VAR t = FILTER ( ADDCOLUMNS ( VALUES ( Commodities[commodity] ), "@g", [Food Typical Gap] ), NOT ISBLANK ( [@g] ) )\n'
                           "RETURN MAXX ( TOPN ( 1, t, ABS ( [@g] ), DESC ), Commodities[commodity] )", None),
    "Biggest Food Gap": ('VAR f = [Biggest Food Mover]\nRETURN CALCULATE ( [Food Typical Gap], Commodities[commodity] = f )', '+0%;-0%;0%'),
    "Biggest Food Colour": (colour_rule("[Biggest Food Gap]"), None),
    "Biggest Food Label": ('"biggest: " & [Biggest Food Mover]', None),
    "Foods Subtitle": ('[Price Type Label] & " prices · " & FORMAT ( [Report Month], "MMMM yyyy" ) & " · each food against the same month in the last five years"', None),

    # ---- page 4: regions
    "Region Typical Gap": (latest("MEDIAN ( Prices[gap_from_normal] )"), '+0%;-0%;0%'),
    "Region Gap Colour": (colour_rule("[Region Typical Gap]"), None),
    "Regions Reporting": ("COALESCE ( COUNTROWS ( FILTER ( VALUES ( Markets[region] ), NOT ISBLANK ( [Market Price] ) ) ), 0 )", "#,0"),
    "Lowest Region": ('VAR t = FILTER ( ADDCOLUMNS ( VALUES ( Markets[region] ), "@g", [Region Typical Gap] ), NOT ISBLANK ( [@g] ) )\nRETURN MAXX ( TOPN ( 1, t, [@g], ASC ), Markets[region] )', None),
    "Highest Region": ('VAR t = FILTER ( ADDCOLUMNS ( VALUES ( Markets[region] ), "@g", [Region Typical Gap] ), NOT ISBLANK ( [@g] ) )\nRETURN MAXX ( TOPN ( 1, t, [@g], DESC ), Markets[region] )', None),
    "Lowest Region Gap": ('VAR r = [Lowest Region]\nRETURN CALCULATE ( [Region Typical Gap], Markets[region] = r )', '+0%;-0%;0%'),
    "Highest Region Gap": ('VAR r = [Highest Region]\nRETURN CALCULATE ( [Region Typical Gap], Markets[region] = r )', '+0%;-0%;0%'),
    "Lowest Region Colour": (colour_rule("[Lowest Region Gap]"), None),
    "Highest Region Colour": (colour_rule("[Highest Region Gap]"), None),
    "Lowest Region Label": ('"lowest: " & [Lowest Region]', None),
    "Highest Region Label": ('"highest: " & [Highest Region]', None),
    "Regions Title": ('[Food Label] & " prices by region"', None),
    "Regions Subtitle": ('[Price Type Label] & " prices · " & FORMAT ( [Latest Month], "MMMM yyyy" ) & " · against the same month in the last five years"', None),

    # ---- page 5: next month
    "Forecast Month Label": ('FORMAT ( MAX ( Forecast[forecast_month] ), "MMM yyyy" )', None),
    "Expected Cheaper": ('COALESCE ( CALCULATE ( DISTINCTCOUNT ( Forecast[market_code] ), Forecast[forecast_direction] = "Too cheap" ), 0 )', "#,0"),
    "Expected Dearer": ('COALESCE ( CALCULATE ( DISTINCTCOUNT ( Forecast[market_code] ), Forecast[forecast_direction] = "Too expensive" ), 0 )', "#,0"),
    "Range Start": ("MAX ( Forecast[forecast_low] )", "#,0"),
    "Range Width": ("MAX ( Forecast[forecast_high] ) - MAX ( Forecast[forecast_low] )", "#,0"),
    "Forecast Price": ("MAX ( Forecast[forecast_price] )", "#,0"),
    "Forecast Usual": ("MAX ( Forecast[normal_price] )", "#,0"),
    "Last Price": ("MAX ( Forecast[last_price] )", "#,0"),
    "Likely Range": ('IF ( NOT ISBLANK ( [Range Start] ), FORMAT ( MAX ( Forecast[forecast_low] ), "#,0" ) & " to " & FORMAT ( MAX ( Forecast[forecast_high] ), "#,0" ) )', None),
    "Expected": ('VAR l = MAX ( Forecast[forecast_alert_level] )\nRETURN SWITCH ( l, "alert high", "Much dearer", "watch high", "Dearer", "normal", "Normal",\n'
                 '    "watch low", "Cheaper", "alert low", "Much cheaper", "not enough history", "Not judged" )', None),
    # colour by the forecast's verdict, so "not enough history" stays neutral even when a gap exists
    "Expected Colour": (f'SWITCH ( MAX ( Forecast[forecast_direction] ), "Too cheap", "{LOW}", "Too expensive", "{HIGH}", "Normal", "{NORMAL}", "{NOT_JUDGED}" )', None),
    "Forecast Title": ('[Food Label] & ": what next month may bring"', None),
    "Forecast Subtitle": ('"Forecast for " & [Forecast Month Label] & " · " & [Price Type Label] & " prices · FCFA per kg"', None),

    # ---- page 6: data quality (no filters on that page)
    "Suspect Prices": ("COUNTROWS ( Suspect )", "#,0"),
    "Reporting Fraction": ('CALCULATE ( COUNTROWS ( Markets ), Markets[is_reporting_now] = TRUE () ) & " of " & COUNTROWS ( Markets )', None),
    "Average Coverage": ("AVERAGE ( Markets[coverage] )", "0%"),
    "Price Records": ("COUNTROWS ( Prices )", "#,0"),
    "Records Latest Year": ("VAR y = YEAR ( MAX ( Prices[price_month] ) )\nRETURN CALCULATE ( COUNTROWS ( Prices ), FILTER ( ALL ( Prices[price_month] ), YEAR ( Prices[price_month] ) = y ) )", "#,0"),
})

# The forecast's tested score comes from the backtest, so the report never states a number by hand
_backtest = json.loads((POWERBI.parent / "reports" / "forecast_backtest.json").read_text(encoding="utf-8"))
MEASURES["Direction Score"] = (str(_backtest["model"]["direction_right_on_big_moves"]), "0%")


def measures_table() -> str:
    out = ["table _Measures", ""]
    for name, (dax, fmt) in MEASURES.items():
        if "\n" in dax:
            body = "\n".join("\t\t\t" + line for line in dax.splitlines())
            out.append(f"\tmeasure {q(name)} = ```\n{body}\n\t\t\t```")
        else:
            out.append(f"\tmeasure {q(name)} = {dax}")
        if fmt:
            out.append(f"\t\tformatString: {fmt}")
        out.append("")
    out.append("\tpartition _Measures = calculated\n\t\tmode: import\n\t\tsource = ROW(\"x\",0)\n")
    return "\n".join(out)


def build_model(root: Path) -> None:
    sm = root / f"{NAME}.SemanticModel"
    d = sm / "definition"
    (d / "tables").mkdir(parents=True)
    write_json(sm / "definition.pbism", {"$schema": "https://developer.microsoft.com/json-schemas/fabric/item/semanticModel/definitionProperties/1.0.0/schema.json", "version": "4.2", "settings": {}})
    write_json(sm / ".platform", platform("SemanticModel"))
    (d / "database.tmdl").write_text("database\n\tcompatibilityLevel: 1606\n\n", encoding="utf-8")
    tables = ["Prices", "Markets", "Commodities", "PriceType", "Calendar", "Forecast", "Suspect", "_Measures"]
    (d / "model.tmdl").write_text(
        "model Model\n\tculture: en-US\n\tdefaultPowerBIDataSourceVersion: powerBI_V3\n\tsourceQueryCulture: en-US\n"
        "\tdataAccessOptions\n\t\tlegacyRedirects\n\t\treturnErrorValuesAsNull\n\n"
        + "".join(f"ref table {q(t)}\n" for t in tables), encoding="utf-8")
    (d / "expressions.tmdl").write_text(
        f'expression DataFolder = "{DATA_FOLDER}" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]\n\n'
        "\tannotation PBI_ResultType = Text\n", encoding="utf-8")

    t = d / "tables"
    (t / "Prices.tmdl").write_text(csv_table("Prices", "prices.csv", [
        ("price_month", "dateTime", "mmm yyyy", False), ("market_code", "int64", None, True),
        ("commodity_code", "int64", None, True), ("price_type", "string", None, True),
        ("standard_unit", "string", None, False), ("price_per_unit", "double", "#,0", False),
        ("normal_price", "double", "#,0", False), ("years_of_history", "int64", None, False),
        ("gap_from_normal", "double", "+0%;-0%;0%", False), ("alert_level", "string", None, False),
        ("direction", "string", None, False), ("strength", "string", None, False), ("alert_order", "int64", None, True),
    ]), encoding="utf-8")
    (t / "Markets.tmdl").write_text(csv_table("Markets", "markets.csv", [
        ("market_code", "int64", None, True), ("market", "string", None, False), ("region", "string", None, False),
        ("department", "string", None, False), ("lat", "double", "0.00", True), ("lon", "double", "0.00", True),
        ("first_month", "dateTime", "mmm yyyy", False), ("last_month", "dateTime", "mmm yyyy", False),
        ("months_with_prices", "int64", None, False), ("missing_months", "int64", None, False),
        ("coverage", "double", "0%", False), ("is_reporting_now", "boolean", None, False),
    ]), encoding="utf-8")
    (t / "Commodities.tmdl").write_text(csv_table("Commodities", "commodities.csv", [
        ("commodity_code", "int64", None, True), ("commodity", "string", None, False), ("commodity_category", "string", None, False),
    ]), encoding="utf-8")
    (t / "Forecast.tmdl").write_text(csv_table("Forecast", "forecast.csv", [
        ("forecast_month", "dateTime", "mmm yyyy", False), ("market_code", "int64", None, True),
        ("commodity_code", "int64", None, True), ("price_type", "string", None, True),
        ("last_price", "double", "#,0", False), ("forecast_price", "double", "#,0", False),
        ("forecast_low", "double", "#,0", False), ("forecast_high", "double", "#,0", False),
        ("normal_price", "double", "#,0", False), ("years_of_history", "int64", None, False),
        ("forecast_gap_from_normal", "double", "+0%;-0%;0%", False), ("forecast_alert_level", "string", None, False),
        ("forecast_direction", "string", None, False),
    ]), encoding="utf-8")
    # prices far from the national median, for the Data quality page (no relationships: that page has no filters)
    (t / "Suspect.tmdl").write_text(csv_table("Suspect", "suspect.csv", [
        ("price_month", "dateTime", "mmm yyyy", False), ("market", "string", None, False), ("region", "string", None, False),
        ("commodity", "string", None, False), ("price_type", "string", None, False), ("standard_unit", "string", None, False),
        ("price_per_unit", "double", "#,0", False), ("national_median", "double", "#,0", False),
        ("ratio_to_national", "double", "0.0x", False),
    ]), encoding="utf-8")
    (t / "PriceType.tmdl").write_text(
        "table PriceType\n\n"
        "\tcolumn price_type\n\t\tdataType: string\n\t\tisHidden\n\t\tsummarizeBy: none\n\t\tsourceColumn: [price_type]\n\n"
        "\tcolumn 'Price type'\n\t\tdataType: string\n\t\tsummarizeBy: none\n\t\tsourceColumn: [Price type]\n\n"
        '\tpartition PriceType = calculated\n\t\tmode: import\n\t\tsource = DATATABLE ( "price_type", STRING, "Price type", STRING, { { "retail", "Retail" }, { "wholesale", "Wholesale" } } )\n',
        encoding="utf-8")
    (t / "Calendar.tmdl").write_text(
        "table Calendar\n\tdataCategory: Time\n\n"
        "\tcolumn Date\n\t\tdataType: dateTime\n\t\tisKey\n\t\tformatString: Short Date\n\t\tsummarizeBy: none\n\t\tsourceColumn: [Date]\n\n"
        "\tcolumn 'Month Start' = DATE ( YEAR ( [Date] ), MONTH ( [Date] ), 1 )\n\t\tdataType: dateTime\n\t\tformatString: mmm yyyy\n\t\tsummarizeBy: none\n\n"
        "\tcolumn Month = FORMAT ( [Date], \"mmm yyyy\" )\n\t\tdataType: string\n\t\tsummarizeBy: none\n\t\tsortByColumn: 'Month Start'\n\n"
        "\tcolumn Year = YEAR ( [Date] )\n\t\tdataType: int64\n\t\tformatString: 0\n\t\tsummarizeBy: none\n\n"
        "\tpartition Calendar = calculated\n\t\tmode: import\n\t\tsource = CALENDAR ( DATE ( 2017, 1, 1 ), DATE ( 2026, 12, 31 ) )\n",
        encoding="utf-8")
    (t / "_Measures.tmdl").write_text(measures_table(), encoding="utf-8")

    rels = [("Prices.market_code", "Markets.market_code"), ("Prices.commodity_code", "Commodities.commodity_code"),
            ("Prices.price_type", "PriceType.price_type"), ("Prices.price_month", "Calendar.Date"),
            ("Forecast.market_code", "Markets.market_code"), ("Forecast.commodity_code", "Commodities.commodity_code"),
            ("Forecast.price_type", "PriceType.price_type")]
    (d / "relationships.tmdl").write_text("".join(
        f"relationship r{i}\n\tfromColumn: {a}\n\ttoColumn: {b}\n\n" for i, (a, b) in enumerate(rels)), encoding="utf-8")


# ----------------------------------------------------------------------------- report helpers

def lit(v):
    if isinstance(v, bool):
        s = "true" if v else "false"
    elif isinstance(v, (int, float)):
        s = f"{v}D"
    else:
        s = f"'{v}'"
    return {"expr": {"Literal": {"Value": s}}}


def colour(c):
    return {"solid": {"color": lit(c)}}


def props(**kw):
    return [{"properties": {k: (v if isinstance(v, dict) and ("expr" in v or "solid" in v or "image" in v) else lit(v)) for k, v in kw.items()}}]


def measure(name):
    return {"Measure": {"Expression": {"SourceRef": {"Entity": "_Measures"}}, "Property": name}}


def column(table, name):
    return {"Column": {"Expression": {"SourceRef": {"Entity": table}}, "Property": name}}


def proj(field, label=None):
    ent = field[next(iter(field))]["Expression"]["SourceRef"]["Entity"]
    prop = field[next(iter(field))]["Property"]
    p = {"field": field, "queryRef": f"{ent}.{prop}", "nativeQueryRef": label or prop}
    if label:
        p["displayName"] = label
    return p


def container(transparent=True, title=None):
    c = {"background": props(show=not transparent), "border": props(show=False), "dropShadow": props(show=False),
         "padding": props(top=0, bottom=0, left=0, right=0)}
    c["title"] = props(show=False) if not title else props(show=True, text=title, fontColor=colour(INK), fontSize=12, fontFamily=FONT)
    return c


def visual(name, x, y, w, h, vtype, query, objects=None, extra=None, z=1000):
    v = {"visualType": vtype, "query": {"queryState": query}, "objects": objects or {},
         "visualContainerObjects": container(), "drillFilterOtherVisuals": True}
    if extra:
        v.update(extra)
    return {"$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.14.0/schema.json",
            "name": name, "position": {"x": x, "y": y, "z": z, "height": h, "width": w, "tabOrder": z}, "visual": v}


def card(name, x, y, w, h, m, size, col, label=False, bold=False, align="left", font=FONT):
    objs = {"labels": props(fontSize=size, color=colour(col), fontFamily=font, bold=bold),
            "categoryLabels": props(show=label, fontSize=11, color=colour(MUTED), fontFamily=FONT),
            "wordWrap": props(show=True)}
    v = visual(name, x, y, w, h, "card", {"Values": {"projections": [proj(measure(m))]}}, objs)
    return v


def text_card(name, x, y, w, h, m, size, col, bold=False):
    # Left-aligned text from a measure: a multi-row card with no labels or accent bar
    # (the basic card always centres its value)
    objs = {"dataLabels": props(fontSize=size, color=colour(col), fontFamily=FONT, bold=bold),
            "categoryLabels": props(show=False),
            "card": props(barShow=False, outlineStyle="None", cardPadding=0)}
    return visual(name, x, y, w, h, "multiRowCard", {"Values": {"projections": [proj(measure(m))]}}, objs)


def card_colour_by(v, m):
    # colour a card's value with a measure that returns a hex colour
    v["visual"]["objects"]["labels"][0]["properties"]["color"] = {"solid": {"color": {"expr": measure(m)}}}
    return v


def slicer(name, x, y, w, h, table, col, header, default=None, descending=False):
    # white dropdown box; its label is drawn in the page background
    objs = {"data": props(mode="Dropdown"), "selection": props(singleSelect=True),
            "header": props(show=False),
            "items": props(fontColor=colour(INK), background=colour("#FFFFFF"), textSize=10, fontFamily=FONT),
            "general": [{"properties": {}}]}
    if default is not None:
        objs["general"] = [{"properties": {"filter": {"filter": {
            "Version": 2, "From": [{"Name": "s", "Entity": table, "Type": 0}],
            "Where": [{"Condition": {"In": {"Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "s"}}, "Property": col}}],
                                            "Values": [[{"Literal": {"Value": f"'{default}'"}}]]}}}]}}}}]
    query = {"Values": {"projections": [{**proj(column(table, col)), "active": True}]}}
    v = visual(name, x, y, w, h, "slicer", query, objs)
    v["visual"]["visualContainerObjects"]["background"] = props(show=True, color=colour("#FFFFFF"), transparency=0)
    v["visual"]["visualContainerObjects"]["border"] = props(show=True, color=colour("#FFFFFF"), radius=8)
    if descending:
        v["visual"]["query"]["sortDefinition"] = {"sort": [{"field": column(table, col), "direction": "Descending"}], "isDefaultSort": False}
    return v


def image_ref(item):
    return {"image": {"name": lit(item), "url": {"expr": {"ResourcePackageItem": {"PackageName": "RegisteredResources", "PackageType": 1, "ItemName": item}}},
                      "scaling": lit("Fit")}}


# ----------------------------------------------------------------------------- page 1

def overview_visuals():
    """Page 1 in the Green Sidebar layout. Positions match powerbi/design/page-sidebar.html."""
    v = []
    # sidebar slicers (labels are in the background image)
    v.append(slicer("slFood", 20, 146, 170, 30, "Commodities", "commodity", "Food", default="Maize (white)"))
    v.append(slicer("slType", 20, 206, 170, 30, "PriceType", "Price type", "Price", default="Retail"))
    v.append(slicer("slMonth", 20, 266, 170, 30, "Calendar", "Month", "Month", descending=True))

    # title strip: follows the food and month chosen
    v.append(text_card("tTitle", 232, 12, 820, 38, "Page Title", 20, INK, bold=True))
    v.append(text_card("tSub", 232, 48, 980, 24, "Page Subtitle", 10, MUTED))

    # KPI row: four cards, icons and labels in the background, numbers here
    kw = (1026 - 36) / 4
    kx = [232 + i * (kw + 12) + 78 for i in range(4)]
    v.append(card("k1", kx[0], 84, 160, 46, "Cheap Fraction", 24, LOW, bold=True))
    v.append(card("k2", kx[1], 84, 160, 46, "Markets Too Expensive", 24, HIGH, bold=True))
    v.append(card("k3", kx[2], 84, 160, 46, "Markets Reporting", 24, INK, bold=True))
    v.append(card_colour_by(card("k4", kx[3], 84, 160, 46, "Spotlight Gap", 24, LOW, bold=True), "Spotlight Gap Colour"))
    v.append(text_card("k4Lbl", kx[3], 132, 160, 22, "Biggest Change Label", 9, MUTED))

    # spotlight card
    v.append(text_card("sName", 976, 226, 270, 30, "Spotlight Title", 14, INK, bold=True))
    v.append(card("sNow", 972, 260, 130, 62, "FCFA per kg now", 22, INK, label=True, bold=True))
    v.append(card("sUsual", 1110, 260, 140, 62, "Usual for this month", 22, NORMAL, label=True, bold=True))
    v.append(text_card("sNote", 976, 330, 270, 66, "Spotlight Note", 10, INK))

    # map: scatter of longitude and latitude over a Cameroon outline in the plot area
    tooltips = [proj(measure("Market Price"), "Price (FCFA/kg)"), proj(measure("Market Normal"), "Normal (FCFA/kg)"),
                proj(measure("Gap From Normal"), "Gap from normal"), proj(measure("Market Status"), "Status")]
    map_q = {"Category": {"projections": [{**proj(column("Markets", "market"), "Market"), "active": True}]},
             "X": {"projections": [proj(measure("Map Longitude"), "Longitude")]},
             "Y": {"projections": [proj(measure("Map Latitude"), "Latitude")]},
             "Size": {"projections": [proj(measure("Map Dot Size"), "Dot size")]},
             "Tooltips": {"projections": tooltips}}
    fill_by_measure = [{"properties": {"fill": {"solid": {"color": {"expr": measure("Market Colour")}}}},
                        "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}]}}]
    map_objs = {
        "categoryAxis": props(show=False, start=LON[0], end=LON[1], gridlineShow=False, showAxisTitle=False),
        "valueAxis": props(show=False, start=LAT[0], end=LAT[1], gridlineShow=False, showAxisTitle=False),
        "dataPoint": fill_by_measure,
        "bubbles": props(bubbleSize=-20),
        "categoryLabels": props(show=False),
        "legend": props(show=False),
        "plotArea": [{"properties": {"image": image_ref(MAP_IMAGE), "transparency": lit(0)}}],
    }
    # 331 x 450 keeps the outline's proportions (8.6 degrees wide, 11.7 tall)
    v.append(visual("mapScatter", 246, 244, 331, 450, "scatterChart", map_q, map_objs))

    # gap from normal by market, coloured by alert level
    bar_q = {"Category": {"projections": [{**proj(column("Markets", "market"), "Market"), "active": True}]},
             "Y": {"projections": [proj(measure("Gap From Normal"), "Gap from normal")]},
             "Tooltips": {"projections": tooltips[:2] + tooltips[3:]}}
    bar_objs = {
        "dataPoint": fill_by_measure,
        "categoryAxis": props(show=True, labelColor=colour(INK), fontSize=9, fontFamily=FONT, showAxisTitle=False),
        "valueAxis": props(show=True, labelColor=colour(MUTED), fontSize=8, gridlineShow=True, gridlineColor=colour("#E8F0E3"), showAxisTitle=False),
        "labels": props(show=True, color=colour(INK), fontSize=8, labelDisplayUnits=1),
        "legend": props(show=False),
    }
    bar = visual("barGap", 616, 228, 320, 468, "clusteredBarChart", bar_q, bar_objs)
    bar["visual"]["query"]["sortDefinition"] = {"sort": [{"field": measure("Gap From Normal"), "direction": "Ascending"}], "isDefaultSort": False}
    v.append(bar)

    # markets to watch: the seven markets furthest from normal
    tbl_q = {"Values": {"projections": [proj(column("Markets", "market"), "Market"), proj(measure("Now")),
                                        proj(measure("Usual")), proj(measure("Change"))]}}
    tbl_objs = {
        "columnHeaders": props(fontColor=colour(MUTED), backColor=colour("#FFFFFF"), fontSize=9, fontFamily=FONT),
        "values": props(fontColorPrimary=colour(INK), backColorPrimary=colour("#FFFFFF"), fontColorSecondary=colour(INK),
                        backColorSecondary=colour("#FFFFFF"), fontSize=10, fontFamily=FONT),
        "grid": props(gridVertical=False, gridHorizontal=True, gridHorizontalColor=colour("#EEF3EA"), rowPadding=4),
        "total": props(totals=False),
    }
    # colour the Change column by direction
    tbl_objs["values"].append({"properties": {"fontColor": {"solid": {"color": {"expr": measure("Market Colour")}}}},
                               "selector": {"metadata": "_Measures.Change"}})
    tbl = visual("tblWatch", 972, 474, 276, 222, "tableEx", tbl_q, tbl_objs)
    tbl["visual"]["query"]["sortDefinition"] = {"sort": [{"field": measure("Change"), "direction": "Ascending"}], "isDefaultSort": False}
    v.append(tbl)
    return v


# ----------------------------------------------------------------------------- shared visual builders (pages 2-7)

PAGE_IDS = ["p_overview", "p_markets", "p_foods", "p_regions", "p_forecast", "p_quality", "p_method"]
KW = (1026 - 36) / 4
KX = [232 + i * (KW + 12) + 78 for i in range(4)]   # where each KPI number starts, right of its icon
STATUS = [("Cheaper", LOW), ("Normal", NORMAL), ("Dearer", HIGH)]


def fill_by(m):
    return [{"properties": {"fill": {"solid": {"color": {"expr": measure(m)}}}},
             "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}]}}]


def axis_objs(cat_font=9):
    return {"categoryAxis": props(show=True, labelColor=colour(INK), fontSize=cat_font, fontFamily=FONT, showAxisTitle=False),
            "valueAxis": props(show=True, labelColor=colour(MUTED), fontSize=8, gridlineShow=True, gridlineColor=colour("#E8F0E3"), showAxisTitle=False),
            "legend": props(show=False)}


def sorted_by(v, field, direction="Ascending"):
    v["visual"]["query"]["sortDefinition"] = {"sort": [{"field": field, "direction": direction}], "isDefaultSort": False}
    return v


def bar(name, x, y, w, h, cat, value_m, colour_m, label, tooltips=(), horizontal=True, labels=True):
    """One measure per category, each bar coloured by a colour measure."""
    q = {"Category": {"projections": [{**proj(cat[0], cat[1]), "active": True}]},
         "Y": {"projections": [proj(measure(value_m), label)]}}
    if tooltips:
        q["Tooltips"] = {"projections": [proj(measure(t)) for t in tooltips]}
    objs = {**axis_objs(), "dataPoint": fill_by(colour_m), "labels": props(show=labels, color=colour(INK), fontSize=8)}
    return visual(name, x, y, w, h, "clusteredBarChart" if horizontal else "clusteredColumnChart", q, objs)


def stacked(name, x, y, w, h, cat, series, colours, labels=True, hide_first=False):
    """Stacked bars, one series per measure with a fixed colour. hide_first paints the first
    series white, which turns a stacked bar into a floating range bar on a white card."""
    q = {"Category": {"projections": [{**proj(cat[0], cat[1]), "active": True}]},
         "Y": {"projections": [proj(measure(m), lbl) for m, lbl in series]}}
    points = [{"properties": {"fill": colour(c)}, "selector": {"metadata": f"_Measures.{m}"}} for (m, _), c in zip(series, colours)]
    objs = {**axis_objs(), "dataPoint": points, "labels": props(show=labels, color=colour("#FFFFFF"), fontSize=8)}
    if hide_first:
        objs["labels"] = props(show=False)
    return visual(name, x, y, w, h, "barChart", q, objs)


def table(name, x, y, w, h, fields, colour_col=None, colour_m=None, font=10, widths=None):
    """fields: list of projections. colour_col (a measure name) gets its text coloured by colour_m.
    widths: fixed column widths in pixels, in field order, so no column is cut off."""
    objs = {"columnHeaders": props(fontColor=colour(MUTED), backColor=colour("#FFFFFF"), fontSize=9, fontFamily=FONT),
            "values": props(fontColorPrimary=colour(INK), backColorPrimary=colour("#FFFFFF"), fontColorSecondary=colour(INK),
                            backColorSecondary=colour("#FFFFFF"), fontSize=font, fontFamily=FONT, wordWrap=False),
            "grid": props(gridVertical=False, gridHorizontal=True, gridHorizontalColor=colour("#EEF3EA"), rowPadding=4),
            "total": props(totals=False)}
    if colour_col:
        objs["values"].append({"properties": {"fontColor": {"solid": {"color": {"expr": measure(colour_m)}}}},
                               "selector": {"metadata": f"_Measures.{colour_col}"}})
    if widths:
        objs["columnWidth"] = [{"properties": {"value": lit(float(wd))}, "selector": {"metadata": f["queryRef"]}}
                               for f, wd in zip(fields, widths)]
    return visual(name, x, y, w, h, "tableEx", {"Values": {"projections": fields}}, objs)


def title_strip(title_m=None, sub_m=None):
    v = []
    if title_m:
        v.append(text_card("tTitle", 232, 12, 820, 38, title_m, 20, INK, bold=True))
    if sub_m:
        v.append(text_card("tSub", 232, 48, 1000, 24, sub_m, 10, MUTED))
    return v


def kpi(i, m, col=INK, colour_m=None, label_m=None, name=None):
    """A KPI number in tile i (0-3); its icon and fixed label are in the background."""
    c = card(name or f"k{i + 1}", KX[i], 84, 160, 46, m, 24, col, bold=True)
    v = [card_colour_by(c, colour_m) if colour_m else c]
    if label_m:
        v.append(text_card(f"k{i + 1}Lbl", KX[i], 132, 168, 22, label_m, 8, MUTED))
    return v


def sidebar_slicers(names):
    """Sidebar dropdowns in the background's label slots (128, 188, 248, 308)."""
    spec = {"Food": ("slFood", "Commodities", "commodity", "Maize (white)", False),
            "Price": ("slType", "PriceType", "Price type", "Retail", False),
            "Month": ("slMonth", "Calendar", "Month", None, True),
            "Market": ("slMarket", "Markets", "market", "Maroua", False)}
    out = []
    for i, n in enumerate(names):
        vid, tbl, col, default, desc = spec[n]
        out.append(slicer(vid, 20, 146 + i * 60, 170, 30, tbl, col, n, default=default, descending=desc))
    return out


def nav_buttons(current):
    """Transparent buttons over the sidebar page links. In Power BI Desktop, Ctrl+click to follow them."""
    out = []
    for i, target in enumerate(PAGE_IDS):
        if target == current:
            continue
        b = visual(f"nav{i}", 10, 372 + i * 25, 180, 22, "actionButton", {}, {
            "icon": [{"properties": {"shapeType": lit("blank")}, "selector": {"id": "default"}}],
            "outline": [{"properties": {"show": lit(False)}, "selector": {"id": "default"}}],
            "fill": [{"properties": {"show": lit(False)}, "selector": {"id": "default"}}],
            "text": [{"properties": {"show": lit(False)}, "selector": {"id": "default"}}],
        })
        b["visual"]["query"] = None
        del b["visual"]["query"]
        b["visual"]["visualContainerObjects"]["visualLink"] = props(show=True, type="PageNavigation", navigationSection=target)
        b["howCreated"] = "InsertVisualButton"   # belongs on the container, not inside "visual"
        out.append(b)
    return out


# ----------------------------------------------------------------------------- pages 2-7

def markets_visuals():
    v = sidebar_slicers(["Food", "Price", "Month", "Market"]) + title_strip("Market Page Title", "Market Page Subtitle")
    v += kpi(0, "Latest Price") + kpi(1, "Latest Usual", NORMAL)
    v += kpi(2, "Latest Change", LOW, "Latest Change Colour") + kpi(3, "Months With Prices")
    # price and usual price over time
    q = {"Category": {"projections": [{**proj(column("Calendar", "Month Start"), "Month"), "active": True}]},
         "Y": {"projections": [proj(measure("Monthly Price"), "Price"), proj(measure("Monthly Usual"), "Usual for that month")]}}
    objs = {**axis_objs(8),
            "dataPoint": [{"properties": {"fill": colour(GREEN)}, "selector": {"metadata": "_Measures.Monthly Price"}},
                          {"properties": {"fill": colour(NORMAL)}, "selector": {"metadata": "_Measures.Monthly Usual"}}],
            "lineStyles": [{"properties": {"strokeWidth": lit(3), "showMarker": lit(False)}},
                           {"properties": {"lineStyle": lit("dashed"), "strokeWidth": lit(2)}, "selector": {"metadata": "_Measures.Monthly Usual"}}],
            "labels": props(show=False)}
    v.append(visual("lineMarket", 246, 226, 1000, 240, "lineChart", q, objs))
    v.append(bar("col12", 246, 540, 572, 156, (column("Calendar", "Month Start"), "Month"), "Gap Last 12 Months", "Gap 12 Colour",
                 "Change from usual", horizontal=False))
    for i in range(4):
        v.append(text_card(f"facts{i + 1}", 864, 528 + i * 34, 380, 30, f"Market Facts {i + 1}", 11, INK))
    return v


def foods_visuals():
    v = sidebar_slicers(["Price", "Month"]) + title_strip(None, "Foods Subtitle")
    v += kpi(0, "Foods Mostly Cheaper", LOW) + kpi(1, "Foods Mostly Dearer", HIGH) + kpi(2, "Foods Judged")
    v += kpi(3, "Biggest Food Gap", LOW, "Biggest Food Colour", "Biggest Food Label")
    food = (column("Commodities", "commodity"), "Food")
    v.append(sorted_by(stacked("stFoods", 246, 248, 476, 448, food,
                               [("Food Cheaper", "Cheaper"), ("Food Normal", "Normal"), ("Food Dearer", "Dearer")],
                               [LOW, NORMAL, HIGH]), measure("Food Cheaper"), "Descending"))
    v.append(sorted_by(bar("barFoodGap", 760, 226, 486, 240, food, "Food Typical Gap", "Food Gap Colour", "Typical change"),
                       measure("Food Typical Gap")))
    v.append(sorted_by(table("tblFoods", 760, 540, 486, 156,
                             [proj(column("Commodities", "commodity"), "Food"), proj(measure("Food Typical Price"), "Now"),
                              proj(measure("Food Usual"), "Usual"), proj(measure("Food Unit"), "Per"), proj(measure("Food Typical Gap"), "Change")],
                             "Food Typical Gap", "Food Gap Colour", font=9), measure("Food Typical Gap")))
    return v


def regions_visuals():
    v = sidebar_slicers(["Food", "Price", "Month"]) + title_strip("Regions Title", "Regions Subtitle")
    v += kpi(0, "Regions Reporting") + kpi(1, "Lowest Region Gap", LOW, "Lowest Region Colour", "Lowest Region Label")
    v += kpi(2, "Highest Region Gap", HIGH, "Highest Region Colour", "Highest Region Label") + kpi(3, "Markets Judged")
    region = (column("Markets", "region"), "Region")
    v.append(sorted_by(bar("barRegion", 246, 226, 476, 240, region, "Region Typical Gap", "Region Gap Colour", "Typical change"),
                       measure("Region Typical Gap")))
    v.append(sorted_by(stacked("stRegion", 246, 540, 476, 156, region,
                               [("Cheaper Markets", "Cheaper"), ("Normal Markets", "Normal"), ("Dearer Markets", "Dearer")],
                               [LOW, NORMAL, HIGH]), measure("Cheaper Markets"), "Descending"))
    v.append(sorted_by(table("tblRegions", 760, 232, 486, 460,
                             [proj(column("Markets", "region"), "Region"), proj(measure("Markets Reporting"), "Reporting"),
                              proj(measure("Cheaper Markets"), "Cheaper"), proj(measure("Dearer Markets"), "Dearer"),
                              proj(measure("Region Typical Gap"), "Typical change")],
                             "Region Typical Gap", "Region Gap Colour", font=11), measure("Region Typical Gap")))
    return v


def forecast_visuals():
    v = sidebar_slicers(["Food", "Price"]) + title_strip("Forecast Title", "Forecast Subtitle")
    v += kpi(0, "Forecast Month Label") + kpi(1, "Expected Cheaper", LOW) + kpi(2, "Expected Dearer", HIGH) + kpi(3, "Direction Score", GREEN)
    market = (column("Markets", "market"), "Market")
    rng = stacked("rngForecast", 246, 228, 592, 452, market, [("Range Start", "From"), ("Range Width", "Likely range")],
                  ["#FFFFFF", GREEN], hide_first=True)
    rng["visual"]["query"]["queryState"]["Tooltips"] = {"projections": [proj(measure("Forecast Price"), "Best guess"),
                                                                         proj(measure("Forecast Usual"), "Usual for that month"),
                                                                         proj(measure("Expected"))]}
    v.append(sorted_by(rng, measure("Range Start")))
    v.append(sorted_by(table("tblForecast", 880, 228, 366, 452,
                             [proj(column("Markets", "market"), "Market"), proj(measure("Last Price"), "Now"),
                              proj(measure("Likely Range"), "Likely next month"), proj(measure("Expected"), "Expected")],
                             "Expected", "Expected Colour", font=9, widths=[100, 42, 108, 96]), measure("Last Price")))
    return v


def quality_visuals():
    v = kpi(0, "Suspect Prices", HIGH) + kpi(1, "Reporting Fraction") + kpi(2, "Average Coverage") + kpi(3, "Records Latest Year")
    yr = {"Category": {"projections": [{**proj(column("Calendar", "Year"), "Year"), "active": True}]},
          "Y": {"projections": [proj(measure("Price Records"), "Price records")]}}
    col = visual("colRecords", 246, 226, 476, 240, "clusteredColumnChart", yr,
                 {**axis_objs(9), "dataPoint": props(fill=colour(GREEN)), "labels": props(show=True, color=colour(INK), fontSize=8)})
    v.append(sorted_by(col, column("Calendar", "Year")))
    v.append(sorted_by(table("tblSuspect", 760, 228, 486, 464,
                             [proj(column("Suspect", "price_month"), "Month"), proj(column("Suspect", "market"), "Market"),
                              proj(column("Suspect", "commodity"), "Food"), proj(column("Suspect", "price_per_unit"), "Price"),
                              proj(column("Suspect", "national_median"), "Typical"), proj(column("Suspect", "ratio_to_national"), "Times")],
                             font=9, widths=[60, 122, 136, 50, 48, 50]), column("Suspect", "ratio_to_national"), "Descending"))
    return v


def method_visuals():
    return []


# ----------------------------------------------------------------------------- report

THEME = {
    "name": "FoodPriceWatchGreen",
    "dataColors": [GREEN, LOW, HIGH, GOLD, "#8BC34A", NORMAL, "#6DAA45", "#C9C6BB"],
    "background": "#FFFFFF", "foreground": INK, "tableAccent": GREEN,
    "textClasses": {"label": {"fontFace": FONT, "color": INK, "fontSize": 9}, "callout": {"fontFace": FONT, "color": INK},
                    "title": {"fontFace": "Segoe UI Semibold", "color": INK}, "header": {"fontFace": "Segoe UI Semibold", "color": INK}},
    "visualStyles": {"*": {"*": {"background": [{"show": False}], "border": [{"show": False}], "dropShadow": [{"show": False}]}}},
}


def platform(kind):
    return {"$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
            "metadata": {"type": kind, "displayName": NAME}, "config": {"version": "2.0", "logicalId": str(uuid.uuid4())}}


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def build_report(root: Path) -> None:
    rp = root / f"{NAME}.Report"
    d = rp / "definition"
    write_json(rp / "definition.pbir", {"$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json",
                                        "version": "4.0", "datasetReference": {"byPath": {"path": f"../{NAME}.SemanticModel"}}})
    write_json(rp / ".platform", platform("Report"))
    res = rp / "StaticResources"
    (res / "SharedResources" / "BaseThemes").mkdir(parents=True)
    shutil.copy(BASE_THEME, res / "SharedResources" / "BaseThemes" / "CY24SU10.json")
    write_json(res / "RegisteredResources" / "FoodPriceWatchGreen.json", THEME)
    images = [f"bg_{p}.png" for p in ["overview", "markets", "foods", "regions", "forecast", "quality", "method"]] + [MAP_IMAGE]
    for img in images:
        shutil.copy(IMAGES / img, res / "RegisteredResources" / img)

    write_json(d / "version.json", {"$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/versionMetadata/1.0.0/schema.json", "version": "2.0.0"})
    write_json(d / "report.json", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/report/3.3.0/schema.json",
        "themeCollection": {
            "baseTheme": {"name": "CY24SU10", "reportVersionAtImport": {"visual": "1.8.95", "report": "2.0.95", "page": "1.3.95"}, "type": "SharedResources"},
            "customTheme": {"name": "FoodPriceWatchGreen.json", "reportVersionAtImport": {"visual": "2.1.0", "report": "2.1.0", "page": "2.0.0"}, "type": "RegisteredResources"}},
        "resourcePackages": [
            {"name": "SharedResources", "type": "SharedResources", "items": [{"name": "CY24SU10", "path": "BaseThemes/CY24SU10.json", "type": "BaseTheme"}]},
            {"name": "RegisteredResources", "type": "RegisteredResources",
             "items": [{"name": "FoodPriceWatchGreen.json", "path": "FoodPriceWatchGreen.json", "type": "CustomTheme"}]
                      + [{"name": i, "path": i, "type": "Image"} for i in images]}],
        "settings": {"useStylableVisualContainerHeader": True, "exportDataMode": "AllowSummarized", "defaultDrillFilterOtherVisuals": True,
                     "allowChangeFilterTypes": True, "useEnhancedTooltips": True, "useDefaultAggregateDisplayName": True}})

    pages = {"p_overview": ("This month", "bg_overview.png", overview_visuals()),
             "p_markets": ("Markets", "bg_markets.png", markets_visuals()),
             "p_foods": ("Foods", "bg_foods.png", foods_visuals()),
             "p_regions": ("Regions", "bg_regions.png", regions_visuals()),
             "p_forecast": ("Next month", "bg_forecast.png", forecast_visuals()),
             "p_quality": ("Data quality", "bg_quality.png", quality_visuals()),
             "p_method": ("Method", "bg_method.png", method_visuals())}
    for pid, (_, _, visuals) in pages.items():
        visuals.extend(nav_buttons(pid))
    write_json(d / "pages" / "pages.json", {"$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.1.0/schema.json",
                                            "pageOrder": list(pages), "activePageName": "p_overview"})
    for pid, (title, bg, visuals) in pages.items():
        write_json(d / "pages" / pid / "page.json", {
            "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.1.0/schema.json",
            "name": pid, "displayName": title, "displayOption": "FitToPage", "height": 720, "width": 1280,
            "objects": {"background": [{"properties": {"image": image_ref(bg), "transparency": lit(0)}}],
                        "outspace": [{"properties": {"color": colour("#EEF6EA")}}]}})
        for i, vis in enumerate(visuals):
            vis["position"]["z"] = vis["position"]["tabOrder"] = (i + 1) * 1000
            write_json(d / "pages" / pid / "visuals" / vis["name"] / "visual.json", vis)


def main() -> int:
    root = POWERBI
    for p in [root / f"{NAME}.SemanticModel", root / f"{NAME}.Report"]:
        if p.exists():
            shutil.rmtree(p)
    build_model(root)
    build_report(root)
    write_json(root / f"{NAME}.pbip", {"$schema": "https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/1.0.0/schema.json",
                                       "version": "1.0", "artifacts": [{"report": {"path": f"{NAME}.Report"}}], "settings": {"enableAutoRecovery": True}})
    print(f"Built {root / (NAME + '.pbip')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
