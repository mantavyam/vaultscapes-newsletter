"""Fetch AlphaSignal newsletter emails from Gmail over IMAP.

Auth: GMAIL_ADDRESS + GMAIL_APP_PASSWORD (Google app password; requires 2FA).
Dedup: RFC-2822 Message-ID header checked against state/processed.json —
IMAP UIDs are mailbox-local and reset with UIDVALIDITY, so they are never
used as the dedup key.

Saves each new message as work/incoming/<n>.eml (oldest first) for the
downstream cleaner/parser stages.
"""

from __future__ import annotations

import email
import imaplib
import json
from datetime import datetime, timedelta, timezone
from email import policy
from pathlib import Path

from utils import markers
from utils.helpers import STATE_FILE, WORK_DIR, env, load_env

INCOMING_DIR = WORK_DIR / "incoming"
LOOKBACK_DAYS = 3  # search window; state file makes reruns idempotent


def load_processed() -> set[str]:
    if STATE_FILE.exists():
        return set(json.loads(STATE_FILE.read_text()).get("message_ids", []))
    return set()


def fetch_new(address: str, app_password: str,
              sender: str = markers.SENDER_ADDRESS) -> list[Path]:
    """Download unprocessed newsletter emails; return saved .eml paths (oldest first)."""
    processed = load_processed()
    since = (datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).strftime("%d-%b-%Y")

    INCOMING_DIR.mkdir(parents=True, exist_ok=True)
    for stale in INCOMING_DIR.glob("*.eml"):
        stale.unlink()

    saved: list[tuple[datetime, Path]] = []
    with imaplib.IMAP4_SSL("imap.gmail.com") as imap:
        imap.login(address, app_password)
        imap.select("INBOX", readonly=True)
        status, data = imap.search(None, f'(FROM "{sender}" SINCE {since})')
        if status != "OK":
            raise RuntimeError(f"IMAP search failed: {status}")
        ids = data[0].split()
        print(f"IMAP: {len(ids)} message(s) from {sender} since {since}")

        for num in ids:
            status, msg_data = imap.fetch(num, "(RFC822)")
            if status != "OK":
                print(f"  warn: fetch failed for message {num!r}, skipping")
                continue
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw, policy=policy.default)
            message_id = msg.get("Message-ID", "").strip()
            if not message_id:
                print(f"  warn: message {num!r} has no Message-ID, skipping")
                continue
            if message_id in processed:
                continue
            dt = email.utils.parsedate_to_datetime(msg.get("Date"))
            path = INCOMING_DIR / f"{num.decode()}.eml"
            path.write_bytes(raw)
            saved.append((dt, path))
            print(f"  new: {message_id} ({msg.get('Subject', '')[:60]})")

    saved.sort(key=lambda pair: pair[0])
    return [path for _, path in saved]


def main() -> int:
    load_env()
    address = env("GMAIL_ADDRESS")
    password = env("GMAIL_APP_PASSWORD")
    if not address or not password:
        raise SystemExit("GMAIL_ADDRESS / GMAIL_APP_PASSWORD not set (see .env.example)")
    paths = fetch_new(address, password)
    print(f"{len(paths)} new email(s) saved to {INCOMING_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
