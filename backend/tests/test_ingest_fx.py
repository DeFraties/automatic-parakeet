import json
from datetime import date

import httpx
import pytest

from app.models import FxRate
from ingest.fx import FxService, ManualCsvFxProvider


def frankfurter(handler_calls):
    def handler(request: httpx.Request):
        handler_calls.append(str(request.url))
        assert request.url.params["from"] == "USD"
        assert "TWD" not in request.url.params["to"]  # not an ECB currency
        body = {
            "rates": {
                "2024-03-14": {"EUR": 0.9, "GBP": 0.8, "JPY": 150.0},
                "2024-03-15": {"EUR": 0.92, "GBP": 0.78, "JPY": 148.0},
            }
        }
        return httpx.Response(200, text=json.dumps(body))

    return httpx.MockTransport(handler)


@pytest.fixture
def manual_csv(tmp_path):
    p = tmp_path / "fx_manual.csv"
    p.write_text("month,currency,rate_to_usd\n2024-03,TWD,0.0315\n2024-04,TWD,0.0310\n")
    return p


def svc(db, calls, csv_path):
    return FxService(
        db,
        api_url="https://fx.test",
        user_agent="t",
        fallback=ManualCsvFxProvider(csv_path),
        transport=frankfurter(calls),
    )


def test_ecb_rate_fetched_and_cached(db, manual_csv):
    calls = []
    fx = svc(db, calls, manual_csv)
    assert fx.rate_to_usd("GBP", date(2024, 3, 15)) == pytest.approx(1 / 0.78)
    assert fx.rate_to_usd("JPY", date(2024, 3, 14)) == pytest.approx(1 / 150)
    assert len(calls) == 1  # one fetch for the whole year
    assert db.get(FxRate, (date(2024, 3, 15), "EUR")).rate_to_usd == pytest.approx(1 / 0.92)


def test_nearest_earlier_business_day(db, manual_csv):
    fx = svc(db, [], manual_csv)
    # Saturday 16th / Sunday 17th -> Friday 15th
    assert fx.rate_to_usd("EUR", date(2024, 3, 17)) == pytest.approx(1 / 0.92)


def test_usd_is_one(db, manual_csv):
    assert svc(db, [], manual_csv).rate_to_usd("USD", date(2024, 1, 1)) == 1.0


def test_twd_uses_fallback_provider(db, manual_csv):
    calls = []
    fx = svc(db, calls, manual_csv)
    assert fx.rate_to_usd("TWD", date(2024, 3, 20)) == 0.0315
    assert fx.rate_to_usd("TWD", date(2024, 4, 2)) == 0.0310
    assert calls == []  # never asks the ECB for TWD


def test_twd_missing_month_returns_none(db, manual_csv):
    assert svc(db, [], manual_csv).rate_to_usd("TWD", date(2023, 1, 5)) is None


def test_missing_manual_file_is_not_fatal(db, tmp_path):
    fx = svc(db, [], tmp_path / "nope.csv")
    assert fx.rate_to_usd("TWD", date(2024, 3, 1)) is None


def test_mirror_fallback_for_hard_mode_lookups(db, manual_csv):
    fx = svc(db, [], manual_csv)
    assert fx.mirror_fallback() == 2
    assert db.get(FxRate, (date(2024, 4, 1), "TWD")).rate_to_usd == 0.0310


def test_fetch_failure_returns_none(db, manual_csv):
    def boom(request):
        return httpx.Response(500)

    fx = FxService(
        db,
        api_url="https://fx.test",
        user_agent="t",
        fallback=ManualCsvFxProvider(manual_csv),
        transport=httpx.MockTransport(boom),
    )
    assert fx.rate_to_usd("EUR", date(2024, 3, 15)) is None
