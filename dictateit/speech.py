"""Loading of speech data packs (locale templates + letter respellings)."""

from __future__ import annotations

import json
from pathlib import Path

DATA_DIR = Path(__file__).parent / "speech_data"


def load_pack(locale: str = "en_uk") -> tuple[dict, dict]:
    """Return (pack, letters) for a locale.

    pack    the locale JSON (punctuation words, math templates, greek, ...)
    letters base phonetic respellings, overridden by the locale's own entries
    """
    locale_file = DATA_DIR / f"{locale}.json"
    if not locale_file.exists():
        locale_file = DATA_DIR / "en_uk.json"
    pack = json.loads(locale_file.read_text(encoding="utf-8"))

    letters = json.loads((DATA_DIR / "letters.json").read_text(encoding="utf-8"))
    letters.update(pack.get("letters", {}))
    return pack, letters
