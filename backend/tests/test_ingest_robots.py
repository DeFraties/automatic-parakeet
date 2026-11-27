import pytest

from ingest.robots import decide, parse, product_token

UA = "BallparkBot/1.0 (+https://ballpark.example.com/about; contact: x@example.com)"

ROBOTS = """
# comment
User-agent: *
Allow: /homes/for_sale/$
Allow: /homes/*_rb/$
Disallow: /homes/
Disallow: /*/amp$
Disallow: *?sc=*
Disallow: /stingray/
Allow: /stingray/*/*/newest_listings.rss
Disallow: /private
Allow: /private/ok
Crawl-delay: 7

User-agent: Googlebot
Disallow: /

User-agent: ballparkbot-images
Disallow: /img/
"""


@pytest.mark.parametrize(
    "path,allowed",
    [
        ("/homes/for_sale/", True),  # Allow ...$ is longer than Disallow /homes/
        ("/homes/for_sale/Seattle-WA/", False),  # $ anchors: only the exact path is allowed
        ("/homes/Seattle-WA_rb/", True),  # wildcard allow
        ("/homes/Seattle-WA/", False),
        ("/news/story/amp", False),  # /*/amp$
        ("/news/story/amp/more", True),
        ("/search?sc=1", False),  # *?sc=*
        ("/search?q=1&x=sc", True),
        ("/stingray/do/x", False),
        ("/stingray/WA/Seattle/newest_listings.rss", True),  # longer allow beats disallow
        ("/private/ok", True),
        ("/private/other", False),
        ("/WA/Seattle/1-Main-St-98101/home/123", True),  # no rule matches
        ("/caf%C3%A9", True),
    ],
)
def test_star_group_wildcards_and_longest_match(path, allowed):
    assert decide(parse(ROBOTS), UA, path)[0] is allowed


def test_named_group_beats_star_and_most_specific_wins():
    groups = parse(ROBOTS)
    # "ballparkbot-images" is NOT our product token (ballparkbot), so * applies to us
    assert decide(groups, UA, "/img/1.jpg")[0] is True
    assert decide(groups, "Googlebot/2.1", "/anything")[0] is False
    named = parse("User-agent: *\nDisallow: /\n\nUser-agent: BallparkBot\nAllow: /\n")
    assert decide(named, UA, "/x")[0] is True


def test_tie_goes_to_allow_and_empty_disallow():
    assert decide(parse("User-agent: *\nDisallow: /a\nAllow: /a\n"), UA, "/a")[0] is True
    assert decide(parse("User-agent: *\nDisallow:\n"), UA, "/anything")[0] is True


def test_consecutive_agent_lines_share_a_group():
    groups = parse("User-agent: foo\nUser-agent: BallparkBot\nDisallow: /x\n")
    assert decide(groups, UA, "/x")[0] is False


def test_product_token():
    assert product_token(UA) == "ballparkbot"
    assert product_token("Mozilla/5.0 (X11)") == "mozilla"


def test_checker_explain_and_crawl_delay(server, tmp_path):
    from ingest.http import PoliteClient

    server.routes["/robots.txt"] = (200, ROBOTS, {})
    c = PoliteClient(UA, tmp_path, sleep=lambda s: None, jitter=lambda: 0)
    ok, why = c.robots.explain(f"{server.url}/homes/Seattle-WA/")
    assert not ok and why == "Disallow: /homes/"
    assert c.robots.explain(f"{server.url}/homes/Seattle-WA_rb/") == (True, "Allow: /homes/*_rb/$")
    assert c.robots.crawl_delay(f"{server.url}/x") == 7
    c.close()


def test_robots_check_cli(cli_env, server, capsys, monkeypatch):  # noqa: F811
    from ingest.cli import main

    monkeypatch.setattr("ingest.http.time.sleep", lambda s: None)

    server.routes["/robots.txt"] = (200, ROBOTS, {})
    assert main(["robots-check", f"{server.url}/homes/for_sale/", f"{server.url}/homes/x/",
                 "--delay", "1"]) == 0  # fmt: skip
    out = capsys.readouterr().out
    assert "ALLOWED" in out and "DISALLOWED" in out and "Disallow: /homes/" in out


from tests.test_ingest_cli import cli_env  # noqa: E402, F401
