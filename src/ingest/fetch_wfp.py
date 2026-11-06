"""Fetch the latest WFP food price data for Cameroon from HDX.

Step 1 of the pipeline. Runs once a month (GitHub Actions) or by hand:

    python -m src.ingest.fetch_wfp

What it does:
1. Asks the HDX API when the Cameroon food price dataset was last updated.
2. If that is the same as the copy we already have, it stops. Nothing to do.
3. Otherwise it downloads the CSV, checks it looks right, and saves it to
   data/raw/ along with a manifest that records every fetch.

Only the Python standard library is used, so this step has no dependencies.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import logging
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HDX_API = "https://data.humdata.org/api/3/action/package_show?id={dataset}"
DATASET_ID = "wfp-food-prices-for-cameroon"
# HDX names the two files in this dataset "Cameroon - Food Prices" and "Cameroon - Markets"
RESOURCES = {
    "prices": "Cameroon - Food Prices",
    "markets": "Cameroon - Markets",
}

REQUIRED_PRICE_COLUMNS = {
    "date", "admin1", "admin2", "market", "market_id", "latitude", "longitude",
    "category", "commodity", "commodity_id", "unit", "priceflag", "pricetype",
    "currency", "price", "usdprice",
}
# A real monthly file has tens of thousands of rows; far fewer means a broken download
MIN_PRICE_ROWS = 10_000

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "data" / "raw"
MANIFEST_PATH = RAW_DIR / "manifest.json"

USER_AGENT = "cameroon-food-price-watch/0.1 (+https://github.com/bihbrandysango-cloud)"

log = logging.getLogger("fetch_wfp")


class ValidationError(Exception):
    """The downloaded file is not what we expect."""


class BlockedError(Exception):
    """The server's bot protection challenged the request instead of sending data."""


def http_get(url: str, retries: int = 3, timeout: int = 60) -> bytes:
    """GET a URL, retrying with a growing wait if the server is slow or down."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                # HDX's firewall answers scripted downloads with an empty 202 "challenge"
                if response.headers.get("x-amzn-waf-action") or response.status == 202:
                    raise BlockedError(
                        f"{url} returned a bot-check challenge, not data. "
                        "Download the file by hand and use --from-file."
                    )
                return response.read()
        except (urllib.error.URLError, TimeoutError) as error:
            if attempt == retries:
                raise
            wait = 5 * attempt
            log.warning("Attempt %d failed (%s). Retrying in %ds.", attempt, error, wait)
            time.sleep(wait)
    raise RuntimeError("unreachable")


def get_dataset_info(dataset: str = DATASET_ID) -> dict:
    """Return HDX metadata for the dataset: when it changed and where its files are."""
    payload = json.loads(http_get(HDX_API.format(dataset=dataset)))
    if not payload.get("success"):
        raise RuntimeError(f"HDX API returned an error for {dataset}")
    result = payload["result"]
    urls = {}
    for key, name in RESOURCES.items():
        match = [r for r in result["resources"] if r["name"] == name]
        if not match:
            raise RuntimeError(f"HDX dataset has no file called '{name}'")
        urls[key] = match[0]["url"]
    return {
        "last_modified": result["last_modified"],
        "dataset_date": result.get("dataset_date"),
        "urls": urls,
    }


def validate_prices(raw: bytes) -> dict:
    """Check the price CSV and return a short summary of it.

    Raises ValidationError if columns are missing, the file is too small,
    or prices are not numbers.
    """
    text = raw.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    missing = REQUIRED_PRICE_COLUMNS - set(reader.fieldnames or [])
    if missing:
        raise ValidationError(f"Missing columns: {sorted(missing)}")

    rows = 0
    dates, markets, commodities = set(), set(), set()
    for line_no, row in enumerate(reader, start=2):
        # Some HDX files carry a second header row of #hxl tags; skip it
        if row["date"].startswith("#"):
            continue
        try:
            float(row["price"])
        except ValueError:
            raise ValidationError(f"Line {line_no}: price is not a number: {row['price']!r}")
        rows += 1
        dates.add(row["date"])
        markets.add(row["market"])
        commodities.add(row["commodity"])

    if rows < MIN_PRICE_ROWS:
        raise ValidationError(f"Only {rows} rows; expected at least {MIN_PRICE_ROWS}")

    return {
        "rows": rows,
        "first_date": min(dates),
        "last_date": max(dates),
        "markets": len(markets),
        "commodities": len(commodities),
    }


def load_manifest(path: Path = MANIFEST_PATH) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"source": f"https://data.humdata.org/dataset/{DATASET_ID}", "fetches": []}


def is_new_version(manifest: dict, hdx_last_modified: str) -> bool:
    """True when HDX has a version we have not saved yet."""
    if not manifest["fetches"]:
        return True
    return manifest["fetches"][-1]["hdx_last_modified"] != hdx_last_modified


def fetch(force: bool = False, raw_dir: Path = RAW_DIR, from_file: Path | None = None) -> bool:
    """Run the fetch. Returns True if new data was saved.

    from_file: a prices CSV downloaded by hand from HDX, used instead of downloading.
    """
    manifest_path = raw_dir / "manifest.json"
    manifest = load_manifest(manifest_path)

    info = get_dataset_info()
    log.info("HDX last updated the dataset at %s", info["last_modified"])

    if not force and not is_new_version(manifest, info["last_modified"]):
        log.info("We already have this version. Nothing to do.")
        return False

    if from_file:
        prices_raw = from_file.read_bytes()
        markets_raw = None
    else:
        prices_raw = http_get(info["urls"]["prices"])
        markets_raw = http_get(info["urls"]["markets"])
    summary = validate_prices(prices_raw)

    raw_dir.mkdir(parents=True, exist_ok=True)
    # Overwrite one file per source: git keeps the history, so no dated copies needed
    (raw_dir / "wfp_food_prices_cmr.csv").write_bytes(prices_raw)
    if markets_raw is not None:
        (raw_dir / "wfp_markets_cmr.csv").write_bytes(markets_raw)

    manifest["fetches"].append({
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "method": f"manual file {from_file.name}" if from_file else "automatic download",
        "hdx_last_modified": info["last_modified"],
        "sha256": hashlib.sha256(prices_raw).hexdigest(),
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
    parser.add_argument("--force", action="store_true", help="download even if unchanged")
    parser.add_argument("--from-file", type=Path, help="use a prices CSV downloaded by hand")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        fetch(force=args.force, from_file=args.from_file)
    except ValidationError as error:
        log.error("Downloaded file failed checks, nothing saved: %s", error)
        return 1
    except BlockedError as error:
        log.error("%s", error)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
