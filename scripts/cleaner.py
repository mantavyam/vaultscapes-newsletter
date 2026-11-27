"""Cleaner: raw AlphaSignal email HTML -> classified sections + cleaned HTML.

The email body is one giant nested-table layout with almost no CSS classes.
The one exploitable invariant: a single <td> holds ~20 direct child <table>
elements, one per visual section. This module finds that container, detects which
template the email uses (scripts/templates/), lets that template classify each
child table and scrub sponsor fragments, validates, and returns the
surviving sections both as parsed objects and as a standalone cleaned HTML
document (the audit artifact).
"""

from __future__ import annotations

import email
from dataclasses import dataclass, field
from email import policy
from pathlib import Path

from bs4 import BeautifulSoup, Tag

import inspection
import templates
from inspection import Fingerprint
from templates.base import EmailTemplate
from utils.helpers import is_tracking_pixel, squash_ws

# Minimum direct child tables for a td to qualify as the section container.
_MIN_SECTION_TABLES = 5


class FormatDriftError(RuntimeError):
    """Email looks like newsletter content but no template could parse it —
    most likely AlphaSignal launched a new layout (they never announce it).

    Carries what the pipeline saw, for the `new-template` issue.
    """

    def __init__(self, message: str, fingerprint: Fingerprint | None = None,
                 template: str | None = None, leads: list[str] | None = None):
        super().__init__(message)
        self.fingerprint = fingerprint
        self.template = template
        self.leads = leads or []


class NotADigestError(RuntimeError):
    """Email carries no newsletter content (announcement, upsell, ad send).

    Decided by inspection.fingerprint(), not by template landmarks, so a
    redesigned digest can never be mistaken for one and silently skipped.
    """


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
    template: EmailTemplate | None = None
    fingerprint: Fingerprint | None = None


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
    fp = inspection.fingerprint(soup)

    def unparsed(reason: str, template: EmailTemplate | None = None,
                 leads: list[str] | None = None) -> Exception:
        """Content -> potential new template; no content -> skip."""
        if fp.verdict == inspection.PROMO:
            return NotADigestError(f"no newsletter content ({fp.summary_line()})")
        return FormatDriftError(reason, fingerprint=fp,
                                template=template.name if template else None,
                                leads=leads)

    try:
        container = _find_section_container(soup)
    except FormatDriftError as exc:
        raise unparsed(str(exc)) from None

    tables = container.find_all("table", recursive=False)
    texts = [squash_ws(t.get_text(" ", strip=True)) for t in tables]
    leads = [t[:100] for t in texts if t]
    template = templates.detect(tables, texts)
    if template is None:
        raise unparsed("no registered template recognises this layout", leads=leads)

    sections: list[Section] = []
    for table, text in zip(tables, texts):
        kind = template.classify(table, text) if text else None
        if kind is None:
            continue
        template.scrub(kind, table)
        lead = squash_ws(table.get_text(" ", strip=True))[:80]
        sections.append(Section(kind=kind, table=table, lead=lead))

    # The author card is a byline in an article but junk in a digest, where it
    # has always been dropped. Classification keeps it; digests discard it here
    # so their output is unchanged.
    if not any(s.kind == "article" for s in sections):
        sections = [s for s in sections if s.kind != "author"]

    problems = _validate(sections)
    if problems:
        raise unparsed(f"{template.name} template matched but: " + "; ".join(problems),
                       template, leads)
    return CleanResult(sections=sections, cleaned_html=_render(sections),
                       template=template, fingerprint=fp)


def _validate(sections: list[Section]) -> list[str]:
    kinds = [s.kind for s in sections]
    if "article" in kinds:
        return [] if "intro" in kinds else ["article is missing its intro section"]
    problems = []
    if "intro" not in kinds:
        problems.append("intro section missing")
    if "summary" not in kinds:
        problems.append("summary section missing")
    if kinds.count("news") < 1:
        problems.append("no news blocks found")
    if "signals" not in kinds:
        problems.append("signals section missing")
    return problems


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
