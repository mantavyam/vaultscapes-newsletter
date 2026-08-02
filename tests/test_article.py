"""Long-form ("Deep Dive") sends: classification, parsing and block fidelity."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import cleaner  # noqa: E402
import parser as feed_parser  # noqa: E402
from utils.helpers import LinkResolver  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
# Two real sends: one with lists, one without; both with several images.
SUNDAY = FIXTURES / "article-sunday.eml"
TECHNICAL = FIXTURES / "article-technical.eml"
DIGEST = FIXTURES / "sample.eml"


def parse(path: Path) -> dict:
    payload = cleaner.load_eml(path)
    return feed_parser.parse(payload, cleaner.clean(payload.html),
                             LinkResolver(enabled=False))


@pytest.fixture(scope="module")
def sunday() -> dict:
    return parse(SUNDAY)


@pytest.fixture(scope="module")
def technical() -> dict:
    return parse(TECHNICAL)


def test_article_is_classified_not_treated_as_drift():
    payload = cleaner.load_eml(SUNDAY)
    kinds = [s.kind for s in cleaner.clean(payload.html).sections]
    assert "article" in kinds
    assert "intro" in kinds
    assert "author" in kinds


def test_both_kicker_variants_parse(sunday, technical):
    assert sunday["kicker"] == "Sunday Deep Dive"
    assert technical["kicker"] == "Technical Deep Dive"


def test_metadata(sunday):
    assert sunday["version"] == 2
    assert sunday["type"] == "article"
    assert sunday["title"] == (
        "Why Kimi K3's architecture is a masterclass in AI efficiency"
    )
    assert sunday["author"]["name"] == "Ben Dickson"
    assert sunday["intro"].startswith("A 2.8 trillion parameter")
    assert sunday["date"] and sunday["iso_date"]


def test_block_kinds_are_known(sunday, technical):
    allowed = {"heading", "paragraph", "list", "image"}
    for doc in (sunday, technical):
        assert doc["blocks"], "article produced no blocks"
        assert {b["kind"] for b in doc["blocks"]} <= allowed


def test_lists_are_captured_with_their_items(technical):
    lists = [b for b in technical["blocks"] if b["kind"] == "list"]
    assert len(lists) == 3
    assert all(block["items"] for block in lists)
    # List text must not also leak out as loose paragraphs.
    paragraphs = " ".join(
        b["html"] for b in technical["blocks"] if b["kind"] == "paragraph"
    )
    assert lists[0]["items"][0][:40] not in paragraphs


def test_every_image_is_kept(sunday, technical):
    assert len([b for b in sunday["blocks"] if b["kind"] == "image"]) == 3
    assert len([b for b in technical["blocks"] if b["kind"] == "image"]) == 2
    for doc in (sunday, technical):
        for block in doc["blocks"]:
            if block["kind"] == "image":
                assert block["src"].startswith("http")


def test_inline_links_survive_in_paragraphs(sunday):
    with_links = [
        b for b in sunday["blocks"]
        if b["kind"] == "paragraph" and "<a href=" in b["html"]
    ]
    assert len(with_links) >= 5
    assert any("Kimi K3</a>" in b["html"] for b in with_links)


def test_headings_are_not_repeated_as_paragraphs(sunday):
    headings = {b["text"] for b in sunday["blocks"] if b["kind"] == "heading"}
    assert headings
    bodies = [b["html"] for b in sunday["blocks"] if b["kind"] == "paragraph"]
    for heading in headings:
        assert heading not in bodies


def test_kicker_and_title_are_not_duplicated_in_the_body(sunday):
    first = sunday["blocks"][0]
    assert sunday["title"] not in (first.get("text"), first.get("html"))
    assert sunday["kicker"] not in (first.get("text"), first.get("html"))


def test_digest_still_parses_as_a_digest():
    doc = parse(DIGEST)
    assert doc["type"] == "digest"
    assert doc["version"] == 2
    assert doc["news"] and doc["signals"] and doc["summary"]
    assert "blocks" not in doc


def test_a_digest_missing_sections_is_still_reported_as_drift():
    """The drift alarm must survive the article branch."""
    payload = cleaner.load_eml(DIGEST)
    broken = payload.html.replace("Signals", "Sig_nals").replace(
        "Summary", "Sum_mary")
    with pytest.raises((cleaner.FormatDriftError, cleaner.NotADigestError)):
        cleaner.clean(broken)


def test_an_unknown_send_is_skipped_not_quarantined():
    payload = cleaner.load_eml(DIGEST)
    stripped = (
        payload.html.replace("Signals", "x").replace("Summary", "x")
        .replace("Top ", "x").replace("Deep Dive", "x")
    )
    with pytest.raises(cleaner.NotADigestError):
        cleaner.clean(stripped)
