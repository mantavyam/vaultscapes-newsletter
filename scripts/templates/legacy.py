"""Legacy AlphaSignal template (all sends up to mid-Nov 2026).

Reference sample: format/legacy.eml (also tests/fixtures/sample.eml and
the two Deep Dive article fixtures).

Landmarks:
    intro     "Hey, ..." / "Hey <Name>, ..." with a trailing "In Partnership with" fragment
    summary   "Summary Read time: 6 min 38 sec" then alternating category rows
              ("Top News", sponsor name, "Signals") and "▸ headline" item rows
    news      "Top <Category>" table, "12,441 Likes", body row with <ul>, "READ MORE"
    signals   "Signals" table; items "1 <headline> 5,367 Likes"; sponsored items
              carry "Presented by <name>"
    article   long-form "… Deep Dive" sends; "Today's Author" card is the byline
"""

from __future__ import annotations

import re

from bs4 import Tag

from utils import markers
from utils.helpers import LinkResolver, squash_ws

from .base import (
    ARTICLE, AUTHOR, GREETING_RE, INTRO, NEWS, SIGNALS, STAT_RE, SUMMARY,
    EmailTemplate, match_news_id,
)

SUMMARY_HEADING = "Summary"
SIGNALS_HEADING = "Signals"
READ_TIME_PREFIX = "Read time:"
NEWS_CATEGORY_PREFIX = "Top "
SPONSOR_PRESENTED_BY = "Presented by"
SPONSOR_PARTNERSHIP = "In Partnership with"

# Sponsored signal-preview row in the Summary outline: "2. ngrok: ..."
_SPONSOR_PREVIEW_RE = re.compile(r"^\d+\.\s*\S{1,24}:\s")
_RANK_PREFIX_RE = re.compile(r"^(\d+)[.\s]")


