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
    "Spotlight Note": ('IF ( [Spotlight Gap] < 0,\n    "Cheap for families who buy it. For farmers it means selling below what seed and fertiliser cost.",\n    "Hard on families who buy it. Farmers with stock to sell may gain." )', None),
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
    "Biggest Change Label": ('"biggest change: " & [Spotlight Market]', None),
    "Spotlight Gap Colour": (f'IF ( [Spotlight Gap] < 0, "{LOW}", "{HIGH}" )', None),
    "Watch Rank": ("VAR g = [Gap From Normal]\nRETURN\n    IF ( NOT ISBLANK ( g ),\n        RANKX ( FILTER ( ALLSELECTED ( Markets[market] ), NOT ISBLANK ( [Gap From Normal] ) ), ABS ( [Gap From Normal] ), ABS ( g ), DESC ) )", "0"),
    "Now": ("VAR r = [Watch Rank]\nRETURN IF ( NOT ISBLANK ( r ) && r <= 7, [Market Price] )", "#,0"),
    "Usual": ("VAR r = [Watch Rank]\nRETURN IF ( NOT ISBLANK ( r ) && r <= 7, [Market Normal] )", "#,0"),
    "Change": ("VAR r = [Watch Rank]\nRETURN IF ( NOT ISBLANK ( r ) && r <= 7, [Gap From Normal] )", '+0%;-0%;0%'),
}


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
    tables = ["Prices", "Markets", "Commodities", "PriceType", "Calendar", "Forecast", "_Measures"]
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
    images = [BACKGROUND, MAP_IMAGE]
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

    pages = {"p_overview": ("This month", BACKGROUND, overview_visuals())}
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
