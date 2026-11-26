"""PoliteClient — the only way source plugins may make HTTP requests (Section 8.2).

- Honest User-Agent from config; no cookies or credentials, ever (logged-out only).
- robots.txt checked before every path (cached 24 h). Disallowed -> RobotsDisallowed.
- Per-domain minimum delay (default 5 s, never below 2 s; robots Crawl-delay honoured if longer)
  plus 0–2 s random jitter, and at most one in-flight request per domain.
- On-disk cache: pages aren't refetched within `cache_ttl_hours` (default 72).
- Retries: max 2, exponential backoff, only on 5xx / timeouts / connection errors.
- 403, 429 or a CAPTCHA / bot-challenge page -> SourceBlocked. The caller must stop the source's
  run. There is no proxy rotation, header spoofing or headless-browser evasion, by design.
"""

import http.cookiejar
import logging
import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from ingest.cache import SqliteCache, hash_key
from ingest.robots import RobotsChecker

log = logging.getLogger(__name__)

MIN_DELAY_S = 2.0
DEFAULT_DELAY_S = 5.0
MAX_JITTER_S = 2.0
MAX_RETRIES = 2

# Lower-cased substrings that indicate a bot challenge / CAPTCHA rather than real content.
CHALLENGE_MARKERS = (
    "cf-browser-verification",
    "challenge-platform",
    "cf_chl_",
    "attention required! | cloudflare",
    "<title>just a moment...</title>",
    "g-recaptcha",
    "h-captcha",
    "hcaptcha.com",
    "recaptcha/api.js",
    "captcha-delivery.com",
    "px-captcha",
    "are you a robot",
)


class SourceBlocked(Exception):
    """The site refused us (403/429) or served a challenge page. Stop the run; don't retry."""


class DownloadError(Exception):
    pass


class RobotsDisallowed(Exception):
    """robots.txt disallows this URL for our User-Agent. Skip it."""


@dataclass
class FetchResult:
    url: str
    status: int
    text: str
    from_cache: bool = False


def looks_like_challenge(body: str) -> bool:
    low = body[:20000].lower()
    return any(m in low for m in CHALLENGE_MARKERS)


class _NoCookies(http.cookiejar.DefaultCookiePolicy):
    def set_ok(self, cookie, request):  # never store cookies
        return False

    def return_ok(self, cookie, request):  # never send cookies
        return False


