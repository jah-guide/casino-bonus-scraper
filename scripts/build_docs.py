#!/usr/bin/env python3
"""Copy scraped JSON into docs/ for static hosting."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_JSON = ROOT / "data" / "bonuses.json"
DOCS_DIR = ROOT / "docs"
DOCS_DATA = DOCS_DIR / "data" / "bonuses.json"


def build_docs() -> None:
    if not DATA_JSON.is_file():
        raise FileNotFoundError(f"Missing {DATA_JSON}; run scrape.py first.")

    DOCS_DATA.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(DATA_JSON, DOCS_DATA)

    # Validate JSON
    json.loads(DOCS_DATA.read_text(encoding="utf-8"))
    print(f"Copied bonuses JSON to {DOCS_DATA}")


if __name__ == "__main__":
    build_docs()
