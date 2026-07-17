"""Cleaner: raw AlphaSignal email HTML -> classified sections + cleaned HTML.

The email body is one giant nested-table layout with almost no CSS classes.
The one exploitable invariant: a single <td> holds ~20 direct child <table>
elements, one per visual section. This module finds that container, classifies
each child table by its leading text, drops the junk (header nav, sponsor
blocks, author card, footer, feedback poll, tracking pixels), and returns the
surviving sections both as parsed objects and as a standalone cleaned HTML
document (the audit artifact).
"""

from __future__ import annotations

import email
import re
from dataclasses import dataclass, field
from email import policy
from pathlib import Path

from bs4 import BeautifulSoup, Tag

from utils import markers
from utils.helpers import is_tracking_pixel, squash_ws

# Minimum direct child tables for a td to qualify as the section container.
_MIN_SECTION_TABLES = 5

# Sponsored signal-preview row in the Summary outline: "2. ngrok: ..."
_SPONSOR_PREVIEW_RE = re.compile(r"^\d+\.\s*\S{1,24}:\s")


class FormatDriftError(RuntimeError):
    """Raised when the email HTML no longer matches the expected structure."""


@dataclass
class EmailPayload:
    """Everything extracted from one .eml file."""

    message_id: str
    subject: str
    date_header: str
    html: str


@dataclass
class Section:
    kind: str  # intro | summary | news | signals
    table: Tag
    lead: str = ""


@dataclass
class CleanResult:
    sections: list[Section] = field(default_factory=list)
    cleaned_html: str = ""


# ---------------------------------------------------------------------------
# .eml loading
# ---------------------------------------------------------------------------

def load_eml(path: Path) -> EmailPayload:
    with open(path, "rb") as f:
        msg = email.message_from_binary_file(f, policy=policy.default)
    html = None
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            html = part.get_content()
    if html is None:
        raise FormatDriftError(f"No text/html part in {path}")
    return EmailPayload(
        message_id=msg.get("Message-ID", "").strip(),
        subject=str(msg.get("Subject", "")).strip(),
        date_header=msg.get("Date", ""),
        html=html,
    )


# ---------------------------------------------------------------------------
# Section discovery & classification
# ---------------------------------------------------------------------------

def _find_section_container(soup: BeautifulSoup) -> Tag:
    best = None
    best_count = 0
    for el in soup.find_all("td"):
        count = len(el.find_all("table", recursive=False))
        if count >= _MIN_SECTION_TABLES and count > best_count:
            best, best_count = el, count
    if best is None:
        raise FormatDriftError(
            f"Section container not found: no <td> with >= {_MIN_SECTION_TABLES} "
            "direct child tables. AlphaSignal likely changed their template."
        )
    return best


def _classify(table: Tag) -> str | None:
    """Return section kind to keep, or None to drop the table."""
    text = squash_ws(table.get_text(" ", strip=True))
    if not text:
        return None
    if text.startswith(markers.GREETING):
        return "intro"
    if text.startswith(markers.SUMMARY_HEADING):
        return "summary"
    if text.startswith(markers.SIGNALS_HEADING):
        return "signals"
    if text.startswith(markers.NEWS_CATEGORY_PREFIX):
        return "news"
    # Everything else is junk: header nav, author card, sponsor blocks,
    # "forward →" / "partner with us →" rows, footer, poll, unsubscribe.
    return None


def _scrub_intro(table: Tag) -> None:
    """Remove the trailing 'In Partnership with' fragment inside the intro table."""
    for el in table.find_all(string=lambda s: s and markers.SPONSOR_PARTNERSHIP in s):
        row = el.find_parent("tr")
        (row or el.parent or el).extract()
    # partnership sponsor logo (and any other stray img) has no place in the intro
    for img in table.find_all("img"):
        img.decompose()


