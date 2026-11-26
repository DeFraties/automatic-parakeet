"""robots.txt checking with a 24 h cache (Section 8.2)."""

import logging
import urllib.robotparser
from collections.abc import Callable
from urllib.parse import urlsplit

from ingest.cache import SqliteCache

log = logging.getLogger(__name__)

ROBOTS_TTL_S = 24 * 3600


class RobotsChecker:
    """`fetch(url) -> (status_code, text)` is supplied by the PoliteClient so robots.txt requests
    get the same User-Agent, delays and blocking rules as everything else."""

    def __init__(
        self, user_agent: str, fetch: Callable[[str], tuple[int, str]], cache: SqliteCache
    ):
        self.user_agent = user_agent
        self._fetch = fetch
        self._cache = cache
        self._parsers: dict[str, urllib.robotparser.RobotFileParser] = {}

    def _parser_for(self, origin: str) -> urllib.robotparser.RobotFileParser:
        if origin in self._parsers:
            return self._parsers[origin]
        cached = self._cache.get("robots", origin, max_age_s=ROBOTS_TTL_S)
        if cached is None:
            status, text = self._fetch(f"{origin}/robots.txt")
            cached = {"status": status, "text": text}
            self._cache.set("robots", origin, cached)
        rp = urllib.robotparser.RobotFileParser()
        status = cached["status"]
        # RFC 9309: 4xx = "unavailable" (no rules -> allowed); 5xx / unreachable = "unreachable"
        # (assume complete disallow until it can be read).
        if status >= 500 or status == 0:
            rp.disallow_all = True
            log.warning("robots.txt for %s returned %s: treating as disallow-all", origin, status)
        elif status >= 400:
            rp.allow_all = True
        else:
            rp.parse(cached["text"].splitlines())
        self._parsers[origin] = rp
        return rp

    def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        return self._parser_for(origin).can_fetch(self.user_agent, url)

    def crawl_delay(self, url: str) -> float | None:
        parts = urlsplit(url)
        delay = self._parser_for(f"{parts.scheme}://{parts.netloc}").crawl_delay(self.user_agent)
        return float(delay) if delay is not None else None
