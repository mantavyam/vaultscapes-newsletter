"""Pipeline orchestrator: fetch -> clean -> parse -> publish.

Usage:
    python scripts/run_pipeline.py                 # IMAP fetch (cron / CI)
    python scripts/run_pipeline.py --eml FILE ...  # process local .eml file(s)
    python scripts/run_pipeline.py --no-resolve    # skip redirect resolution

Exit codes:
    0  success (including the no-new-email no-op)
    1  an email looked like newsletter content but no template parsed it
       (possible new template): its .eml is saved to quarantine/ and a
       `new-template` issue is opened; other emails still publish.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import alerts
import cleaner
import inspection
import parser as feed_parser
import publish
from utils.helpers import ROOT, LinkResolver, env, load_env

QUARANTINE_DIR = ROOT / "quarantine"
# AlphaSignal skips some weekends/holidays; longer silence means trouble.
DEFAULT_STALE_DAYS = 4


def process_eml(path: Path, resolver: LinkResolver) -> dict | None:
    """Publish one issue. Returns its payload, or None when the email was skipped."""
    payload = cleaner.load_eml(path)
    print(f"processing: {payload.subject[:70]} ({payload.message_id})")
    try:
        cleaned = cleaner.clean(payload.html)
        payload_json = feed_parser.parse(payload, cleaned, resolver)
    except cleaner.NotADigestError as exc:
        # Sponsored one-offs share the sender but carry no digest content.
        # Record them so they aren't re-fetched, and move on.
        print(f"  skipped: {exc}")
        publish.mark_processed(payload.message_id)
        return None
    except cleaner.FormatDriftError as exc:
        report_new_template(path, payload, exc)
        raise
    entry = publish.publish_issue(
        payload_json, cleaned.cleaned_html, payload.message_id, payload.date_header
    )
    gaps = inspection.coverage_problems(payload_json)
    if gaps:
        # A known template "parsed" it but left fields empty: the layout has
        # probably changed under it. Published anyway; flagged for review.
        report_new_template(path, payload, None, gaps, cleaned.template.name,
                            entry["json_url"])
    return payload_json


def report_new_template(path: Path, payload, exc: cleaner.FormatDriftError | None,
                        gaps: list[str] | None = None, template: str | None = None,
                        published_url: str | None = None) -> None:
    """Keep the exact .eml (a template is written from it) and open/comment the
    `new-template` issue."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
    saved = f"quarantine/{stamp}.eml"
    shutil.copyfile(path, ROOT / saved)
    print(f"POSSIBLE NEW TEMPLATE: email saved to {saved}")

    lines = [
        f"**Email:** {payload.subject}",
        f"**Date:** {payload.date_header}",
        f"**Message-ID:** `{payload.message_id}`",
        f"**Saved .eml:** `{saved}` (add it to `format/` + `tests/fixtures/` "
        "and write a template in `scripts/templates/` from it)",
        "",
    ]
    if exc is not None:
        matched = exc.template or "none"
        lines += [
            f"**Matched template:** {matched}",
            f"**Why:** {exc}",
            "**Status:** not published. The email is not marked processed, so the "
            "first run after the template lands publishes it (keep it inside "
            "`LOOKBACK_DAYS`).",
        ]
        fp, leads = exc.fingerprint, exc.leads
    else:
        lines += [
            f"**Matched template:** {template}",
            "**Why:** parsed, but fields a correct parse always fills are empty:",
            *[f"- {g}" for g in gaps or []],
            f"**Status:** published with gaps: {published_url}",
        ]
        fp, leads = None, []
    if fp is not None:
        lines += ["", "**Why it looks like newsletter content:** "
                  + (", ".join(fp.reasons) or "weak signals"),
                  f"`{fp.summary_line()}`"]
    if leads:
        lines += ["", "**Top-level sections seen:**", "```",
                  *[f"{i:>2} {t}" for i, t in enumerate(leads)], "```"]
    lines += ["", f"Run: {alerts.run_link()}"]
    alerts.open_issue("new-template", "Possible new AlphaSignal email template",
                      "\n".join(lines))


def main() -> int:
    argp = argparse.ArgumentParser(description=__doc__)
    argp.add_argument("--eml", nargs="*", type=Path,
                      help="process local .eml file(s) instead of fetching via IMAP")
    argp.add_argument("--no-resolve", action="store_true",
                      help="keep tracking URLs instead of resolving redirects")
    args = argp.parse_args()

    load_env()
    alerts.reset_run()
    resolver = LinkResolver(enabled=not args.no_resolve)

    if args.eml:
        paths = args.eml
    else:
        import fetch_email

        address = env("GMAIL_ADDRESS")
        password = env("GMAIL_APP_PASSWORD")
        if not address or not password:
            print("GMAIL_ADDRESS / GMAIL_APP_PASSWORD not set", file=sys.stderr)
            return 1
        paths = fetch_email.fetch_new(address, password)
        if not paths:
            print("No new newsletter emails — nothing to do.")
            check_stale()
            return 0

    # One drifted email must not block the rest of the queue: keep going,
    # then fail the run so the quarantined evidence still raises the alarm.
    published = skipped = failed = 0
    for path in paths:
        try:
            if process_eml(path, resolver) is not None:
                published += 1
            else:
                skipped += 1
        except cleaner.FormatDriftError as exc:
            print(f"  failed: {exc}", file=sys.stderr)
            failed += 1
    print(f"done: {published} issue(s) published, {skipped} skipped, {failed} failed")
    if published:
        alerts.close_issues("no-new-issues", f"Published {published} issue(s): {alerts.run_link()}")
        if not failed:
            alerts.close_issues("new-template",
                                f"Every fetched email parsed cleanly: {alerts.run_link()}")
    else:
        check_stale()
    return 1 if failed else 0


def check_stale() -> None:
    """Open `no-new-issues` when nothing has been published for STALE_DAYS."""
    days = int(env("STALE_DAYS") or DEFAULT_STALE_DAYS)
    latest = publish.latest_iso_date()
    if latest is None:
        return
    age = (datetime.now(timezone.utc).date() - datetime.fromisoformat(latest).date()).days
    if age > days:
        alerts.open_issue(
            "no-new-issues", f"No new AlphaSignal issue for {age} days",
            f"Latest published issue: **{latest}** ({age} days ago, threshold {days}).\n\n"
            f"Run: {alerts.run_link()}\n\nCheck the Gmail inbox still receives "
            f"news@alphasignal.ai, the subscription is active, and LOOKBACK_DAYS.",
        )


if __name__ == "__main__":
    raise SystemExit(main())