class LegacyTemplate(EmailTemplate):
    name = "legacy"

    def matches(self, tables: list[Tag], texts: list[str]) -> bool:
        # Not the greeting: "Hey <Name>," is shared with newer layouts, so it
        # would let legacy claim (and half-parse) an unknown redesign.
        return any(
            (t.startswith(SUMMARY_HEADING) and READ_TIME_PREFIX in t[:40])
            or markers.ARTICLE_KICKER_SUFFIX in t[:40]
            for t in texts
        )

    # -- classification ----------------------------------------------------

    def classify(self, table: Tag, text: str) -> str | None:
        if GREETING_RE.match(text):
            return INTRO
        if text.startswith(SUMMARY_HEADING):
            return SUMMARY
        if text.startswith(SIGNALS_HEADING):
            return SIGNALS
        if text.startswith(NEWS_CATEGORY_PREFIX):
            return NEWS
        # Long-form sends: the kicker opens the table, e.g. "Sunday Deep Dive".
        # Bounded lookahead so a digest merely mentioning the phrase can't match.
        if markers.ARTICLE_KICKER_SUFFIX in text[:40]:
            return ARTICLE
        if text.startswith(markers.AUTHOR_HEADING):
            # Junk in a digest, byline in an article; the core drops it for digests.
            return AUTHOR
        # Everything else: header nav, sponsor blocks, "forward →" /
        # "partner with us →" rows, footer, poll, unsubscribe.
        return None

    # -- scrubbing ---------------------------------------------------------

    def scrub(self, kind: str, table: Tag) -> None:
        if kind == INTRO:
            self._scrub_intro(table)
        elif kind == SUMMARY:
            self._scrub_summary(table)
        elif kind == SIGNALS:
            self._scrub_signals(table)

    @staticmethod
    def _scrub_intro(table: Tag) -> None:
        """Remove the trailing 'In Partnership with' fragment and stray images."""
        for el in table.find_all(string=lambda s: s and SPONSOR_PARTNERSHIP in s):
            row = el.find_parent("tr")
            (row or el.parent or el).extract()
        for img in table.find_all("img"):
            img.decompose()

    @staticmethod
    def _scrub_summary(table: Tag) -> None:
        """Drop sponsor outline entries from the Summary section.

        Rows alternate: a short category row ("Top Repo" / "Top News" / sponsor
        name / "Signals") followed by an item row. A category row that is
        neither "Top ..." nor "Signals" is a sponsor name — remove it and its
        item. Numbered signal-preview rows are kept unless sponsored.
        """
        drop_next_items = False
        for row in table.find_all("tr"):
            text = squash_ws(row.get_text(" ", strip=True))
            if not text:
                continue
            is_category = len(text) < 40 and not row.find("a") and not text[0].isdigit()
            if is_category:
                if text.startswith(NEWS_CATEGORY_PREFIX) or text in (
                    SUMMARY_HEADING, SIGNALS_HEADING,
                ) or text.startswith(READ_TIME_PREFIX):
                    drop_next_items = False
                else:
                    drop_next_items = True  # sponsor name row
                    row.decompose()
                continue
            if drop_next_items:
                row.decompose()
            elif text[0].isdigit() and _SPONSOR_PREVIEW_RE.match(text):
                # "2. ngrok: Your self-hosted models..." — sponsor name + colon
                row.decompose()

    @staticmethod
    def _scrub_signals(table: Tag) -> None:
        """Drop sponsored items: the smallest ancestor table holding the
        'Presented by' line but not the 'Signals' heading."""
        for el in table.find_all(string=lambda s: s and SPONSOR_PRESENTED_BY in s):
            node = el.find_parent("table")
            while node is not None:
                parent = node.find_parent("table")
                if parent is None or SIGNALS_HEADING in squash_ws(
                    parent.get_text(" ", strip=True)
                )[:20]:
                    break
                if squash_ws(parent.get_text(" ", strip=True)).startswith(
                    SIGNALS_HEADING
                ):
                    break
                node = parent
            if node is not None:
                node.decompose()

    # -- parsing -----------------------------------------------------------

    def parse_intro(self, table: Tag) -> str:
        return GREETING_RE.sub("", squash_ws(table.get_text(" ", strip=True)), count=1)

    def parse_summary(self, table: Tag, news: list[dict]) -> tuple[list[dict], str]:
        entries: list[dict] = []
        read_time = ""
        category = None
        for row in table.find_all("tr"):
            text = squash_ws(row.get_text(" ", strip=True))
            if not text:
                continue
            if text.startswith(READ_TIME_PREFIX):
                read_time = text[len(READ_TIME_PREFIX):].strip()
                continue
            if text in (SUMMARY_HEADING, SIGNALS_HEADING):
                category = None if text == SUMMARY_HEADING else "signals"
                continue
            if text.startswith(NEWS_CATEGORY_PREFIX) and len(text) < 40:
                category = text
                continue
            if category and category != "signals" and row.find("a"):
                headline = squash_ws(text.lstrip("▸").strip())
                entries.append({
                    "category": category,
                    "headline": headline,
                    "news_id": match_news_id(headline, news),
                })
                category = None
            # numbered signal-preview rows are ignored: the full Signals
            # section is the single source of truth for signals
        return entries, read_time

    def parse_news_block(self, table: Tag, news_id: str,
                         resolver: LinkResolver) -> dict:
        category = ""
        headline = ""
        likes = None
        image_url = None
        body = ""
        bullets: list[str] = []
        read_more_url = None

        for row in table.find_all("tr"):
            text = squash_ws(row.get_text(" ", strip=True))
            h1_cell = row.find(class_="h1")

            if not category and text.startswith(NEWS_CATEGORY_PREFIX) and len(text) < 40:
                category = text
                continue
            if h1_cell is not None and not headline:
                headline = squash_ws(h1_cell.get_text(" ", strip=True))
                continue
            stat = STAT_RE.fullmatch(text)
            if stat and likes is None:
                likes = int(stat.group(1).replace(",", ""))
                continue
            img = row.find("img")
            if img is not None and image_url is None and img.get("src"):
                image_url = img["src"]
                continue
            if text == "READ MORE" and read_more_url is None:
                a = row.find("a", href=True)
                if a is not None:
                    read_more_url = resolver.resolve(a["href"])
                continue
            if len(text) > 100 and not body:
                ul = row.find("ul")
                if ul is not None:
                    bullets = [squash_ws(li.get_text(" ", strip=True))
                               for li in ul.find_all("li")]
                    ul_text = squash_ws(ul.get_text(" ", strip=True))
                    body = squash_ws(text.replace(ul_text, " "))
                else:
                    body = text

        return {
            "id": news_id,
            "category": category,
            "headline": headline,
            "likes": likes,
            "body": body,
            "bullets": bullets,
            "image_url": image_url,
            "read_more_url": read_more_url,
        }

    def parse_signals(self, table: Tag, resolver: LinkResolver) -> list[dict]:
        """Items are the class="h1" anchors; the stat lives in the nearest
        ancestor table matching "<rank> ... <count> <Likes|Stars|Downloads>"."""
        items: list[dict] = []
        seen: set[str] = set()
        for a in table.find_all("a", class_="h1", href=True):
            headline = squash_ws(a.get_text(" ", strip=True))
            if not headline or headline in seen:
                continue
            seen.add(headline)

            stat = None
            node = a.find_parent("table")
            while node is not None:
                text = squash_ws(node.get_text(" ", strip=True))
                m = STAT_RE.search(text)
                if m and _RANK_PREFIX_RE.match(text):
                    stat = {
                        "type": m.group(2).lower(),
                        "value": int(m.group(1).replace(",", "")),
                    }
                    break
                node = node.find_parent("table")

            items.append({
                "rank": len(items) + 1,
                "headline": headline,
                "stat": stat,
                "url": resolver.resolve(a["href"]),
            })
        return items
