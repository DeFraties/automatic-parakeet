import pytest

from ingest.http import (
    MIN_DELAY_S,
    PoliteClient,
    RobotsDisallowed,
    SourceBlocked,
    looks_like_challenge,
)

UA = "BallparkBot/1.0 (+https://ballpark.example.com/about; contact: test@example.com)"


class FakeTime:
    def __init__(self):
        self.now = 1000.0
        self.sleeps: list[float] = []

    def clock(self):
        return self.now

    def sleep(self, s):
        self.sleeps.append(s)
        self.now += s


@pytest.fixture
def ft():
    return FakeTime()


def make(tmp_path, ft, **kw):
    kw.setdefault("jitter", lambda: 0.0)
    return PoliteClient(UA, tmp_path, sleep=ft.sleep, clock=ft.clock, **kw)


def test_sends_honest_user_agent(server, tmp_path, ft):
    server.routes["/robots.txt"] = (200, "User-agent: *\nAllow: /\n", {})
    server.routes["/a"] = (200, "hello", {})
    c = make(tmp_path, ft)
    assert c.get(f"{server.url}/a").text == "hello"
    assert all(h.get("User-Agent") == UA for _, h in server.hits)


def test_obeys_robots_txt(server, tmp_path, ft):
    server.routes["/robots.txt"] = (200, "User-agent: *\nDisallow: /private/\n", {})
    server.routes["/public"] = (200, "ok", {})
    server.routes["/private/x"] = (200, "secret", {})
    c = make(tmp_path, ft)
    assert c.get(f"{server.url}/public").status == 200
    with pytest.raises(RobotsDisallowed):
        c.get(f"{server.url}/private/x")
    assert "/private/x" not in server.paths()
    assert server.paths().count("/robots.txt") == 1  # cached


def test_robots_rules_for_our_user_agent(server, tmp_path, ft):
    server.routes["/robots.txt"] = (200, "User-agent: BallparkBot\nDisallow: /\n", {})
    with pytest.raises(RobotsDisallowed):
        make(tmp_path, ft).get(f"{server.url}/anything")


def test_missing_robots_allows_all(server, tmp_path, ft):
    server.routes["/page"] = (200, "ok", {})
    assert make(tmp_path, ft).get(f"{server.url}/page").status == 200  # robots.txt -> 404


def test_robots_server_error_disallows_all(server, tmp_path, ft):
    server.routes["/robots.txt"] = (500, "oops", {})
    server.routes["/page"] = (200, "ok", {})
    with pytest.raises(RobotsDisallowed):
        make(tmp_path, ft).get(f"{server.url}/page")


def test_robots_cached_across_clients(server, tmp_path, ft):
    server.routes["/robots.txt"] = (200, "User-agent: *\nAllow: /\n", {})
    server.routes["/p"] = (200, "ok", {})
    make(tmp_path, ft).get(f"{server.url}/p")
    make(tmp_path, ft).get(f"{server.url}/p", use_cache=False)
    assert server.paths().count("/robots.txt") == 1


def test_enforces_per_domain_delay(server, tmp_path, ft):
    for p in ("/1", "/2", "/3"):
        server.routes[p] = (200, "ok", {})
    c = make(tmp_path, ft, default_delay=5)
    c.get(f"{server.url}/1")
    c.get(f"{server.url}/2")
    c.get(f"{server.url}/3")
    # robots.txt, /1, /2, /3 -> every request after the first waits the full 5 s
    assert ft.sleeps == [5.0, 5.0, 5.0]


def test_jitter_is_added(server, tmp_path, ft):
    server.routes["/1"] = (200, "ok", {})
    c = make(tmp_path, ft, default_delay=3, jitter=lambda: 1.5)
    c.get(f"{server.url}/1")
    assert ft.sleeps == [4.5]


def test_delay_never_below_two_seconds(tmp_path, ft):
    c = make(tmp_path, ft, default_delay=0.1)
    assert c.default_delay == MIN_DELAY_S == 2
    c.set_delay("example.com", 0.5)
    assert c.delay_for("example.com") == 2


