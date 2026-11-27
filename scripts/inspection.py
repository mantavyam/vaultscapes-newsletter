"""Template-independent inspection: is this email content, and did we get all of it?

AlphaSignal never announces a redesign, so the pipeline cannot rely on a
template to say "this is a newsletter". Templates describe *markup*; this
module looks for the *content pattern* every digest/article has carried across
all layouts so far, using signals that survive a redesign:

    digest evidence    engagement stats ("3,714 Likes" / "Stars" / "Downloads"),
                       headline links (class="h1"), a "Summary" and a "Signals"
                       section, a read-time phrase, "Top <Category>" labels
    article evidence   a "… Deep Dive" kicker, many long paragraphs, content
                       images from alphasignal.ai/image/

Measured on real sends (see tests/test_inspection.py):

    send                 stats h1  summary signals readtime top  longp deepdive
    legacy digest           8  13     ✓       ✓       ✓       2     2–5
    nov26 digest           10  14     ✓       ✓       ✓       1     5
    deep dive article       0  1–2                                 13–22   ✓
    announcement (promo)    0   0                                  1

From the fingerprint the core decides, *independently of which template matched*:

    PROMO (score <= 1)                       -> skip (announcement, ad send)
    otherwise + a template parsed it         -> publish, then coverage check
    otherwise + no template / parse failed   -> possible new template: issue

UNCERTAIN (score 2-3) is deliberately treated like content: a false
`new-template` alert costs a glance, a silently skipped newsletter costs an issue.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

from utils import markers
from utils.helpers import squash_ws

CONTENT, UNCERTAIN, PROMO = "content", "uncertain", "promo"

_STAT_RE = re.compile(r"\b\d[\d,]*\s+(?:" + "|".join(markers.STAT_TYPES) + r")\b")
_READ_TIME_RE = re.compile(r"\b\d+\s*min(?:\s*\d+\s*sec)?\s*read\b|Read time:", re.I)
_TOP_CATEGORY_RE = re.compile(r"\bTop [A-Z][a-z]+\b")

# Scores at or above CONTENT_SCORE are content, at or below PROMO_SCORE promo.
# Real digests score 9, articles 5, the announcement 0 — wide margins on both sides.
CONTENT_SCORE = 4
PROMO_SCORE = 1


@dataclass
class Fingerprint:
    stats: int = 0
    headline_links: int = 0
    content_images: int = 0
    long_paragraphs: int = 0
    has_summary: bool = False
    has_signals: bool = False
    has_read_time: bool = False
    top_categories: int = 0
    has_deep_dive: bool = False
    digest_score: int = 0
    article_score: int = 0
    verdict: str = PROMO
    reasons: list[str] = field(default_factory=list)

    @property
    def is_content(self) -> bool:
        return self.verdict == CONTENT

    def summary_line(self) -> str:
        return (f"verdict={self.verdict} digest_score={self.digest_score} "
                f"article_score={self.article_score} stats={self.stats} "
                f"h1={self.headline_links} images={self.content_images} "
                f"long_p={self.long_paragraphs} summary={self.has_summary} "
                f"signals={self.has_signals} read_time={self.has_read_time} "
                f"top_categories={self.top_categories} deep_dive={self.has_deep_dive}")


def fingerprint(html: str | BeautifulSoup) -> Fingerprint:
    soup = html if isinstance(html, BeautifulSoup) else BeautifulSoup(html, "lxml")
    text = squash_ws(soup.get_text(" "))
    fp = Fingerprint(
        stats=len(_STAT_RE.findall(text)),
        headline_links=len(soup.select(".h1")),
        content_images=sum(1 for img in soup.find_all("img")
                           if "/image/" in (img.get("src") or "")),
        long_paragraphs=sum(1 for p in soup.find_all("p")
                            if len(squash_ws(p.get_text(" "))) > 200),
        has_summary=bool(re.search(r"\bSummary\b", text)),
        has_signals=bool(re.search(r"\bSignals\b", text, re.I)),
        has_read_time=bool(_READ_TIME_RE.search(text)),
        top_categories=len(set(_TOP_CATEGORY_RE.findall(text))),
        has_deep_dive=markers.ARTICLE_KICKER_SUFFIX in text,
    )

    digest = [
        (fp.stats >= 3, 3, f"{fp.stats} engagement stats"),
        (fp.headline_links >= 3, 2, f"{fp.headline_links} headline links"),
        (fp.has_summary, 1, "Summary section"),
        (fp.has_signals, 1, "Signals section"),
        (fp.has_read_time, 1, "read-time phrase"),
        (fp.top_categories >= 1, 1, "'Top <Category>' labels"),
    ]
    article = [
        (fp.has_deep_dive, 2, "'Deep Dive' kicker"),
        (fp.long_paragraphs >= 8, 2, f"{fp.long_paragraphs} long paragraphs"),
        (fp.content_images >= 2, 1, f"{fp.content_images} content images"),
    ]
    fp.digest_score = sum(w for ok, w, _ in digest if ok)
    fp.article_score = sum(w for ok, w, _ in article if ok)
    best = max(fp.digest_score, fp.article_score)
    fp.reasons = [why for ok, _, why in digest + article if ok]
    if best >= CONTENT_SCORE:
        fp.verdict = CONTENT
    elif best <= PROMO_SCORE:
        fp.verdict = PROMO
    else:
        fp.verdict = UNCERTAIN
    return fp


# ---------------------------------------------------------------------------
# Coverage: a template that "parsed" a redesigned email may still miss fields.
# ---------------------------------------------------------------------------

def coverage_problems(payload: dict) -> list[str]:
    """Fields a correct parse always fills; any gap hints at partial drift."""
    problems: list[str] = []
    if payload.get("type") == "article":
        if not payload.get("title"):
            problems.append("article title empty")
        if len(payload.get("blocks", [])) < 5:
            problems.append(f"only {len(payload.get('blocks', []))} article blocks")
        return problems

    news = payload.get("news", [])
    signals = payload.get("signals", [])
    summary = payload.get("summary", [])
    for field_name in ("body", "likes", "image_url", "read_more_url", "category"):
        missing = [n["id"] for n in news if not n.get(field_name)]
        if missing:
            problems.append(f"news without {field_name}: {', '.join(missing)}")
    no_stat = [str(s["rank"]) for s in signals if not s.get("stat")]
    if no_stat:
        problems.append(f"signals without stat: ranks {', '.join(no_stat)}")
    if len(signals) < 3:
        problems.append(f"only {len(signals)} signals")
    if not payload.get("read_time"):
        problems.append("read_time empty")
    if not payload.get("intro"):
        problems.append("intro empty")
    if len(summary) != len(news):
        problems.append(f"summary has {len(summary)} entries for {len(news)} news blocks")
    unlinked = [s["headline"][:40] for s in summary if not s.get("news_id")]
    if unlinked:
        problems.append(f"summary entries not linked to news: {unlinked}")
    return problems
