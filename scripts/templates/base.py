"""Contract every AlphaSignal email template implements, plus shared helpers.

The core pipeline (cleaner.py / parser.py) knows nothing about any specific
template's markup. It finds the section container, asks the registry which
template the email uses, and then delegates every template-specific decision
to that template object:

    classify(table)          which section a top-level table is (or None = junk)
    scrub(kind, table)       strip sponsor fragments inside a kept section
    parse_intro(table)       -> str
    parse_summary(table, news) -> (summary entries, read_time)
    parse_news_block(table, news_id, resolver) -> dict
    parse_signals(table, resolver) -> list[dict]

The JSON each parse_* returns must keep the shape documented in README.md —
the app parses it, not the template. Adding a template = add a module in this
package and register it in templates/__init__.py; core files stay untouched.
"""

from __future__ import annotations

import re

from bs4 import Tag

from utils import markers
from utils.helpers import LinkResolver

# Section kinds the core understands.
INTRO, SUMMARY, NEWS, SIGNALS, ARTICLE, AUTHOR = (
    "intro", "summary", "news", "signals", "article", "author",
)

# "Hey," (old) or personalised "Hey Vaultscapes," (since 2026-11-23, both layouts)
GREETING_RE = re.compile(r"^Hey\b[^,]{0,40},\s*")

# "2,022 Likes" / "23,314 Stars" / "879 Downloads" (any leading glyph ignored)
STAT_RE = re.compile(r"([\d,]+)\s+(" + "|".join(markers.STAT_TYPES) + r")\b")


def parse_stat(text: str) -> dict | None:
    m = STAT_RE.search(text)
    if m is None:
        return None
    return {"type": m.group(2).lower(), "value": int(m.group(1).replace(",", ""))}


def match_news_id(headline: str, news: list[dict]) -> str | None:
    """Match a summary headline to its full news block (whitespace-tolerant)."""
    norm = re.sub(r"\W+", "", headline).lower()
    for block in news:
        block_norm = re.sub(r"\W+", "", block["headline"]).lower()
        if norm == block_norm or norm in block_norm or block_norm in norm:
            return block["id"]
    return None


class EmailTemplate:
    """Base class. Subclasses override everything that touches markup."""

    #: short identifier, logged and used in tests
    name = "base"

    def matches(self, tables: list[Tag], texts: list[str]) -> bool:
        """True if the email's top-level section tables are in this template.

        `texts` holds each table's whitespace-squashed text, index-aligned.
        """
        raise NotImplementedError

    def classify(self, table: Tag, text: str) -> str | None:
        raise NotImplementedError

    def scrub(self, kind: str, table: Tag) -> None:
        """Remove sponsor fragments from inside a kept section (in place)."""

    def parse_intro(self, table: Tag) -> str:
        raise NotImplementedError

    def parse_summary(self, table: Tag, news: list[dict]) -> tuple[list[dict], str]:
        raise NotImplementedError

    def parse_news_block(self, table: Tag, news_id: str,
                         resolver: LinkResolver) -> dict:
        raise NotImplementedError

    def parse_signals(self, table: Tag, resolver: LinkResolver) -> list[dict]:
        raise NotImplementedError