def test_robots_crawl_delay_respected(server, tmp_path, ft):
    server.routes["/robots.txt"] = (200, "User-agent: *\nCrawl-delay: 10\n", {})
    server.routes["/a"] = (200, "ok", {})
    server.routes["/b"] = (200, "ok", {})
    c = make(tmp_path, ft, default_delay=2)
    c.get(f"{server.url}/a")
    c.get(f"{server.url}/b")
    assert ft.sleeps[-1] == 10


@pytest.mark.parametrize("status", [403, 429])
def test_stops_on_403_429(server, tmp_path, ft, status):
    server.routes["/x"] = (status, "go away", {})
    with pytest.raises(SourceBlocked):
        make(tmp_path, ft).get(f"{server.url}/x")
    assert server.paths().count("/x") == 1  # no retries


@pytest.mark.parametrize(
    "body,status",
    [
        ("<html><title>Just a moment...</title><div id='cf-browser-verification'></div>", 503),
        ("<html><script src='/cdn-cgi/challenge-platform/h/b/orchestrate'></script>", 200),
        ("<form><div class='g-recaptcha' data-sitekey='x'></div></form>", 200),
    ],
)
def test_stops_on_challenge_pages(server, tmp_path, ft, body, status):
    server.routes["/x"] = (status, body, {})
    with pytest.raises(SourceBlocked):
        make(tmp_path, ft).get(f"{server.url}/x")
    assert server.paths().count("/x") == 1


def test_retries_5xx_then_succeeds(server, tmp_path, ft):
    server.sequences["/flaky"] = [(502, "bad gateway"), (503, "unavailable")]
    server.routes["/flaky"] = (200, "finally", {})
    assert make(tmp_path, ft).get(f"{server.url}/flaky").text == "finally"
    assert server.paths().count("/flaky") == 3


def test_gives_up_after_two_retries(server, tmp_path, ft):
    server.routes["/down"] = (500, "error", {})
    assert make(tmp_path, ft).get(f"{server.url}/down").status == 500
    assert server.paths().count("/down") == 3


def test_never_sends_cookies(server, tmp_path, ft):
    server.routes["/set"] = (200, "ok", {"Set-Cookie": "session=abc123; Path=/"})
    server.routes["/next"] = (200, "ok", {})
    c = make(tmp_path, ft)
    c.get(f"{server.url}/set")
    c.get(f"{server.url}/next")
    assert all("Cookie" not in h and "cookie" not in h for _, h in server.hits)


def test_cache_avoids_refetch(server, tmp_path, ft):
    server.routes["/page"] = (200, "cached body", {})
    c = make(tmp_path, ft)
    c.get(f"{server.url}/page")
    r = make(tmp_path, ft).get(f"{server.url}/page")
    assert r.from_cache and r.text == "cached body"
    assert server.paths().count("/page") == 1


def test_errors_are_not_cached(server, tmp_path, ft):
    server.routes["/missing"] = (404, "nope", {})
    c = make(tmp_path, ft)
    c.get(f"{server.url}/missing")
    c.get(f"{server.url}/missing")
    assert server.paths().count("/missing") == 2


def test_download(server, tmp_path, ft):
    server.routes["/data.csv"] = (200, "a,b\n1,2\n", {"Content-Type": "text/csv"})
    c = make(tmp_path, ft)
    dest = c.download(f"{server.url}/data.csv", tmp_path / "d" / "data.csv")
    assert dest.read_text() == "a,b\n1,2\n"
    c.download(f"{server.url}/data.csv", dest)  # fresh file is reused
    assert server.paths().count("/data.csv") == 1


def test_challenge_detection_is_specific():
    assert not looks_like_challenge("<html><body>Nice flat for sale</body></html>")
    assert looks_like_challenge("<title>Attention Required! | Cloudflare</title>")


def test_requires_user_agent(tmp_path):
    with pytest.raises(ValueError):
        PoliteClient("", tmp_path)


def test_robots_403_is_not_logged_as_blocked(server, tmp_path, ft, caplog):
    server.routes["/robots.txt"] = (403, "AccessDenied", {})
    server.routes["/file.csv"] = (200, "a,b", {})
    assert make(tmp_path, ft).get(f"{server.url}/file.csv").text == "a,b"
    assert "BLOCKED" not in caplog.text
