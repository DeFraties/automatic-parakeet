"""Simple nickname filter (Section 4.4): blocks the obvious; not a moderation system."""

import re
import unicodedata

NICKNAME_RE = re.compile(r"^[\w .\-]{3,16}$", re.UNICODE)

# Substrings checked after normalisation (lower-case, leetspeak undone, non-letters removed).
_BLOCKED = (
    "fuck", "shit", "cunt", "bitch", "bastard", "dick", "cock", "pussy", "asshole", "arsehole",
    "wank", "twat", "slut", "whore", "nigg", "fag", "retard", "rape", "nazi", "hitler", "porn",
    "penis", "vagina", "boob", "tits", "spic", "chink", "kike", "dyke", "tranny", "paki",
    "puta", "merda", "cazzo", "scheisse", "kurwa", "pierdol", "chuj", "putain", "connard",
    "salope", "joder", "coño", "pendejo", "kanker",
)  # fmt: skip
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a",
                       "$": "s", "!": "i", "|": "i", "+": "t"})  # fmt: skip


def _normalise(text: str) -> str:
    t = unicodedata.normalize("NFKD", text.lower()).translate(_LEET)
    return "".join(ch for ch in t if ch.isalpha() or ch == "ñ")


def nickname_problem(nickname: str) -> str | None:
    """None if acceptable, else a short reason."""
    nick = nickname.strip()
    if not 3 <= len(nick) <= 16:
        return "Nicknames must be 3–16 characters."
    if not NICKNAME_RE.match(nick):
        return "Use letters, numbers, spaces, dots, dashes or underscores."
    flat = _normalise(nick)
    if any(word in flat for word in _BLOCKED):
        return "Please choose a different nickname."
    return None
