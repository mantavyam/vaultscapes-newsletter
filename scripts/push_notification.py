"""Send an FCM topic push for the issue that was just published.

Runs only when the pipeline actually published something — a scheduled run
that finds no new email must not notify anyone.

Auth: FCM HTTP v1 requires a short-lived OAuth2 access token minted from a
service account. The legacy static server key was removed by Google in 2024,
so a bare `curl` with an API key does not work.

Env:
    FCM_SERVICE_ACCOUNT  service account JSON (GitHub Actions secret)
    FCM_TOPIC            topic name, defaults to `news-feed`
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests
from google.auth.transport.requests import Request
from google.oauth2 import service_account

from utils.helpers import DATA_DIR

SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
LATEST_FILE = DATA_DIR / "latest.json"
STAMP_FILE = Path(__file__).resolve().parent.parent / "state" / "pushed.json"


def _access_token(raw_credentials: str) -> tuple[str, str]:
    """(bearer token, project id) from the service account JSON."""
    info = json.loads(raw_credentials)
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=[SCOPE]
    )
    creds.refresh(Request())
    return creds.token, info["project_id"]


def _already_pushed(iso_date: str) -> bool:
    """Guard against the retry window notifying twice for one issue."""
    if not STAMP_FILE.exists():
        return False
    try:
        return json.loads(STAMP_FILE.read_text()).get("last_pushed") == iso_date
    except json.JSONDecodeError:
        return False


def _record_pushed(iso_date: str) -> None:
    STAMP_FILE.parent.mkdir(parents=True, exist_ok=True)
    STAMP_FILE.write_text(
        json.dumps({"last_pushed": iso_date}, indent=2) + "\n", encoding="utf-8"
    )


def main() -> int:
    raw = os.environ.get("FCM_SERVICE_ACCOUNT")
    if not raw:
        print("FCM_SERVICE_ACCOUNT not set — skipping push.")
        return 0

    if not LATEST_FILE.exists():
        print("No latest.json — nothing to announce.")
        return 0

    issue = json.loads(LATEST_FILE.read_text(encoding="utf-8"))
    iso_date = issue.get("iso_date", "")

    if _already_pushed(iso_date):
        print(f"Already pushed {iso_date} — skipping.")
        return 0

    is_article = issue.get("type") == "article"
    headline = (issue.get("title") or issue.get("subject") or "New issue").strip()
    title = f"📖 {issue.get('kicker', 'Deep Dive')}" if is_article else "Your daily AI intelligence briefing has landed."

    token, project_id = _access_token(raw)
    topic = os.environ.get("FCM_TOPIC", "news-feed")

    message = {
        "message": {
            "topic": topic,
            "notification": {"title": title, "body": headline},
            # Mirrored into data so a foreground handler can route the tap to
            # the exact issue rather than just opening the app.
            "data": {
                "iso_date": iso_date,
                "issue_type": issue.get("type", "digest"),
            },
            "android": {
                "priority": "high",
                "notification": {
                    "channel_id": "vaultscapes_breakthrough",
                    # Collapse to one notification per issue if several land.
                    "tag": f"issue-{iso_date}",
                },
            },
        }
    }

    response = requests.post(
        f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; UTF-8",
        },
        json=message,
        timeout=30,
    )

    if response.status_code != 200:
        print(f"FCM push failed: {response.status_code} {response.text}",
              file=sys.stderr)
        # Non-fatal: the issue is published and the app's poll will still find
        # it. Failing the job here would bury a successful publish.
        return 0

    print(f"Pushed {iso_date} to /topics/{topic}: {title} — {headline}")
    _record_pushed(iso_date)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
