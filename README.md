# Vaultscapes News Feed — AlphaSignal Newsletter Automation

Automated pipeline that turns the daily [AlphaSignal](https://alphasignal.ai) newsletter
email into clean, structured JSON hosted on GitHub — the data source for the Vaultscapes
app's native AI news feed (replacing the legacy WebView).

```
AlphaSignal email → Gmail → [cron: GitHub Actions]
  → fetch_email.py   (IMAP, dedup by Message-ID)
  → cleaner.py       (strip ads/sponsors/footer → cleaned HTML artifact)
  → parser.py        (marker-driven → versioned JSON: summary / news / signals)
  → publish.py       (dated files + latest.json + index.json manifest)
  → git commit & push → app fetches via raw.githubusercontent.com
```

## Repository layout

```
data/
├── latest.json               # newest issue — the app's primary fetch
├── index.json                # manifest (newest first) with absolute raw URLs;
│                             # powers latest + date-wise history resolution
└── 2026/
    └── 07-July/
        ├── 14-07-2026.json   # one issue, schema below
        └── html/
            └── 14-07-2026.html  # cleaned HTML (audit artifact, kept forever)
scripts/                      # the pipeline (see docstrings)
tests/                        # regression tests against tests/fixtures/sample.eml
state/processed.json          # published Gmail Message-IDs (idempotency)
quarantine/                   # raw HTML of issues that failed parsing (evidence)
```

## Setup

1. **Push this folder to its own GitHub repo** (e.g. `vaultscapes-news-feed`).
2. **Gmail app password**: Google Account → Security → 2-Step Verification →
   App passwords. Requires 2FA enabled.
3. **GitHub Secrets** (repo → Settings → Secrets and variables → Actions):
   - `GMAIL_ADDRESS` — the Gmail address receiving AlphaSignal
   - `GMAIL_APP_PASSWORD` — the app password
4. Done. The workflow (`.github/workflows/fetch-newsletter.yml`) runs weekdays at
   15:00 and 18:00 UTC (second run is an idempotent retry), or trigger manually via
   *Actions → Fetch AlphaSignal Newsletter → Run workflow*.

> **Security note:** a Gmail app password grants full IMAP access to the account,
> not a read-only scope. Keep the repo's collaborator list tight, and revoke/rotate
> the app password from Google Account settings if that ever changes. For a shared
> or team setup, migrate to the Gmail API with OAuth `gmail.readonly` scope.

## Local development

```bash
python3 -m venv work/venv && work/venv/bin/pip install -r requirements.txt
cp .env.example .env                 # fill in FEED_GITHUB_REPO (+ Gmail creds for live fetch)

# run the full pipeline on the checked-in fixture (offline, no Gmail needed):
work/venv/bin/python scripts/run_pipeline.py --eml tests/fixtures/sample.eml --no-resolve

# run tests:
work/venv/bin/python -m pytest tests/ -q

# live fetch from Gmail:
work/venv/bin/python scripts/run_pipeline.py
```

`.env` keys (see `.env.example`):

| Key | Purpose |
|---|---|
| `FEED_GITHUB_REPO` | `owner/name` of this repo — builds the absolute raw URLs written into `index.json` (`latest_url`, per-issue `json_url`/`html_url`) that the app uses for latest + history resolution. In CI this falls back to `GITHUB_REPOSITORY` automatically. |
| `FEED_GITHUB_BRANCH` | branch for raw URLs (default `main`) |
| `FEED_RAW_BASE` | optional explicit base-URL override |
| `GMAIL_ADDRESS` / `GMAIL_APP_PASSWORD` | local live fetch only; CI uses Secrets |

## JSON schema (version 1)

```jsonc
{
  "version": 1,
  "date": "14-07-2026",          // DD-MM-YYYY, IST
  "iso_date": "2026-07-14",      // for sorting
  "subject": "…email subject…",
  "intro": "…editorial intro paragraph…",
  "read_time": "6 min 55 sec",
  "summary": [                    // outline; links to full blocks below
    { "category": "Top Repo", "headline": "…", "news_id": "news-1" }
  ],
  "news": [                       // full blocks; sponsors removed
    {
      "id": "news-1",
      "category": "Top Repo",     // "Top News", "Top Repo", …
      "headline": "…",
      "likes": 6185,
      "body": "…paragraphs…",
      "bullets": ["…", "…"],
      "image_url": "https://alphasignal.ai/image/….png",
      "read_more_url": "https://…resolved final URL…"
    }
  ],
  "signals": [                    // sponsored entries dropped, ranks renumbered
    {
      "rank": 1,
      "headline": "…",
      "stat": { "type": "likes", "value": 2022 },   // likes | stars | downloads
      "url": "https://…resolved final URL…"
    }
  ]
}
```

App consumption:

- **Latest issue**: `GET <raw-base>/data/latest.json`
- **History / search**: `GET <raw-base>/data/index.json` → `issues[]` has
  `iso_date`, `subject`, `headlines[]` (for date-wise headline lists) and
  `json_url` to fetch any past issue.
- `raw.githubusercontent.com` CDN caches ~5 minutes — fine for a daily feed.
- Hard-fail on unknown `version` values instead of guessing.

## Cleaning rules (what gets removed)

Marker-driven (the email is ~70 nested tables with no usable CSS classes; all
markers live in `scripts/utils/markers.py`):

- header nav (Signup / Work With Us / Follow on X / Archive) and logo
- "In Partnership with" banner and "Today's Author" card
- "Presented by …" sponsor blocks between news items
- sponsored Signals entries (detected via "Presented by" in the full list and
  the `N. Name:` pattern in the summary preview) — ranks renumbered
- footer: mission statement, privacy text, WORK WITH US, feedback poll, unsubscribe
- open-tracking pixel; click-tracking links resolved to their final destinations

## Failure behaviour

- **No new email** (weekend/holiday): pipeline exits 0, no commit, no noise.
- **Format drift** (AlphaSignal changes their template): validation fails, the raw
  HTML is committed to `quarantine/`, the workflow goes red and GitHub emails the
  owner. `data/latest.json` is untouched — the app keeps serving the last good issue.
- **Duplicate run**: `state/processed.json` (Message-ID keyed) makes reruns no-ops.
