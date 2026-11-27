"""AlphaSignal template introduced 2026-11-23 ("NOV26").

Reference sample: format/nov26.eml.

Landmarks (differences from legacy in brackets):
    intro     "Hey <Name>, ..." [personalised greeting]; the "In Partnership
              with" ad is its own nested table inside the intro
    summary   "Summary 6 min 0 sec read" [no "Read time:" prefix]; one
              "→ <a>headline</a> · CATEGORY" row per item [category is an
              uppercase suffix; a non-"TOP …" suffix marks a sponsor]; then
              "SIGNALS" and the signal previews (sponsored ones carry a suffix)
    news      "Top <Category>" box; "▲ 3,714 Likes"; body is a <div> of <p>
              and <ul>; "Read more" button [mixed case] beside "Forward"
    signals   "Signals" box; items have no rank number [ranks implied by
              order], "▲ N Likes" and a thumbnail; sponsored items carry
              "Presented by <name>"
    junk      "Presented by" sponsor boxes, "Your feed …"/"AlphaSignal PRO"
              upsells, "Our Events", feedback poll + footer — dropped by
              classify() returning None
"""

from __future__ import annotations

import re

from bs4 import Tag

from utils.helpers import LinkResolver, squash_ws

from .base import (
    GREETING_RE, INTRO, NEWS, SIGNALS, SUMMARY, EmailTemplate, match_news_id, parse_stat,
)

_SUMMARY_RE = re.compile(r"^Summary\s+(\d+\s*min(?:\s*\d+\s*sec)?)\s+read\b")
SUMMARY_HEADING = "Summary"
SUMMARY_SIGNALS_DIVIDER = "SIGNALS"
SIGNALS_HEADING = "Signals"
NEWS_CATEGORY_PREFIX = "Top "
SUMMARY_NEWS_TAG_PREFIX = "TOP "
SPONSOR_PRESENTED_BY = "Presented by"
SPONSOR_PARTNERSHIP = "In Partnership with"
READ_MORE = "read more"


def _count(node: Tag, pred) -> int:
    return sum(1 for el in node.find_all(True) if pred(el)) + (1 if pred(node) else 0)


def _item_root(el, scope: Tag, pred) -> Tag | None:
    """Largest ancestor of `el` (below `scope`) holding at most one element
    matching `pred` — i.e. the whole visual item and nothing of its siblings."""
    node = el if isinstance(el, Tag) else el.parent
    while node.parent is not None and node.parent is not scope:
        if _count(node.parent, pred) > 1:
            break
        node = node.parent
    return node if node is not scope else None


def _is_h1_link(el: Tag) -> bool:
    return el.name == "a" and "h1" in (el.get("class") or [])


def _is_link(el: Tag) -> bool:
    return el.name == "a" and el.has_attr("href")


def _summary_tag(a: Tag) -> str:
    """The "· TOP MODEL" suffix after a summary link, without the dot."""
    for sib in a.next_siblings:
        text = squash_ws(sib.get_text(" ", strip=True) if isinstance(sib, Tag) else str(sib))
        if text:
            return text.lstrip("·").strip()
    return ""


class Nov2026Template(EmailTemplate):
    name = "nov2026"

    def matches(self, tables: list[Tag], texts: list[str]) -> bool:
        return any(_SUMMARY_RE.match(t) for t in texts)

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
        return None

    # -- scrubbing ---------------------------------------------------------

    def scrub(self, kind: str, table: Tag) -> None:
        if kind == INTRO:
            for el in table.find_all(string=lambda s: s and SPONSOR_PARTNERSHIP in s):
                # climb to the ad table: the largest one without the greeting
                node = el.find_parent("table")
                while node is not None:
                    parent = node.find_parent("table")
                    if parent is None or parent is table or GREETING_RE.match(
                        squash_ws(parent.get_text(" ", strip=True))
                    ):
                        break
                    node = parent
                if node is not None and node is not table:
                    node.decompose()
            for img in table.find_all("img"):
                img.decompose()
        elif kind == SUMMARY:
            for a in table.find_all(_is_link):
                tag = _summary_tag(a)
                if tag and not tag.startswith(SUMMARY_NEWS_TAG_PREFIX):
                    item = _item_root(a, table, _is_link)
                    if item is not None:
                        item.decompose()
        elif kind == SIGNALS:
            for el in table.find_all(string=lambda s: s and SPONSOR_PRESENTED_BY in s):
                item = _item_root(el, table, _is_h1_link)
                if item is not None:
                    item.decompose()

    # -- parsing -----------------------------------------------------------

    def parse_intro(self, table: Tag) -> str:
        return GREETING_RE.sub("", squash_ws(table.get_text(" ", strip=True)), count=1)

    def parse_summary(self, table: Tag, news: list[dict]) -> tuple[list[dict], str]:
        m = _SUMMARY_RE.match(squash_ws(table.get_text(" ", strip=True)))
        read_time = m.group(1) if m else ""
        entries: list[dict] = []
        for el in table.descendants:
            if not isinstance(el, Tag):
                continue
            if el.name == "td" and squash_ws(el.get_text(" ", strip=True)) == SUMMARY_SIGNALS_DIVIDER:
                break  # the rest are signal previews; Signals is the source of truth
            if not _is_link(el):
                continue
            headline = squash_ws(el.get_text(" ", strip=True))
            if not headline:
                continue
            news_id = match_news_id(headline, news)
            block = next((n for n in news if n["id"] == news_id), None)
            entries.append({
                # use the block's own casing ("Top Model", not "TOP MODEL")
                "category": block["category"] if block else _summary_tag(el).title(),
                "headline": headline,
                "news_id": news_id,
            })
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
            if not text and row.find("img") is None:
                continue
            h1_cell = row.find(class_="h1")
            if not category and text.startswith(NEWS_CATEGORY_PREFIX) and len(text) < 40:
                category = text
                continue
            if h1_cell is not None and not headline:
                headline = squash_ws(h1_cell.get_text(" ", strip=True))
                continue
            if likes is None and len(text) < 30:
                stat = parse_stat(text)
                if stat is not None:
                    likes = stat["value"]
                    continue
            if text.lower() == READ_MORE and read_more_url is None:
                a = row.find("a", href=True)
                if a is not None:
                    read_more_url = resolver.resolve(a["href"])
                continue
            img = row.find("img")
            if img is not None and image_url is None and img.get("src") and not text:
                image_url = img["src"]
                continue
            if not body and (row.find("p") is not None or len(text) > 100):
                container = row.find("div") or row
                paras = [squash_ws(p.get_text(" ", strip=True))
                         for p in container.find_all("p")
                         if not p.find_parent(["li", "ul", "ol"])]
                bullets = [squash_ws(li.get_text(" ", strip=True))
                           for li in container.find_all("li")]
                body = " ".join(p for p in paras if p) if paras else text

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
        items: list[dict] = []
        seen: set[str] = set()
        for a in table.find_all(_is_h1_link):
            headline = squash_ws(a.get_text(" ", strip=True))
            if not headline or headline in seen:
                continue
            seen.add(headline)
            item = _item_root(a, table, _is_h1_link) or a
            # headlines can carry numbers too ("Hits 800,000 Downloads")
            rest = squash_ws(item.get_text(" ", strip=True)).replace(headline, " ", 1)
            items.append({
                "rank": len(items) + 1,
                "headline": headline,
                "stat": parse_stat(rest),
                "url": resolver.resolve(a["href"]),
            })
        return items
