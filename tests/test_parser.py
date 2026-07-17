"""Parser regression tests: full pipeline (offline) against the fixture .eml."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import cleaner  # noqa: E402
import parser as feed_parser  # noqa: E402
from utils.helpers import LinkResolver  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "sample.eml"


@pytest.fixture(scope="module")
def doc():
    payload = cleaner.load_eml(FIXTURE)
    cleaned = cleaner.clean(payload.html)
    return feed_parser.parse(payload, cleaned, LinkResolver(enabled=False))


def test_metadata(doc):
    assert doc["version"] == 1
    assert doc["date"] == "14-07-2026"          # Date header 14:33 UTC -> 20:03 IST same day
    assert doc["iso_date"] == "2026-07-14"
    assert doc["read_time"] == "6 min 55 sec"
    assert doc["intro"].startswith("Today is an Anthropic day")
    assert "In Partnership" not in doc["intro"]


def test_summary(doc):
    assert len(doc["summary"]) == 3
    categories = [s["category"] for s in doc["summary"]]
    assert categories == ["Top Repo", "Top News", "Top Repo"]
    # every outline entry links to a full news block
    news_ids = {n["id"] for n in doc["news"]}
    for entry in doc["summary"]:
        assert entry["news_id"] in news_ids


def test_news_blocks(doc):
    assert len(doc["news"]) == 3
    n1, n2, n3 = doc["news"]

    assert n1["likes"] == 6185
    assert n1["category"] == "Top Repo"
    assert n1["headline"].startswith("GPT-4o in Cursor")
    assert len(n1["bullets"]) == 4
    assert n1["image_url"] and "alphasignal.ai/image/" in n1["image_url"]
    assert n1["read_more_url"]

    assert n2["likes"] == 3666
    assert "309,815 real conversations" in n2["body"]

    assert n3["likes"] == 2242
    assert n3["headline"].endswith("no GPU")


def test_signals_sponsor_dropped_and_renumbered(doc):
    signals = doc["signals"]
    assert len(signals) == 5                     # 6 in email, ngrok ad dropped
    assert [s["rank"] for s in signals] == [1, 2, 3, 4, 5]
    headlines = " ".join(s["headline"] for s in signals).lower()
    assert "ngrok" not in headlines

    assert signals[0]["stat"] == {"type": "likes", "value": 2022}
    assert signals[1]["stat"] == {"type": "stars", "value": 23314}
    assert signals[3]["stat"] == {"type": "downloads", "value": 879}
    for s in signals:
        assert s["url"], f"signal #{s['rank']} lost its link"


def test_no_sponsor_leak_anywhere(doc):
    import json

    blob = json.dumps(doc).lower()
    for junk in ("presented by", "orkes", "vanta", "ngrok", "partner with us"):
        assert junk not in blob, f"sponsor leaked into JSON: {junk}"
