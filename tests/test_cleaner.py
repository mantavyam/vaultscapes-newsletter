"""Cleaner regression tests against the checked-in fixture .eml."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import cleaner  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "sample.eml"


@pytest.fixture(scope="module")
def payload():
    return cleaner.load_eml(FIXTURE)


@pytest.fixture(scope="module")
def result(payload):
    return cleaner.clean(payload.html)


def test_eml_metadata(payload):
    assert payload.message_id.startswith("<") and payload.message_id.endswith(">")
    assert "Anthropic" in payload.subject
    assert payload.date_header


def test_section_kinds(result):
    kinds = [s.kind for s in result.sections]
    assert kinds.count("intro") == 1
    assert kinds.count("summary") == 1
    assert kinds.count("signals") == 1
    assert kinds.count("news") == 3


def test_no_sponsor_content_survives(result):
    html = result.cleaned_html.lower()
    for junk in (
        "presented by",
        "partner with us",
        "in partnership with",
        "orkes",
        "vanta",
        "ngrok",
    ):
        assert junk not in html, f"sponsor marker leaked: {junk}"


def test_no_footer_or_header_junk(result):
    html = result.cleaned_html.lower()
    for junk in (
        "unsubscribe",
        "how was today's email",
        "work with us",
        "at alpha signal, our mission",
        "today's author",
    ):
        assert junk not in html, f"junk marker leaked: {junk}"


def test_no_tracking_pixel(result):
    assert "app.alphasignal.ai/o?" not in result.cleaned_html


def test_content_preserved(result):
    html = result.cleaned_html
    assert "Blender" in html            # news 1
    assert "309,815 real conversations" in html  # news 2
    assert "744 billion parameter" in html       # news 3
    assert "Prefect" in html            # signal 3 (kept)


def test_format_drift_raises():
    with pytest.raises(cleaner.FormatDriftError):
        cleaner.clean("<html><body><p>totally different layout</p></body></html>")
