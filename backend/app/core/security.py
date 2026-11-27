"""Simple in-memory, per-IP sliding-window rate limiting (Section 6.1).

Good enough for a single-server deployment. With multiple Uvicorn workers each worker keeps its
own window, so the effective limit is `limit x workers` — acceptable for this light-touch use.
"""

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request


class RateLimiter:
    def __init__(self, window_seconds: int = 3600):
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int) -> None:
        if limit <= 0:
            return
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= limit:
                raise HTTPException(
                    status_code=429,
                    detail={"code": "rate_limited", "message": "Too many requests, slow down."},
                )
            q.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()


def client_ip(request: Request) -> str:
    # Caddy sets X-Forwarded-For; take the left-most (original client) address.
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# --- Content Security Policy (Section 7.3 / 11) -----------------------------------------------
def csp_img_hosts(image_hosts: list[str], tile_url: str) -> list[str]:
    from urllib.parse import urlsplit

    hosts = {f"https://{h}" for h in image_hosts if h}
    tile_host = urlsplit(tile_url.replace("{s}", "a")).netloc
    if tile_host:
        hosts.add(f"https://{tile_host}")
    return sorted(hosts)


def build_csp(image_hosts: list[str], tile_url: str) -> str:
    """CSP whose img-src allows only our own site, the enabled sources' image hosts and the map
    tile server, so a photo URL from any other host can't load."""
    img_src = " ".join(["'self'", *csp_img_hosts(image_hosts, tile_url)])
    return (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        f"img-src {img_src}; connect-src 'self'; font-src 'self'; frame-ancestors 'none'; "
        "base-uri 'self'; form-action 'self'"
    )
