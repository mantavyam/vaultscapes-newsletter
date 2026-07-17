"""Publish: write dated artifacts, latest.json, index.json, and update state.

Output layout (all under data/):
    data/<YYYY>/<MM-MonthName>/<DD-MM-YYYY>.json     one issue's payload
    data/<YYYY>/<MM-MonthName>/html/<DD-MM-YYYY>.html cleaned HTML audit artifact
    data/latest.json                                  copy of the newest payload
    data/index.json                                   manifest (newest first) with
                                                      absolute raw URLs so the app
                                                      resolves latest + history

The manifest is what the Flutter app's Search / Journal Navigation consumes;
raw.githubusercontent.com cannot list directories, so this file is the only
way the app discovers history.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from utils.helpers import (
    DATA_DIR,
    STATE_FILE,
    issue_date_ist,
    issue_paths,
    issue_repo_paths,
    raw_base_url,
)

INDEX_FILE = DATA_DIR / "index.json"
LATEST_FILE = DATA_DIR / "latest.json"
MAX_INDEX_HEADLINES = 5


def publish_issue(payload_json: dict, cleaned_html: str, message_id: str,
                  date_header: str) -> None:
    dt = issue_date_ist(date_header)
    paths = issue_paths(dt)
    repo_paths = issue_repo_paths(dt)
    base = raw_base_url()

    # 1. dated artifacts
    paths["json"].parent.mkdir(parents=True, exist_ok=True)
    paths["html"].parent.mkdir(parents=True, exist_ok=True)
    paths["json"].write_text(
        json.dumps(payload_json, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    paths["html"].write_text(cleaned_html, encoding="utf-8")

    # 2. index.json (manifest, newest first)
    index = {"updated_at": "", "latest_url": "", "issues": []}
    if INDEX_FILE.exists():
        index = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    entry = {
        "date": payload_json["date"],
        "iso_date": payload_json["iso_date"],
        "subject": payload_json["subject"],
        "path": repo_paths["json"],
        "json_url": f"{base}/{repo_paths['json']}",
        "html_url": f"{base}/{repo_paths['html']}",
        "headlines": [n["headline"] for n in payload_json["news"]][:MAX_INDEX_HEADLINES],
    }
    issues = [i for i in index.get("issues", []) if i["iso_date"] != entry["iso_date"]]
    issues.append(entry)
    issues.sort(key=lambda i: i["iso_date"], reverse=True)
    index = {
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "latest_url": f"{base}/data/latest.json",
        "issues": issues,
    }
    INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    INDEX_FILE.write_text(
        json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    # 3. latest.json — only if this issue is (or ties) the newest
    if issues and issues[0]["iso_date"] == entry["iso_date"]:
        LATEST_FILE.write_text(
            json.dumps(payload_json, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    # 4. state
    state = {"message_ids": []}
    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    if message_id and message_id not in state["message_ids"]:
        state["message_ids"].append(message_id)
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(f"published {repo_paths['json']} (+html, index.json, latest.json)")
