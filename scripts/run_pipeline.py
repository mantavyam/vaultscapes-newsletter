"""Pipeline orchestrator: fetch -> clean -> parse -> publish.

Usage:
    python scripts/run_pipeline.py                 # IMAP fetch (cron / CI)
    python scripts/run_pipeline.py --eml FILE ...  # process local .eml file(s)
    python scripts/run_pipeline.py --no-resolve    # skip redirect resolution

Exit codes:
    0  success (including the no-new-email no-op)
    1  format drift or any hard failure — the offending HTML is saved to
       quarantine/ for post-mortem before exiting, so evidence survives
       even though nothing malformed reaches data/.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cleaner
import parser as feed_parser
import publish
from utils.helpers import ROOT, LinkResolver, load_env

QUARANTINE_DIR = ROOT / "quarantine"


def process_eml(path: Path, resolver: LinkResolver) -> None:
    payload = cleaner.load_eml(path)
    print(f"processing: {payload.subject[:70]} ({payload.message_id})")
    try:
        cleaned = cleaner.clean(payload.html)
        payload_json = feed_parser.parse(payload, cleaned, resolver)
    except cleaner.FormatDriftError:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
        (QUARANTINE_DIR / f"{stamp}-raw.html").write_text(
            payload.html, encoding="utf-8"
        )
        print(f"FORMAT DRIFT: raw HTML quarantined to quarantine/{stamp}-raw.html")
        raise
    publish.publish_issue(
        payload_json, cleaned.cleaned_html, payload.message_id, payload.date_header
    )


def main() -> int:
    argp = argparse.ArgumentParser(description=__doc__)
    argp.add_argument("--eml", nargs="*", type=Path,
                      help="process local .eml file(s) instead of fetching via IMAP")
    argp.add_argument("--no-resolve", action="store_true",
                      help="keep tracking URLs instead of resolving redirects")
    args = argp.parse_args()

    load_env()
    resolver = LinkResolver(enabled=not args.no_resolve)

    if args.eml:
        paths = args.eml
    else:
        import fetch_email
        from utils.helpers import env

        address = env("GMAIL_ADDRESS")
        password = env("GMAIL_APP_PASSWORD")
        if not address or not password:
            print("GMAIL_ADDRESS / GMAIL_APP_PASSWORD not set", file=sys.stderr)
            return 1
        paths = fetch_email.fetch_new(address, password)
        if not paths:
            print("No new newsletter emails — nothing to do.")
            return 0

    for path in paths:
        process_eml(path, resolver)
    print(f"done: {len(paths)} issue(s) published")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