class PoliteClient:
    def __init__(
        self,
        user_agent: str,
        cache_dir: str | Path,
        *,
        default_delay: float = DEFAULT_DELAY_S,
        cache_ttl_hours: float = 72,
        timeout: float = 30,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        jitter: Callable[[], float] | None = None,
    ):
        if not user_agent:
            raise ValueError("A descriptive User-Agent is required")
        self.user_agent = user_agent
        self.default_delay = max(MIN_DELAY_S, default_delay)
        self.cache_ttl_s = cache_ttl_hours * 3600
        self._sleep = sleep or time.sleep
        self._clock = clock
        self._jitter = jitter or (lambda: random.uniform(0, MAX_JITTER_S))
        self._delays: dict[str, float] = {}
        self._last_request: dict[str, float] = {}
        self._domain_locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        self.cache = SqliteCache(Path(cache_dir) / "http_cache.sqlite")
        jar = http.cookiejar.CookieJar(policy=_NoCookies())
        self._http = httpx.Client(
            headers={"User-Agent": user_agent, "Accept-Language": "en"},
            cookies=jar,
            timeout=timeout,
            follow_redirects=True,
            transport=transport,
        )
        self.robots = RobotsChecker(user_agent, self._fetch_robots, self.cache)
        self.requests_made = 0

    # -- configuration -------------------------------------------------------------------------
    def set_delay(self, domain: str, seconds: float) -> None:
        """Per-source delay for a domain. Never below 2 s."""
        self._delays[domain] = max(MIN_DELAY_S, seconds)

    def delay_for(self, domain: str) -> float:
        return self._delays.get(domain, self.default_delay)

    # -- internals -----------------------------------------------------------------------------
    def _lock_for(self, domain: str) -> threading.Lock:
        with self._locks_guard:
            return self._domain_locks.setdefault(domain, threading.Lock())

    def _wait_turn(self, domain: str, extra_delay: float | None = None) -> None:
        last = self._last_request.get(domain)
        if last is None:
            return
        delay = max(self.delay_for(domain), extra_delay or 0) + self._jitter()
        remaining = delay - (self._clock() - last)
        if remaining > 0:
            self._sleep(remaining)

    def _send(self, url: str, crawl_delay: float | None = None, stream_to: Path | None = None):
        domain = urlsplit(url).netloc
        with self._lock_for(domain):  # max 1 concurrent request per domain
            attempt = 0
            while True:
                self._wait_turn(domain, crawl_delay)
                try:
                    self.requests_made += 1
                    if stream_to is None:
                        resp = self._http.get(url)
                        self._last_request[domain] = self._clock()
                        body = resp.text
                    else:
                        with self._http.stream("GET", url) as resp:
                            self._last_request[domain] = self._clock()
                            if resp.status_code == 200:
                                tmp = stream_to.with_suffix(stream_to.suffix + ".part")
                                with open(tmp, "wb") as fh:
                                    for chunk in resp.iter_bytes(1 << 16):
                                        fh.write(chunk)
                                tmp.replace(stream_to)
                                body = ""
                            else:
                                body = resp.read().decode(errors="replace")
                except (httpx.TimeoutException, httpx.TransportError) as e:
                    self._last_request[domain] = self._clock()
                    if attempt >= MAX_RETRIES:
                        raise
                    attempt += 1
                    log.info("retry %s after %s", url, type(e).__name__)
                    self._sleep(2**attempt)
                    continue
                status = resp.status_code
                if status in (403, 429) or looks_like_challenge(body):
                    if urlsplit(url).path != "/robots.txt":  # robots 4xx = "no rules" (RFC 9309)
                        log.error("BLOCKED %s (HTTP %s)", url, status)
                    raise SourceBlocked(f"{domain} refused the request (HTTP {status})")
                if 500 <= status < 600 and attempt < MAX_RETRIES:
                    attempt += 1
                    self._sleep(2**attempt)
                    continue
                return status, body

    def _fetch_robots(self, robots_url: str) -> tuple[int, str]:
        try:
            return self._send(robots_url)
        except SourceBlocked:
            return 403, ""
        except (httpx.TimeoutException, httpx.TransportError):
            return 0, ""

    def _check_robots(self, url: str) -> float | None:
        if not self.robots.allowed(url):
            log.warning("robots.txt disallows %s — skipping", url)
            raise RobotsDisallowed(url)
        return self.robots.crawl_delay(url)

    # -- public API ----------------------------------------------------------------------------
    def get(self, url: str, *, use_cache: bool = True) -> FetchResult:
        key = hash_key(url)
        if use_cache:
            hit = self.cache.get("http", key, max_age_s=self.cache_ttl_s)
            if hit is not None:
                return FetchResult(url, hit["status"], hit["text"], from_cache=True)
        crawl_delay = self._check_robots(url)
        status, body = self._send(url, crawl_delay)
        if status == 200:
            self.cache.set("http", key, {"status": status, "text": body})
        return FetchResult(url, status, body)

    def download(self, url: str, dest: str | Path, *, max_age_hours: float | None = None) -> Path:
        """Stream a (possibly large) file to `dest`. Re-uses an existing file younger than
        `max_age_hours` (defaults to the client's cache TTL)."""
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        ttl = self.cache_ttl_s if max_age_hours is None else max_age_hours * 3600
        if dest.exists() and time.time() - dest.stat().st_mtime < ttl:
            log.info("using cached download %s", dest)
            return dest
        crawl_delay = self._check_robots(url)
        status, _ = self._send(url, crawl_delay, stream_to=dest)
        if status != 200:
            raise DownloadError(f"download of {url} failed: HTTP {status}")
        return dest

    def close(self) -> None:
        self._http.close()
        self.cache.close()
