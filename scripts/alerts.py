"""GitHub issues for everything that needs attention, each mirrored to Discord.

One open issue per label: a repeat of the same problem is a comment on the
open issue, not a new one. Every open, comment and automatic close is also
posted to DISCORD_WEBHOOK_URL (issues opened by the workflow's own token do not
trigger other workflows, so the pipeline posts the alert itself).

Labels (IMPORTANT ones also get the `important` label):
  new-template    important  an email looks like newsletter content (inspection.py)
                             but no template parsed it, or a template left
                             fields empty; exact .eml in quarantine/
                                                               closes after a clean run
  run-failed      important  the workflow failed for any other reason (IMAP
                             login, crash, test gate)          closes after a clean run
  no-new-issues   important  nothing published for STALE_DAYS  closes when one is published
  push-failed                the FCM notification was not delivered
                                                               closes after a delivered push

Environment: GH_TOKEN + GITHUB_ACTIONS (issues are filed only in Actions),
DISCORD_WEBHOOK_URL (optional; without it nothing is posted).

CLI (last workflow step):  python scripts/alerts.py run-status
    with JOB_STATUS=${{ job.status }}
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import requests

IMPORTANT = {"new-template", "run-failed", "no-new-issues"}
DISCORD_LIMIT = 2000

# Labels filed during this run, so the final run-status step doesn't open a
# generic `run-failed` on top of a specific issue that already explains it.
_FILED = Path(__file__).resolve().parent.parent / "work" / "alerts-filed.txt"


def gh(*args: str) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True,
                          text=True).stdout


def can_file_issues() -> bool:
    return bool(os.environ.get("GITHUB_ACTIONS") and os.environ.get("GH_TOKEN"))


def run_link() -> str:
    if os.environ.get("GITHUB_RUN_ID"):
        return (f"{os.environ['GITHUB_SERVER_URL']}/{os.environ['GITHUB_REPOSITORY']}"
                f"/actions/runs/{os.environ['GITHUB_RUN_ID']}")
    return "local run"


# ---------------------------------------------------------------------------
# Discord
# ---------------------------------------------------------------------------

def _post(content: str) -> None:
    """Post to Discord; never fails the run."""
    hook = os.environ.get("DISCORD_WEBHOOK_URL")
    if not hook:
        return
    try:
        # flags 4 = SUPPRESS_EMBEDS: no link previews
        requests.post(hook, json={"content": content[:DISCORD_LIMIT], "flags": 4},
                      timeout=15).raise_for_status()
    except requests.RequestException as exc:
        print(f"! could not post to Discord: {type(exc).__name__}", file=sys.stderr)


def alert_text(event: str, label: str, title: str, body: str, url: str | None) -> str:
    """Heading, label line, the issue text (shortened), a link to the issue."""
    flag = "**Important** · " if label in IMPORTANT else ""
    head = [f"## {event}: {title}", f"{flag}`{label}`", ""]
    tail = ["", f"[Open the issue]({url})"] if url else []
    room = DISCORD_LIMIT - len("\n".join(head + tail)) - 2
    text = body if len(body) <= room else body[:room - 1].rstrip() + "…"
    return "\n".join(head + [text] + tail)


def alert(event: str, label: str, title: str, body: str, url: str | None = None) -> None:
    _post(alert_text(event, label, title, body, url))


# ---------------------------------------------------------------------------
# GitHub issues
# ---------------------------------------------------------------------------

def annotate(label: str, title: str, body: str) -> None:
    """Show the problem on the run's summary page too."""
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    first = next((ln.strip("-* ").strip() for ln in body.splitlines() if ln.strip()), "")

    def esc(t: str) -> str:
        return (t.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
                .replace(":", "%3A").replace(",", "%2C"))

    level = "error" if label in IMPORTANT else "warning"
    print(f"::{level} title={esc(f'{label}: {title}')}::{first.replace('%', '%25')[:400]}",
          flush=True)


def _record_filed(label: str) -> None:
    _FILED.parent.mkdir(parents=True, exist_ok=True)
    with _FILED.open("a", encoding="utf-8") as f:
        f.write(label + "\n")


def reset_run() -> None:
    _FILED.unlink(missing_ok=True)


def filed_this_run() -> set[str]:
    if not _FILED.exists():
        return set()
    return set(_FILED.read_text(encoding="utf-8").split())


def open_issue(label: str, title: str, body: str) -> None:
    """Open an issue, or comment on the open one with this label; alert Discord."""
    annotate(label, title, body)
    _record_filed(label)
    if not can_file_issues():
        print(f"! {title} (local run, no issue filed)\n{body}", file=sys.stderr)
        return
    try:
        gh("label", "create", label, "--color",
           "d73a4a" if label in IMPORTANT else "fbca04",
           "--description", "Newsletter pipeline alert", "--force")
        labels = ["--label", label]
        if label in IMPORTANT:
            gh("label", "create", "important", "--color", "b60205",
               "--description", "Needs attention", "--force")
            labels += ["--label", "important"]
        found = json.loads(gh("issue", "list", "--label", label, "--state", "open",
                              "--json", "number,title", "--limit", "1"))
        if found:
            url = gh("issue", "comment", str(found[0]["number"]), "--body", body).strip()
            alert("Issue updated", label, found[0]["title"], body, url)
        else:
            url = gh("issue", "create", "--title", title, *labels, "--body", body).strip()
            alert("Issue opened", label, title, body, url)
    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"! could not file issue: {exc}", file=sys.stderr)
        alert("Issue not filed", label, title, body)  # Discord still hears about it


def close_issues(label: str, note: str) -> None:
    """Close the open issues with this label (problem went away); alert Discord."""
    if not can_file_issues():
        return
    try:
        issues = json.loads(gh("issue", "list", "--label", label, "--state", "open",
                               "--json", "number,title,url"))
        for issue in issues:
            gh("issue", "close", str(issue["number"]), "--comment", note)
            alert("Issue resolved", label, issue["title"], note, issue["url"])
    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"! could not close issues: {exc}", file=sys.stderr)


def run_status(job_status: str) -> None:
    """Last workflow step: generic `run-failed`, or close it after a clean run."""
    if job_status in ("failure", "cancelled"):
        specific = filed_this_run() & (IMPORTANT - {"run-failed"})
        if specific:
            print(f"run failed; already reported as: {', '.join(sorted(specific))}")
            return
        open_issue("run-failed", "Newsletter pipeline run failed",
                   f"The workflow ended with status `{job_status}`.\n\nRun: {run_link()}\n\n"
                   "Open the run for the error (IMAP login, test gate, crash). The next "
                   "scheduled run retries every email not yet in state/processed.json.")
    elif job_status == "success":
        close_issues("run-failed", f"The next run went through: {run_link()}")


if __name__ == "__main__":
    if sys.argv[1:] == ["run-status"]:
        run_status(os.environ.get("JOB_STATUS", ""))
    else:
        sys.exit("usage: python scripts/alerts.py run-status")
