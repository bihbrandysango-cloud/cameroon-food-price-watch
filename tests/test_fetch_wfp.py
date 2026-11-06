"""Tests for the fetch step. They use small fake rows, so no internet is needed."""

from datetime import date

import pytest

from src.ingest import fetch_wfp
from src.ingest.fetch_wfp import ValidationError, clean, merge, months_back


def api_row(month: str = "2026-09", market: str = "1", price: float = 200.0) -> dict:
    return {
        "location_code": "CMR", "reference_period_start": f"{month}-15T00:00:00",
        "reference_period_end": f"{month}-28T23:59:59", "admin1_code": "CM004",
        "admin1_name": "Far North", "admin2_code": "CM004001", "admin2_name": "Diamare",
        "market_code": market, "market_name": "Maroua", "lat": 10.6, "lon": 14.3,
        "commodity_category": "cereals and tubers", "commodity_code": "67",
        "commodity_name": "Maize (white)", "unit": "KG", "price_flag": "actual",
        "price_type": "Retail", "currency_code": "XAF", "price": price,
    }


def test_clean_trims_dates_and_keeps_columns():
    row = clean([api_row()])[0]
    assert row["reference_period_start"] == "2026-09-15"
    assert row["price"] == "200.0"
    assert "location_code" not in row


def test_missing_column_is_rejected():
    bad = api_row()
    del bad["price_type"]
    with pytest.raises(ValidationError, match="missing"):
        clean([bad])


@pytest.mark.parametrize("price", ["n/a", None, 0, -5])
def test_bad_price_is_rejected(price):
    with pytest.raises(ValidationError):
        clean([api_row(price=price)])


def test_merge_adds_new_rows_and_replaces_corrected_ones():
    old = clean([api_row("2026-08", price=210), api_row("2026-09", price=200)])
    fresh = clean([api_row("2026-09", price=190), api_row("2026-10", price=185)])
    merged = merge(old, fresh)
    prices = {r["reference_period_start"]: r["price"] for r in merged}
    assert prices == {"2026-08-15": "210.0", "2026-09-15": "190.0", "2026-10-15": "185.0"}


def test_months_back_crosses_year_boundary():
    assert months_back(date(2026, 3, 20), 6) == "2025-09-01"
    assert months_back(date(2026, 11, 5), 6) == "2026-05-01"


def test_fetch_saves_then_skips_when_nothing_changed(tmp_path, monkeypatch):
    calls = []

    def fake_download(app_identifier, start_date=None):
        calls.append(start_date)
        return [api_row("2026-08"), api_row("2026-09")]

    monkeypatch.setattr(fetch_wfp, "download", fake_download)
    today = date(2026, 11, 5)

    assert fetch_wfp.fetch("id", raw_dir=tmp_path, today=today) is True
    assert fetch_wfp.fetch("id", raw_dir=tmp_path, today=today) is False
    # First run takes the full history, the second only the last six months
    assert calls == [None, "2026-05-01"]
    assert (tmp_path / "wfp_food_prices_cmr.csv").exists()


def test_full_run_then_refresh_with_same_data_saves_nothing(tmp_path, monkeypatch):
    # HAPI returns rows unsorted; a refresh must not count a new order as a change
    monkeypatch.setattr(fetch_wfp, "download",
                        lambda app_identifier, start_date=None: [api_row("2026-09"), api_row("2026-08")])
    assert fetch_wfp.fetch("id", full=True, raw_dir=tmp_path) is True
    assert fetch_wfp.fetch("id", raw_dir=tmp_path, today=date(2026, 11, 5)) is False


def test_missing_app_identifier_stops_with_message(monkeypatch):
    monkeypatch.delenv("HAPI_APP_IDENTIFIER", raising=False)
    assert fetch_wfp.main([]) == 2
