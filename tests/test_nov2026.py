"""NOV26 template (2026-11-23 onwards) and template detection."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import cleaner  # noqa: E402
import parser as feed_parser  # noqa: E402
from utils.helpers import LinkResolver  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
NOV26 = FIXTURES / "nov2026.eml"
LEGACY = FIXTURES / "sample.eml"

JUNK = ("Presented by", "In Partnership with", "Verda", "Runpod", "Lium",
        "AlphaSignal PRO", "Upgrade to PRO", "Your feed", "Our Events",
        "How was today", "Unsubscribe")


@pytest.fixture(scope="module")
def cleaned():
    payload = cleaner.load_eml(NOV26)
    return payload, cleaner.clean(payload.html)


@pytest.fixture(scope="module")
def issue(cleaned):
    payload, result = cleaned
    return feed_parser.parse(payload, result, LinkResolver(enabled=False))


def test_detects_nov2026_template(cleaned):
    assert cleaned[1].template.name == "nov2026"
    assert cleaner.clean(cleaner.load_eml(LEGACY).html).template.name == "legacy"


def test_sections_and_junk_dropped(cleaned):
    _, result = cleaned
    assert [s.kind for s in result.sections] == [
        "intro", "summary", "news", "news", "news", "signals"]
    for word in JUNK:
        assert word not in result.cleaned_html, word


def test_payload_shape_matches_legacy(issue):
    legacy_payload = cleaner.load_eml(LEGACY)
    legacy = feed_parser.parse(legacy_payload, cleaner.clean(legacy_payload.html),
                               LinkResolver(enabled=False))
    assert issue.keys() == legacy.keys()
    assert issue["news"][0].keys() == legacy["news"][0].keys()
    assert issue["signals"][0].keys() == legacy["signals"][0].keys()
    assert issue["summary"][0].keys() == legacy["summary"][0].keys()


def test_intro_and_meta(issue):
    assert issue["type"] == "digest"
    assert issue["date"] == "26-11-2026"
    assert issue["read_time"] == "6 min 0 sec"
    assert issue["intro"].startswith("Google shipped a 17-guide Gemma 4")
    assert "Partnership" not in issue["intro"]


def test_summary_excludes_sponsors_and_links_news(issue):
    assert [s["news_id"] for s in issue["summary"]] == ["news-1", "news-2", "news-3"]
    assert all(s["category"] == "Top Model" for s in issue["summary"])


def test_news_blocks(issue):
    assert [n["likes"] for n in issue["news"]] == [3714, 3617, 3400]
    for n in issue["news"]:
        assert n["category"] == "Top Model"
        assert n["headline"] and n["body"] and n["bullets"]
        assert n["image_url"].startswith("https://alphasignal.ai/image/")
        assert n["read_more_url"]
        assert not any(b in n["body"] for b in n["bullets"])


def test_signals_drop_sponsor_and_read_stat_not_headline(issue):
    sig = issue["signals"]
    assert [s["rank"] for s in sig] == [1, 2, 3, 4, 5]
    assert not any("H100" in s["headline"] for s in sig)  # Lium.io sponsor
    assert [s["stat"]["value"] for s in sig] == [3117, 3088, 3032, 2606, 2491]


def test_personalised_greeting_on_legacy_layout():
    """Nov 2026: 'Hey Vaultscapes,' also appears in the legacy layout."""
    payload = cleaner.load_eml(LEGACY)
    html = payload.html.replace("Hey,", "Hey Vaultscapes,", 1)
    result = cleaner.clean(html)
    assert result.template.name == "legacy"
    payload.html = html
    issue = feed_parser.parse(payload, result, LinkResolver(enabled=False))
    assert not issue["intro"].startswith("Vaultscapes")
