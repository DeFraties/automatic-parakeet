"""FX rates for ingestion (Section 6.5).

- ECB reference rates via the Frankfurter API, cached in the `fx_rates` table.
- Lookup uses the rate for `price_date`, or the nearest earlier business day.
- Currencies the ECB doesn't publish (TWD) go through a pluggable FallbackFxProvider; the default
  reads monthly averages from `data/fx_manual.csv` (month,currency,rate_to_usd).
- Rates are stored as USD per 1 unit of currency (price_usd = price_local * rate_to_usd).
"""

import csv
import logging
from abc import ABC, abstractmethod
from datetime import date, timedelta
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.countries import ecb_currencies, fallback_currencies
from app.models import FxRate

log = logging.getLogger(__name__)

LOOKBACK_DAYS = 10  # weekends + holidays


class FallbackFxProvider(ABC):
    @abstractmethod
    def rate_to_usd(self, currency: str, on: date) -> float | None: ...

    def monthly_rates(self) -> list[tuple[date, str, float]]:
        """(first-of-month, currency, rate) rows to mirror into fx_rates, if any."""
        return []


class ManualCsvFxProvider(FallbackFxProvider):
    """Monthly average rates maintained by the owner: `month,currency,rate_to_usd`
    e.g. `2025-03,TWD,0.0303`."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._rates: dict[tuple[str, str], float] | None = None

    def _load(self) -> dict[tuple[str, str], float]:
        if self._rates is None:
            self._rates = {}
            if self.path.exists():
                with open(self.path, newline="", encoding="utf-8") as fh:
                    for row in csv.DictReader(fh):
                        try:
                            key = (row["month"].strip()[:7], row["currency"].strip().upper())
                            self._rates[key] = float(row["rate_to_usd"])
                        except (KeyError, ValueError):
                            log.warning("bad row in %s: %r", self.path, row)
            else:
                log.warning("manual FX file %s not found", self.path)
        return self._rates

    def rate_to_usd(self, currency: str, on: date) -> float | None:
        return self._load().get((on.strftime("%Y-%m"), currency))

    def monthly_rates(self) -> list[tuple[date, str, float]]:
        out = []
        for (month, cur), rate in self._load().items():
            y, m = month.split("-")
            out.append((date(int(y), int(m), 1), cur, rate))
        return out


class FxService:
    def __init__(
        self,
        db: Session,
        *,
        api_url: str,
        user_agent: str,
        fallback: FallbackFxProvider,
        transport: httpx.BaseTransport | None = None,
    ):
        self.db = db
        self.api_url = api_url.rstrip("/")
        self.fallback = fallback
        self.fallback_set = set(fallback_currencies())
        self._http = httpx.Client(
            headers={"User-Agent": user_agent},
            timeout=30,
            transport=transport,
            follow_redirects=True,
        )
        self._fetched_years: set[int] = set()

    def close(self) -> None:
        self._http.close()

    # -- fetching ------------------------------------------------------------------------------
    def fetch_range(self, start: date, end: date) -> int:
        """Fetch ECB rates for all launch currencies between start and end; store them."""
        url = f"{self.api_url}/{start.isoformat()}..{end.isoformat()}"
        resp = self._http.get(url, params={"from": "USD", "to": ",".join(ecb_currencies())})
        resp.raise_for_status()
        n = 0
        for day, rates in resp.json().get("rates", {}).items():
            d = date.fromisoformat(day)
            for cur, per_usd in rates.items():
                if per_usd:
                    self.db.merge(FxRate(date=d, currency=cur, rate_to_usd=1 / per_usd))
                    n += 1
        self.db.commit()
        return n

    def mirror_fallback(self) -> int:
        """Copy fallback (manual) monthly rates into fx_rates so play-time lookups see them."""
        rows = self.fallback.monthly_rates()
        for d, cur, rate in rows:
            self.db.merge(FxRate(date=d, currency=cur, rate_to_usd=rate))
        self.db.commit()
        return len(rows)

    def update(self, days: int = 30) -> int:
        end = date.today()
        n = self.fetch_range(end - timedelta(days=days), end)
        return n + self.mirror_fallback()

    # -- lookup --------------------------------------------------------------------------------
    def _stored(self, currency: str, on: date) -> float | None:
        return self.db.execute(
            select(FxRate.rate_to_usd)
            .where(
                FxRate.currency == currency,
                FxRate.date <= on,
                FxRate.date >= on - timedelta(days=LOOKBACK_DAYS),
            )
            .order_by(FxRate.date.desc())
            .limit(1)
        ).scalar_one_or_none()

    def rate_to_usd(self, currency: str, on: date) -> float | None:
        """USD per 1 unit of `currency` on `on` (nearest earlier business day). None = unknown."""
        if currency == "USD":
            return 1.0
        if currency in self.fallback_set:
            return self.fallback.rate_to_usd(currency, on)
        rate = self._stored(currency, on)
        if rate is None and on.year not in self._fetched_years:
            self._fetched_years.add(on.year)
            start = date(on.year, 1, 1) - timedelta(days=LOOKBACK_DAYS)
            end = min(date(on.year, 12, 31), date.today())
            try:
                self.fetch_range(start, end)
            except httpx.HTTPError as e:
                log.error("FX fetch failed for %s: %s", on.year, e)
            rate = self._stored(currency, on)
        return rate
