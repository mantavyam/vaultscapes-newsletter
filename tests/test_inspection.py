"""Content fingerprint: promo sends are skipped, possible new templates raise."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import cleaner  # noqa: E402
import inspection  # noqa: E402
import parser as feed_parser  # noqa: E402
from utils.helpers import LinkResolver  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


def html(name: str) -> str:
    return cleaner.load_eml(FIXTURES / name).html


@pytest.mark.parametrize("name, verdict", [
    ("sample.eml", inspection.CONTENT),
    ("nov2026.eml", inspection.CONTENT),
    ("article-sunday.eml", inspection.CONTENT),
    ("article-technical.eml", inspection.CONTENT),
    ("announcement.eml", inspection.PROMO),
])
def test_fingerprint_verdicts(name, verdict):
    assert inspection.fingerprint(html(name)).verdict == verdict


def test_announcement_is_skipped_not_alerted():
    with pytest.raises(cleaner.NotADigestError):
        cleaner.clean(html("announcement.eml"))


def test_unknown_layout_with_content_raises_new_template():
    """nov26 content under headings no template knows -> possible new template."""
    redesigned = (html("nov2026.eml")
                  .replace("Summary", "At a glance")
                  .replace("Hey Vaultscapes,", "Morning Vaultscapes —"))
    with pytest.raises(cleaner.FormatDriftError) as err:
        cleaner.clean(redesigned)
    assert err.value.template is None
    assert err.value.fingerprint.is_content
    assert err.value.leads  # sections listed in the issue


def test_known_template_that_breaks_names_itself():
    broken = html("nov2026.eml").replace("Hey Vaultscapes,", "Morning —")
    with pytest.raises(cleaner.FormatDriftError) as err:
        cleaner.clean(broken)
    assert err.value.template == "nov2026"
    assert "intro section missing" in str(err.value)


@pytest.mark.parametrize("name", ["sample.eml", "nov2026.eml",
                                  "article-sunday.eml", "article-technical.eml"])
def test_known_sends_have_full_coverage(name):
    payload = cleaner.load_eml(FIXTURES / name)
    doc = feed_parser.parse(payload, cleaner.clean(payload.html),
                            LinkResolver(enabled=False))
    assert inspection.coverage_problems(doc) == []


def test_coverage_flags_partial_parse():
    payload = cleaner.load_eml(FIXTURES / "nov2026.eml")
    doc = feed_parser.parse(payload, cleaner.clean(payload.html),
                            LinkResolver(enabled=False))
    doc["news"][1]["body"] = ""
    doc["signals"][0]["stat"] = None
    gaps = inspection.coverage_problems(doc)
    assert any("news without body: news-2" in g for g in gaps)
    assert any("signals without stat" in g for g in gaps)
