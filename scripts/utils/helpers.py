"""Shared helpers: environment/config, date handling, link resolution, paths."""

from __future__ import annotations

import email
import email.utils
import os
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from dotenv import load_dotenv
except ImportError:  # dotenv is optional in CI where env vars come from the workflow
    load_dotenv = None

from . import markers

# Repo root = two levels above this file (scripts/utils/helpers.py)
ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT / "data"
STATE_FILE = ROOT / "state" / "processed.json"
WORK_DIR = ROOT / "work"

IST = ZoneInfo("Asia/Kolkata")

_MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def load_env() -> None:
    """Load .env from the repo root if python-dotenv is installed and the file exists."""
    if load_dotenv is not None:
        load_dotenv(ROOT / ".env")


def env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)


def raw_base_url() -> str:
    """Absolute raw.githubusercontent.com base for this feed repo.

    Resolution order:
    1. FEED_RAW_BASE (explicit override)
    2. FEED_GITHUB_REPO + FEED_GITHUB_BRANCH ("owner/name" + branch)
    3. GITHUB_REPOSITORY (set automatically inside GitHub Actions)
    """
    override = env("FEED_RAW_BASE")
    if override:
        return override.rstrip("/")
    repo = env("FEED_GITHUB_REPO") or env("GITHUB_REPOSITORY")
    if not repo:
        raise RuntimeError(
            "Cannot resolve feed repo URL: set FEED_RAW_BASE or FEED_GITHUB_REPO in .env"
        )
    branch = env("FEED_GITHUB_BRANCH", "main")
    return f"https://raw.githubusercontent.com/{repo}/{branch}"


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------

def issue_date_ist(date_header: str) -> datetime:
    """RFC-2822 Date header -> timezone-aware datetime in IST."""
    dt = email.utils.parsedate_to_datetime(date_header)
    return dt.astimezone(IST)


def ddmmyyyy(dt: datetime) -> str:
    return dt.strftime("%d-%m-%Y")


def iso_date(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def month_folder(dt: datetime) -> str:
    """'07-July' — zero-padded number keeps chronological sort, name keeps readability."""
    return f"{dt.month:02d}-{_MONTH_NAMES[dt.month - 1]}"


def issue_paths(dt: datetime) -> dict[str, Path]:
    """Filesystem locations for one issue's artifacts."""
    folder = DATA_DIR / str(dt.year) / month_folder(dt)
    stem = ddmmyyyy(dt)
    return {
        "json": folder / f"{stem}.json",
        "html": folder / "html" / f"{stem}.html",
    }


def issue_repo_paths(dt: datetime) -> dict[str, str]:
    """Repo-relative POSIX paths (for index.json and raw URLs)."""
    folder = f"data/{dt.year}/{month_folder(dt)}"
    stem = ddmmyyyy(dt)
    return {
        "json": f"{folder}/{stem}.json",
        "html": f"{folder}/html/{stem}.html",
    }


# ---------------------------------------------------------------------------
# Text / link utilities
# ---------------------------------------------------------------------------

def squash_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def is_tracking_pixel(src: str) -> bool:
    return any(
        host in src and markers.TRACKING_PIXEL_PATH + "?" in src
        for host in markers.TRACKING_HOSTS
    )


def is_tracking_link(href: str) -> bool:
    return any(host in href for host in markers.TRACKING_HOSTS)


class LinkResolver:
    """Follows click-tracking redirects to the real destination URL.

    Caches within a run. On any failure, returns the original URL —
    a tracked link beats a dropped link.
    """

    _UA = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    )

    def __init__(self, enabled: bool = True, timeout: float = 10.0):
        self.enabled = enabled
        self.timeout = timeout
        self._cache: dict[str, str] = {}
        self._session = None

    def _get_session(self):
        if self._session is None:
            import requests

            self._session = requests.Session()
            self._session.headers["User-Agent"] = self._UA
        return self._session

    def resolve(self, url: str) -> str:
        if not self.enabled or not url or not is_tracking_link(url):
            return url
        if url in self._cache:
            return self._cache[url]
        final = url
        try:
            resp = self._get_session().get(
                url, allow_redirects=True, timeout=self.timeout, stream=True
            )
            final = resp.url
            resp.close()
        except Exception:
            pass  # keep the tracking URL rather than dropping the link
        self._cache[url] = final
        return final