def _scrub_summary(table: Tag) -> None:
    """Drop sponsor outline entries from the Summary section.

    Summary rows alternate: a short category row ("Top Repo" / "Top News" /
    sponsor name / "Signals") followed by an item row. A category row that is
    neither "Top ..." nor "Signals" is a sponsor name — remove it and its item.
    Numbered signal-preview rows after the "Signals" category are kept; the
    parser dedups them against the full Signals section.
    """
    rows = table.find_all("tr")
    drop_next_items = False
    for row in rows:
        text = squash_ws(row.get_text(" ", strip=True))
        if not text:
            continue
        is_category = len(text) < 40 and not row.find("a") and not text[0].isdigit()
        if is_category:
            if text.startswith(markers.NEWS_CATEGORY_PREFIX) or text in (
                markers.SUMMARY_HEADING,
                markers.SIGNALS_HEADING,
            ) or text.startswith(markers.READ_TIME_PREFIX):
                drop_next_items = False
            else:
                drop_next_items = True  # sponsor name row
                row.decompose()
            continue
        if drop_next_items:
            row.decompose()
        elif text[0].isdigit() and _SPONSOR_PREVIEW_RE.match(text):
            # sponsored signal-preview row: "2. ngrok: Your self-hosted models..."
            # (sponsor name + colon right after the rank; organic headlines don't
            # lead with a colon-suffixed name)
            row.decompose()


def _scrub_signals(table: Tag) -> None:
    """Drop sponsored items from the full Signals section.

    Each signal item lives in its own sub-table; a sponsored one carries a
    'Presented by <name>' line. Remove the smallest ancestor table that
    contains the sponsor line but not the 'Signals' heading.
    """
    for el in table.find_all(string=lambda s: s and markers.SPONSOR_PRESENTED_BY in s):
        node = el.find_parent("table")
        while node is not None:
            text = node.get_text(" ", strip=True)
            parent = node.find_parent("table")
            if parent is None or markers.SIGNALS_HEADING in squash_ws(
                parent.get_text(" ", strip=True)
            )[:20]:
                break
            # climb while the parent is still item-scoped (no heading in it)
            if squash_ws(parent.get_text(" ", strip=True)).startswith(
                markers.SIGNALS_HEADING
            ):
                break
            node = parent
        if node is not None:
            node.decompose()


def _strip_tracking_pixels(soup: BeautifulSoup) -> None:
    for img in soup.find_all("img"):
        src = img.get("src", "")
        if is_tracking_pixel(src):
            img.decompose()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def clean(html: str) -> CleanResult:
    soup = BeautifulSoup(html, "lxml")
    _strip_tracking_pixels(soup)
    container = _find_section_container(soup)

    sections: list[Section] = []
    for table in container.find_all("table", recursive=False):
        kind = _classify(table)
        if kind is None:
            continue
        if kind == "intro":
            _scrub_intro(table)
        elif kind == "summary":
            _scrub_summary(table)
        elif kind == "signals":
            _scrub_signals(table)
        lead = squash_ws(table.get_text(" ", strip=True))[:80]
        sections.append(Section(kind=kind, table=table, lead=lead))

    _validate(sections)
    return CleanResult(sections=sections, cleaned_html=_render(sections))


def _validate(sections: list[Section]) -> None:
    kinds = [s.kind for s in sections]
    problems = []
    if "intro" not in kinds:
        problems.append("intro section missing")
    if "summary" not in kinds:
        problems.append("summary section missing")
    if kinds.count("news") < 1:
        problems.append("no news blocks found")
    if "signals" not in kinds:
        problems.append("signals section missing")
    if problems:
        raise FormatDriftError(
            "Cleaned email failed validation: " + "; ".join(problems)
        )


def _render(sections: list[Section]) -> str:
    """Standalone cleaned HTML document — the audit artifact."""
    parts = [
        "<!DOCTYPE html>",
        '<html><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>AlphaSignal (cleaned)</title>",
        "<style>body{margin:0 auto;max-width:640px;font-family:Helvetica,Arial,"
        "sans-serif;background:#fff;color:#222}table{width:100%}</style>",
        "</head><body>",
    ]
    for section in sections:
        parts.append(f"<!-- section: {section.kind} -->")
        parts.append(str(section.table))
    parts.append("</body></html>")
    return "\n".join(parts)
