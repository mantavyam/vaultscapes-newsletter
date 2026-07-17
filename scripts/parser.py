"""Parser: cleaned sections -> the versioned feed JSON payload.

Consumes the Section objects produced by cleaner.clean() and emits the schema
documented in the plan (§5.3): metadata + summary[] + news[] + signals[].
"""

from __future__ import annotations

import re

from bs4 import Tag

from cleaner import CleanResult, EmailPayload, FormatDriftError, Section
from utils import markers
from utils.helpers import (
    LinkResolver,
    ddmmyyyy,
    iso_date,
    issue_date_ist,
    squash_ws,
)

SCHEMA_VERSION = 1

_STAT_RE = re.compile(
    r"([\d,]+)\s+(" + "|".join(markers.STAT_TYPES) + r")\b"
)
_RANK_PREFIX_RE = re.compile(r"^(\d+)[.\s]")


def parse(payload: EmailPayload, cleaned: CleanResult,
          resolver: LinkResolver | None = None) -> dict:
    resolver = resolver or LinkResolver(enabled=False)
    by_kind: dict[str, list[Section]] = {}
    for section in cleaned.sections:
        by_kind.setdefault(section.kind, []).append(section)

    dt = issue_date_ist(payload.date_header)
    news = [
        _parse_news_block(s.table, f"news-{i + 1}", resolver)
        for i, s in enumerate(by_kind.get("news", []))
    ]
    summary, read_time = _parse_summary(by_kind["summary"][0].table, news)
    signals = _parse_signals(by_kind["signals"][0].table, resolver)

    if not news:
        raise FormatDriftError("Parsed zero news blocks")
    if not signals:
        raise FormatDriftError("Parsed zero signals")

    return {
        "version": SCHEMA_VERSION,
        "date": ddmmyyyy(dt),
        "iso_date": iso_date(dt),
        "subject": payload.subject,
        "intro": _parse_intro(by_kind["intro"][0].table),
        "read_time": read_time,
        "summary": summary,
        "news": news,
        "signals": signals,
    }


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

def _parse_intro(table: Tag) -> str:
    text = squash_ws(table.get_text(" ", strip=True))
    if text.startswith(markers.GREETING):
        text = text[len(markers.GREETING):].strip()
    return text


def _parse_summary(table: Tag, news: list[dict]) -> tuple[list[dict], str]:
    """Outline entries ("Top X" category + headline), linked to news blocks."""
    entries: list[dict] = []
    read_time = ""
    category = None
    for row in table.find_all("tr"):
        text = squash_ws(row.get_text(" ", strip=True))
        if not text:
            continue
        if text.startswith(markers.READ_TIME_PREFIX):
            read_time = text[len(markers.READ_TIME_PREFIX):].strip()
            continue
        if text in (markers.SUMMARY_HEADING, markers.SIGNALS_HEADING):
            category = None if text == markers.SUMMARY_HEADING else "signals"
            continue
        if text.startswith(markers.NEWS_CATEGORY_PREFIX) and len(text) < 40:
            category = text
            continue
        if category and category != "signals" and row.find("a"):
            headline = squash_ws(text.lstrip("▸").strip())
            entries.append({
                "category": category,
                "headline": headline,
                "news_id": _match_news_id(headline, news),
            })
            category = None
        # numbered signal-preview rows are ignored: the full Signals section
        # is the single source of truth for signals
    return entries, read_time


def _match_news_id(headline: str, news: list[dict]) -> str | None:
    """Match a summary headline to its full news block (whitespace-tolerant)."""
    norm = re.sub(r"\W+", "", headline).lower()
    for block in news:
        block_norm = re.sub(r"\W+", "", block["headline"]).lower()
        if norm == block_norm or norm in block_norm or block_norm in norm:
            return block["id"]
    return None


def _parse_news_block(table: Tag, news_id: str, resolver: LinkResolver) -> dict:
    rows = table.find_all("tr")
    category = ""
    headline = ""
    likes = None
    image_url = None
    body = ""
    bullets: list[str] = []
    read_more_url = None

    for row in rows:
        text = squash_ws(row.get_text(" ", strip=True))
        h1_cell = row.find(class_="h1")

        if not category and text.startswith(markers.NEWS_CATEGORY_PREFIX) and len(text) < 40:
            category = text
            continue
        if h1_cell is not None and not headline:
            headline = squash_ws(h1_cell.get_text(" ", strip=True))
            continue
        stat = _STAT_RE.fullmatch(text)
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
                bullets = [squash_ws(li.get_text(" ", strip=True)) for li in ul.find_all("li")]
                ul_text = squash_ws(ul.get_text(" ", strip=True))
                body = squash_ws(text.replace(ul_text, " "))
            else:
                body = text

    if not headline:
        raise FormatDriftError(f"News block {news_id}: headline not found")

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


def _parse_signals(table: Tag, resolver: LinkResolver) -> list[dict]:
    """Signal items are the class="h1" anchors inside the Signals section.

    For each anchor, the stat lives in the nearest ancestor table that also
    matches "<rank> ... <count> <Likes|Stars|Downloads>". Sponsored items were
    already removed by the cleaner; ranks are renumbered sequentially here.
    """
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
            m = _STAT_RE.search(text)
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
