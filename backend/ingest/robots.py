"""robots.txt checking with a 24 h cache (Section 8.2), following RFC 9309 and Google's
documented matching rules (Python's urllib.robotparser ignores `*` and `$`, which real listing
sites use heavily):

- Group selection: the group(s) whose user-agent token matches our product token
  ("BallparkBot") most specifically; otherwise the `*` group(s); otherwise everything allowed.
- Rule matching: `*` matches any sequence, a trailing `$` anchors the end of the path. The
  longest matching rule wins; on a tie `Allow` wins. No matching rule = allowed.
- Status codes: 4xx = no rules (allowed); 5xx / unreachable = disallow everything.
"""

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import quote, unquote, urlsplit

from ingest.cache import SqliteCache

log = logging.getLogger(__name__)

ROBOTS_TTL_S = 24 * 3600


@dataclass
class Rule:
    allow: bool
    pattern: str
    regex: re.Pattern = field(repr=False)


@dataclass
class Group:
    agents: list[str]
    rules: list[Rule] = field(default_factory=list)
    crawl_delay: float | None = None


def _normalise(path: str) -> str:
    """Percent-encoding normalised so '/caf%C3%A9' and '/café' compare equal."""
    return quote(unquote(path), safe="/?=&*$%:@!+,;~-._")


def _compile(pattern: str) -> re.Pattern:
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    rx = "".join(".*" if ch == "*" else re.escape(ch) for ch in _normalise(body))
    return re.compile(rx + ("$" if anchored else ""))


def parse(text: str) -> list[Group]:
    groups: list[Group] = []
    current: Group | None = None
    last_was_agent = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = (part.strip() for part in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            if current is None or not last_was_agent:
                current = Group(agents=[])
                groups.append(current)
            current.agents.append(value.lower())
            last_was_agent = True
            continue
        last_was_agent = False
        if current is None:
            continue
        if key in ("allow", "disallow"):
            if value:  # an empty Disallow means "allow everything"
                current.rules.append(Rule(key == "allow", value, _compile(value)))
        elif key == "crawl-delay":
            try:
                current.crawl_delay = float(value)
            except ValueError:
                pass
    return groups


def product_token(user_agent: str) -> str:
    """'BallparkBot/1.0 (+https://…)' -> 'ballparkbot'."""
    return re.split(r"[/\s]", user_agent.strip(), maxsplit=1)[0].lower()


def groups_for(groups: list[Group], user_agent: str) -> list[Group]:
    token = product_token(user_agent)
    named = [g for g in groups if any(a != "*" and a in token for a in g.agents)]
    if named:
        best = max(len(a) for g in named for a in g.agents if a != "*" and a in token)
        return [g for g in named if any(len(a) == best and a in token for a in g.agents)]
    return [g for g in groups if "*" in g.agents]


def decide(groups: list[Group], user_agent: str, path: str) -> tuple[bool, Rule | None]:
    """(allowed, deciding rule) for a path (including any query string)."""
    target = _normalise(path or "/")
    best: Rule | None = None
    for g in groups_for(groups, user_agent):
        for r in g.rules:
            if r.regex.match(target) and (
                best is None
                or len(r.pattern) > len(best.pattern)
                or (len(r.pattern) == len(best.pattern) and r.allow and not best.allow)
            ):
                best = r
    return (best is None or best.allow), best


@dataclass
class _Policy:
    status: int
    groups: list[Group]


class RobotsChecker:
    """`fetch(url) -> (status_code, text)` is supplied by the PoliteClient so robots.txt requests
    get the same User-Agent, delays and blocking rules as everything else."""

    def __init__(
        self, user_agent: str, fetch: Callable[[str], tuple[int, str]], cache: SqliteCache
    ):
        self.user_agent = user_agent
        self._fetch = fetch
        self._cache = cache
        self._policies: dict[str, _Policy] = {}

    def _policy_for(self, origin: str) -> _Policy:
        if origin in self._policies:
            return self._policies[origin]
        cached = self._cache.get("robots", origin, max_age_s=ROBOTS_TTL_S)
        if cached is None:
            status, text = self._fetch(f"{origin}/robots.txt")
            cached = {"status": status, "text": text}
            self._cache.set("robots", origin, cached)
        status = cached["status"]
        if status >= 500 or status == 0:
            log.warning("robots.txt for %s returned %s: treating as disallow-all", origin, status)
        policy = _Policy(status, parse(cached["text"]) if 200 <= status < 300 else [])
        self._policies[origin] = policy
        return policy

    @staticmethod
    def _split(url: str) -> tuple[str, str]:
        parts = urlsplit(url)
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        return f"{parts.scheme}://{parts.netloc}", path

    def explain(self, url: str) -> tuple[bool, str]:
        """(allowed, human-readable reason) — used by `ingest robots-check`."""
        origin, path = self._split(url)
        policy = self._policy_for(origin)
        if policy.status >= 500 or policy.status == 0:
            return False, f"robots.txt unreachable (HTTP {policy.status}): disallow all"
        if policy.status >= 400:
            return True, f"no robots.txt (HTTP {policy.status}): allowed"
        allowed, rule = decide(policy.groups, self.user_agent, path)
        if rule is None:
            return True, "no matching rule: allowed"
        return allowed, f"{'Allow' if rule.allow else 'Disallow'}: {rule.pattern}"

    def allowed(self, url: str) -> bool:
        return self.explain(url)[0]

    def crawl_delay(self, url: str) -> float | None:
        origin, _ = self._split(url)
        policy = self._policy_for(origin)
        delays = [g.crawl_delay for g in groups_for(policy.groups, self.user_agent)
                  if g.crawl_delay is not None]  # fmt: skip
        return max(delays) if delays else None
