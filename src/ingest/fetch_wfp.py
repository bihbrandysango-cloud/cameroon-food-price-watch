"""Fetch WFP food prices for Cameroon from HDX HAPI, the Humanitarian API.

Step 1 of the pipeline. Runs once a month (GitHub Actions) or by hand:

    python -m src.ingest.fetch_wfp            # update the last few months
    python -m src.ingest.fetch_wfp --full     # rebuild the whole history

HAPI needs an app identifier: base64 of "app_name:email". It is read from the
HAPI_APP_IDENTIFIER environment variable so the email never sits in the code.

What it does:
1. Downloads prices from HAPI page by page (at most 10,000 rows a page).
   The first run takes the full history. Later runs take only the last
   REFRESH_MONTHS months, because WFP sometimes corrects recent prices.
2. Checks the rows look right.
3. Merges them into data/raw/wfp_food_prices_cmr.csv: new rows are added and
   corrected rows replace old ones.
4. Saves only if something changed, and records every run in a manifest.

Only the Python standard library is used, so this step has no dependencies.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import http.client
import io
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

HAPI_URL = "https://hapi.humdata.org/api/v2/food-security-nutrition-poverty/food-prices-market-monitor"
LOCATION = "CMR"
# HAPI allows 10,000 rows a call, but big pages often arrive cut off, so ask for fewer
PAGE_SIZE = 2_000
REFRESH_MONTHS = 6

COLUMNS = [
    "reference_period_start", "reference_period_end", "admin1_code", "admin1_name",
    "admin2_code", "admin2_name", "market_code", "market_name", "lat", "lon",
    "commodity_category", "commodity_code", "commodity_name", "unit", "price_flag",
    "price_type", "currency_code", "price",
]
# One price per market, food, unit, price type and flag, per month
KEY = ("market_code", "commodity_code", "unit", "price_type", "price_flag", "reference_period_start")

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "data" / "raw"
DATA_FILE = "wfp_food_prices_cmr.csv"

log = logging.getLogger("fetch_wfp")


class ValidationError(Exception):
    """The data from HAPI is not what we expect."""


def http_get_json(url: str, retries: int = 5, timeout: int = 300) -> dict:
    """GET a URL and parse JSON, retrying with a growing wait if the server is slow,
    down, or sends a cut-off response."""
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read())
        except (urllib.error.URLError, TimeoutError, http.client.IncompleteRead,
                json.JSONDecodeError) as error:
            if attempt == retries:
                raise
            wait = 10 * attempt
            log.warning("Attempt %d failed (%s). Retrying in %ds.", attempt, error, wait)
            time.sleep(wait)
    raise RuntimeError("unreachable")


def months_back(today: date, months: int) -> str:
    """First day of the month `months` before today, as YYYY-MM-DD."""
    index = today.year * 12 + today.month - 1 - months
    return f"{index // 12:04d}-{index % 12 + 1:02d}-01"


def download(app_identifier: str, start_date: str | None = None) -> list[dict]:
    """Download every Cameroon price row from HAPI, optionally from start_date on."""
    rows: list[dict] = []
    offset = 0
    while True:
        params = {
            "location_code": LOCATION,
            "output_format": "json",
            "limit": PAGE_SIZE,
            "offset": offset,
            "app_identifier": app_identifier,
        }
        if start_date:
            params["start_date"] = start_date
        page = http_get_json(f"{HAPI_URL}?{urllib.parse.urlencode(params)}")["data"]
        rows.extend(page)
        log.info("Page at offset %s: %s rows", f"{offset:,}", f"{len(page):,}")
        if len(page) < PAGE_SIZE:
            return rows
        offset += PAGE_SIZE


def clean(rows: list[dict]) -> list[dict]:
    """Keep our columns, trim dates to YYYY-MM-DD and check every row.

    Raises ValidationError if a column is missing or a price is not a positive number.
    """
    cleaned = []
    for number, row in enumerate(rows, start=1):
        missing = [c for c in COLUMNS if c not in row]
        if missing:
            raise ValidationError(f"Row {number} is missing {missing}")
        try:
            price = float(row["price"])
        except (TypeError, ValueError):
            raise ValidationError(f"Row {number}: price is not a number: {row['price']!r}")
        if price <= 0:
            raise ValidationError(f"Row {number}: price must be above zero, got {price}")
        out = {c: "" if row[c] is None else str(row[c]) for c in COLUMNS}
        out["price"] = str(price)
        out["reference_period_start"] = out["reference_period_start"][:10]
        out["reference_period_end"] = out["reference_period_end"][:10]
        cleaned.append(out)
    return cleaned


def merge(existing: list[dict], fresh: list[dict]) -> list[dict]:
    """Add fresh rows to existing ones. A fresh row replaces an old row with the same key."""
    merged = {tuple(r[k] for k in KEY): r for r in existing}
    merged.update({tuple(r[k] for k in KEY): r for r in fresh})
    return sorted(merged.values(), key=lambda r: tuple(r[k] for k in KEY[::-1]))


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def to_csv_bytes(rows: list[dict]) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def summarise(rows: list[dict]) -> dict:
    dates = [r["reference_period_start"] for r in rows]
    return {
        "rows": len(rows),
        "first_date": min(dates),
        "last_date": max(dates),
        "markets": len({r["market_code"] for r in rows}),
        "commodities": len({r["commodity_code"] for r in rows}),
    }


def load_manifest(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"source": f"{HAPI_URL}?location_code={LOCATION}", "fetches": []}


def fetch(app_identifier: str, full: bool = False, raw_dir: Path = RAW_DIR,
          today: date | None = None) -> bool:
    """Run the fetch. Returns True if the saved data changed."""
    data_path = raw_dir / DATA_FILE
    manifest_path = raw_dir / "manifest.json"
    existing = read_csv(data_path)

    # No saved data yet means we need the whole history
    start_date = None if full or not existing else months_back(today or date.today(), REFRESH_MONTHS)
    log.info("Downloading %s", f"from {start_date}" if start_date else "the full history")

    fresh = clean(download(app_identifier, start_date))
    if not fresh:
        raise ValidationError("HAPI returned no rows")

    # merge() also sorts, so a full run and a refresh write rows in the same order
    merged = merge([] if full else existing, fresh)
    new_bytes = to_csv_bytes(merged)
    new_hash = hashlib.sha256(new_bytes).hexdigest()

    manifest = load_manifest(manifest_path)
    previous = manifest["fetches"][-1].get("sha256") if manifest["fetches"] else None
    if new_hash == previous:
        log.info("No new or corrected prices. Nothing to save.")
        return False

    raw_dir.mkdir(parents=True, exist_ok=True)
    data_path.write_bytes(new_bytes)
    summary = summarise(merged)
    manifest["fetches"].append({
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": "full" if start_date is None else f"refresh from {start_date}",
        "rows_downloaded": len(fresh),
        "rows_added": len(merged) - len(existing) if not full else len(merged),
        "sha256": new_hash,
        **summary,
    })
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    log.info(
        "Saved %s rows, %s markets, %s commodities, %s to %s.",
        f"{summary['rows']:,}", summary["markets"], summary["commodities"],
        summary["first_date"], summary["last_date"],
    )
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--full", action="store_true", help="re-download the whole history")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    app_identifier = os.environ.get("HAPI_APP_IDENTIFIER")
    if not app_identifier:
        log.error(
            "Set HAPI_APP_IDENTIFIER to base64 of 'app_name:email'. "
            "See https://hdx-hapi.readthedocs.io/en/latest/getting-started/"
        )
        return 2
    try:
        fetch(app_identifier, full=args.full)
    except ValidationError as error:
        log.error("Data failed checks, nothing saved: %s", error)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
