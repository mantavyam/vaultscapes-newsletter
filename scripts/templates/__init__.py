"""Template registry.

Each AlphaSignal email layout lives in its own module here. To support a new
layout:

    1. copy the closest module (e.g. nov2026.py) to a new file,
    2. adjust its markers / matches() / parse_* to the new markup,
    3. add an instance to TEMPLATES below (newest first),
    4. drop a sample .eml in tests/fixtures/ and add a test.

cleaner.py and parser.py need no changes.
"""

from __future__ import annotations

from bs4 import Tag

from .base import EmailTemplate
from .legacy import LegacyTemplate
from .nov2026 import Nov2026Template

# Newest first: detection takes the first template whose matches() is true.
TEMPLATES: tuple[EmailTemplate, ...] = (
    Nov2026Template(),
    LegacyTemplate(),
)


def detect(tables: list[Tag], texts: list[str]) -> EmailTemplate | None:
    """First template whose layout landmarks are present, else None.

    None is not decided here: the core asks inspection.fingerprint() whether
    the email is content (-> `new-template` issue) or promo (-> skip).
    """
    for template in TEMPLATES:
        if template.matches(tables, texts):
            return template
    return None


__all__ = ["EmailTemplate", "TEMPLATES", "detect"]
