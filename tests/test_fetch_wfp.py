"""Tests for the fetch step. They use small fake files, so no internet is needed."""

import pytest

from src.ingest import fetch_wfp
from src.ingest.fetch_wfp import ValidationError, is_new_version, validate_prices

HEADER = (
    "date,admin1,admin2,market,market_id,latitude,longitude,category,commodity,"
    "commodity_id,unit,priceflag,pricetype,currency,price,usdprice\n"
)
ROW = (
    "2026-09-15,Extrême-Nord,Diamare,Maroua,1,10.6,14.3,cereals and tubers,"
    "Maize (white),67,KG,actual,Retail,XAF,{price},0.35\n"
)


def make_csv(rows: int, price: str = "200") -> bytes:
    return (HEADER + ROW.format(price=price) * rows).encode("utf-8")


@pytest.fixture(autouse=True)
def small_minimum(monkeypatch):
    monkeypatch.setattr(fetch_wfp, "MIN_PRICE_ROWS", 5)


def test_valid_file_returns_summary():
    summary = validate_prices(make_csv(10))
    assert summary["rows"] == 10
    assert summary["last_date"] == "2026-09-15"
    assert summary["markets"] == 1


def test_hxl_tag_row_is_skipped():
    data = HEADER + "#date,#adm1,#adm2,#loc,,,,,#item,,,,,,#value,\n" + ROW.format(price="200") * 6
    assert validate_prices(data.encode("utf-8"))["rows"] == 6


def test_missing_column_is_rejected():
    bad = make_csv(10).replace(b"usdprice", b"usd")
    with pytest.raises(ValidationError, match="Missing columns"):
        validate_prices(bad)


def test_too_few_rows_is_rejected():
    with pytest.raises(ValidationError, match="Only 2 rows"):
        validate_prices(make_csv(2))


def test_non_numeric_price_is_rejected():
    with pytest.raises(ValidationError, match="not a number"):
        validate_prices(make_csv(10, price="n/a"))


def test_bot_check_challenge_raises_blocked(monkeypatch):
    class Challenge:
        status = 202
        headers = {"x-amzn-waf-action": "challenge"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b""

    monkeypatch.setattr(fetch_wfp.urllib.request, "urlopen", lambda *a, **k: Challenge())
    with pytest.raises(fetch_wfp.BlockedError):
        fetch_wfp.http_get("https://example.org/file.csv")


def test_first_run_is_always_new():
    assert is_new_version({"fetches": []}, "2026-11-04T01:14:34")


def test_same_version_is_skipped():
    manifest = {"fetches": [{"hdx_last_modified": "2026-11-04T01:14:34"}]}
    assert not is_new_version(manifest, "2026-11-04T01:14:34")
    assert is_new_version(manifest, "2026-12-03T00:00:00")
