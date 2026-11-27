"""Alert issues + Discord mirroring (no network, no gh)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import alerts  # noqa: E402


@pytest.fixture
def actions(monkeypatch, tmp_path):
    """Pretend to be in GitHub Actions; record gh calls and Discord posts."""
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GH_TOKEN", "x")
    monkeypatch.setattr(alerts, "_FILED", tmp_path / "filed.txt")
    calls, posts, open_issues = [], [], []

    def fake_gh(*args):
        calls.append(args)
        if args[:2] == ("issue", "list"):
            return json.dumps(open_issues)
        if args[:2] in (("issue", "create"), ("issue", "comment")):
            return "https://github.com/o/r/issues/1\n"
        return ""

    monkeypatch.setattr(alerts, "gh", fake_gh)
    monkeypatch.setattr(alerts, "_post", posts.append)
    return calls, posts, open_issues


def test_opens_new_issue_with_important_label(actions):
    calls, posts, _ = actions
    alerts.open_issue("new-template", "Format changed", "details")
    create = next(c for c in calls if c[:2] == ("issue", "create"))
    assert "new-template" in create and "important" in create
    assert posts and posts[0].startswith("## Issue opened: Format changed")


def test_repeat_comments_on_open_issue(actions):
    calls, posts, open_issues = actions
    open_issues.append({"number": 7, "title": "Format changed"})
    alerts.open_issue("new-template", "Format changed", "again")
    assert any(c[:3] == ("issue", "comment", "7") for c in calls)
    assert not any(c[:2] == ("issue", "create") for c in calls)
    assert posts[0].startswith("## Issue updated")


def test_close_issues_alerts_each(actions):
    calls, posts, open_issues = actions
    open_issues.append({"number": 3, "title": "t", "url": "u"})
    alerts.close_issues("run-failed", "recovered")
    assert ("issue", "close", "3", "--comment", "recovered") in calls
    assert posts[0].startswith("## Issue resolved")


def test_run_status_skips_generic_when_specific_filed(actions):
    calls, _, _ = actions
    alerts.open_issue("new-template", "Format changed", "x")
    calls.clear()
    alerts.run_status("failure")
    assert not any(c[:2] == ("issue", "create") for c in calls)


def test_run_status_opens_and_closes_run_failed(actions):
    calls, _, open_issues = actions
    alerts.run_status("failure")
    assert any(c[:2] == ("issue", "create") and "run-failed" in c for c in calls)
    open_issues.append({"number": 9, "title": "t", "url": "u"})
    alerts.run_status("success")
    assert ("issue", "close", "9", "--comment") == next(
        c for c in calls if c[:2] == ("issue", "close"))[:4]


def test_alert_text_fits_discord_limit():
    text = alerts.alert_text("Issue opened", "new-template", "t", "y" * 5000, "u")
    assert len(text) <= alerts.DISCORD_LIMIT
    assert text.endswith("[Open the issue](u)")


def test_local_run_files_nothing(monkeypatch, tmp_path):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(alerts, "_FILED", tmp_path / "f.txt")
    monkeypatch.setattr(alerts, "gh", lambda *a: pytest.fail("gh called locally"))
    alerts.open_issue("run-failed", "t", "b")
    alerts.close_issues("run-failed", "n")
