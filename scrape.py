#!/usr/bin/env python3
"""Scrape casino welcome-style bonuses from LCB.org and write data/bonuses.json."""

from __future__ import annotations

import json
import os
import re
import sys
import textwrap
import urllib.robotparser
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from openai import OpenAI

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
ROBOTS_PATH = DATA_DIR / "robots_lcb_org.txt"
OUTPUT_PATH = DATA_DIR / "bonuses.json"

SOURCE_LIST_URL = "https://lcb.org/bonuses/exclusive"
ROBOTS_URL = "https://lcb.org/robots.txt"
USER_AGENT = "CasinoBonusScreeningBot/1.0 (+https://github.com; educational screening task)"

CASINO_COUNT = 3
REQUEST_TIMEOUT = 45

GROQ_OPENAI_BASE_URL = "https://api.groq.com/openai/v1"
# Groq retired llama-3.3-70b-versatile on 2026-08-16; see console.groq.com/docs/deprecations
GROQ_DEFAULT_MODEL = "openai/gpt-oss-120b"
OPENAI_DEFAULT_MODEL = "gpt-4o-mini"


@dataclass
class RawBonus:
    casino_name: str
    bonus_headline: str
    wr_short: str
    wr_tooltip: str
    source_url: str
    terms_text: str
    bonus_id: str


def session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})
    return s


def fetch_robots(s: requests.Session) -> tuple[str, dict[str, Any]]:
    resp = s.get(ROBOTS_URL, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    text = resp.text
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ROBOTS_PATH.write_text(text, encoding="utf-8")

    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(ROBOTS_URL)
    rp.parse(text.splitlines())

    allowed = rp.can_fetch(USER_AGENT, SOURCE_LIST_URL)
    return text, {
        "robots_url": ROBOTS_URL,
        "source_url": SOURCE_LIST_URL,
        "user_agent": USER_AGENT,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "can_fetch_source": allowed,
        "saved_to": str(ROBOTS_PATH.relative_to(ROOT)),
    }


def clean_text(el) -> str:
    if el is None:
        return ""
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True))


def parse_list_row(row) -> dict[str, str] | None:
    bonus_id = row.get("data-bonus")
    if not bonus_id:
        return None

    name_el = row.select_one(".table-cell.name h3 a")
    if not name_el:
        return None
    casino_name = clean_text(name_el)
    casino_name = re.sub(r"^New!\s*", "", casino_name, flags=re.I)

    bonus_el = row.select_one(".table-cell.bonus p")
    bonus_headline = clean_text(bonus_el)
    if not bonus_headline:
        return None

    wr_el = row.select_one(".table-cell.lowest a, .table-cell.lowest")
    wr_short = ""
    wr_tooltip = ""
    if wr_el:
        wr_short = clean_text(wr_el.select_one("span")) or clean_text(wr_el)
        wr_tooltip = wr_el.get("data-original-title") or ""

    casino_href = row.select_one(".table-cell.logo.casino a")
    if not casino_href or not casino_href.get("href"):
        return None
    casino_url = urljoin(SOURCE_LIST_URL, casino_href["href"])
    source_url = f"{casino_url}#bonus-item-{bonus_id}"

    return {
        "casino_name": casino_name,
        "bonus_headline": bonus_headline,
        "wr_short": wr_short,
        "wr_tooltip": wr_tooltip,
        "source_url": source_url,
        "casino_url": casino_url,
        "bonus_id": bonus_id,
    }


def fetch_bonus_terms(s: requests.Session, casino_url: str, bonus_id: str) -> str:
    resp = s.get(casino_url, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    offer = soup.select_one(f'[data-bonus="{bonus_id}"]')
    if offer:
        content = offer.select_one(".content")
        if content:
            return clean_text(content)

    anchor = soup.select_one(f"#bonus-item-{bonus_id}")
    if anchor:
        block = anchor.find_parent(class_=re.compile("bonus"))
        if block:
            content = block.select_one(".content, .bonus-desc")
            if content:
                return clean_text(content)
        return clean_text(anchor)

    return ""


def is_deposit_style_bonus(headline: str) -> bool:
    h = headline.lower()
    if "%" in headline or "up to" in h:
        return True
    if re.search(r"\d+\s*%\s*", headline):
        return True
    return False


def scrape_raw_bonuses(s: requests.Session) -> list[RawBonus]:
    resp = s.get(SOURCE_LIST_URL, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    if resp.status_code == 403:
        raise RuntimeError("Blocked by source (HTTP 403).")

    soup = BeautifulSoup(resp.text, "lxml")
    rows = soup.select("#bonuses-list .table-row")
    if not rows:
        raise RuntimeError("No bonus rows found on list page.")

    picked: list[RawBonus] = []
    seen_casinos: set[str] = set()

    for row in rows:
        parsed = parse_list_row(row)
        if not parsed:
            continue
        if parsed["casino_name"] in seen_casinos:
            continue
        if not is_deposit_style_bonus(parsed["bonus_headline"]):
            continue

        terms = fetch_bonus_terms(s, parsed["casino_url"], parsed["bonus_id"])
        combined_terms = " ".join(
            filter(
                None,
                [
                    parsed["bonus_headline"],
                    parsed["wr_short"],
                    parsed["wr_tooltip"],
                    terms,
                ],
            )
        )

        picked.append(
            RawBonus(
                casino_name=parsed["casino_name"],
                bonus_headline=parsed["bonus_headline"],
                wr_short=parsed["wr_short"],
                wr_tooltip=parsed["wr_tooltip"],
                source_url=parsed["source_url"],
                terms_text=combined_terms,
                bonus_id=parsed["bonus_id"],
            )
        )
        seen_casinos.add(parsed["casino_name"])
        if len(picked) >= CASINO_COUNT:
            break

    if len(picked) < CASINO_COUNT:
        raise RuntimeError(
            f"Only found {len(picked)} deposit-style bonuses; need {CASINO_COUNT}."
        )

    return picked


def llm_client() -> tuple[OpenAI | None, str | None, dict[str, str]]:
    """Resolve LLM client: Groq by default when LLM_API_KEY is set without LLM_BASE_URL."""
    provider = os.environ.get("LLM_PROVIDER", "").lower()
    model_override = os.environ.get("LLM_MODEL")
    base_url = os.environ.get("LLM_BASE_URL")
    openai_key = os.environ.get("OPENAI_API_KEY")
    llm_key = os.environ.get("LLM_API_KEY")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")

    api_key: str | None = None
    model = model_override or OPENAI_DEFAULT_MODEL
    resolved_base = base_url

    if base_url:
        api_key = openai_key or llm_key or anthropic_key
        if not model_override and "groq.com" in base_url:
            model = GROQ_DEFAULT_MODEL
            provider = provider or "groq"
        elif not provider:
            provider = "openai" if openai_key and not llm_key else "custom"
    elif provider == "openai" and openai_key:
        api_key = openai_key
        model = model_override or OPENAI_DEFAULT_MODEL
        provider = "openai"
    elif llm_key:
        api_key = llm_key
        resolved_base = GROQ_OPENAI_BASE_URL
        model = model_override or GROQ_DEFAULT_MODEL
        provider = "groq"
    elif openai_key:
        api_key = openai_key
        model = model_override or OPENAI_DEFAULT_MODEL
        provider = "openai"
    elif anthropic_key:
        api_key = anthropic_key
        resolved_base = "https://api.anthropic.com/v1/"
        model = model_override or "claude-3-5-haiku-latest"
        provider = "anthropic"
    else:
        provider = provider or "openai"

    meta = {
        "provider": provider,
        "model": model,
        "base_url": resolved_base or "",
    }
    if not api_key:
        return None, None, meta

    client = (
        OpenAI(api_key=api_key, base_url=resolved_base)
        if resolved_base
        else OpenAI(api_key=api_key)
    )
    return client, model, meta


def regex_fallback_extract(raw: RawBonus) -> dict[str, Any]:
    """Parse structured fields from scraped text when the LLM step cannot run."""
    wr = None
    m = re.search(r"(\d+)\s*x", raw.wr_short, re.I)
    if m:
        wr = int(m.group(1))
    if wr is None:
        m = re.search(r"WR:\s*(\d+)\s*x", raw.terms_text, re.I)
        if m:
            wr = int(m.group(1))
    if wr is None:
        m = re.search(r"(\d+)\s*times", raw.wr_tooltip, re.I)
        if m:
            wr = int(m.group(1))

    min_dep = None
    for pattern in (
        r"Minimum deposit:\s*(\$[\d.,]+|\€[\d.,]+|£[\d.,]+)",
        r"Min deposit:\s*(\$[\d.,]+|\€[\d.,]+|£[\d.,]+)",
    ):
        m = re.search(pattern, raw.terms_text, re.I)
        if m:
            min_dep = m.group(1).rstrip(".")
            break

    return {
        "welcome_bonus": raw.bonus_headline,
        "wagering_requirement_multiplier": wr,
        "minimum_deposit": min_dep,
    }


def extract_with_llm(client: OpenAI, model: str, raw: RawBonus) -> dict[str, Any]:
    system = (
        "You extract structured casino bonus fields from marketing terms. "
        "Return only valid JSON matching the schema."
    )
    user = textwrap.dedent(
        f"""
        Casino: {raw.casino_name}
        Source page: {raw.source_url}

        Free-text terms (may include HTML entities already decoded):
        {raw.terms_text}

        Extract:
        - welcome_bonus: short human-readable headline (e.g. "200% up to $200 + 50 Spins")
        - wagering_requirement_multiplier: numeric multiplier only (e.g. 35 for 35x). If multiple,
          use the primary bonus WR; if only "WR for Free Spins: 10x" and deposit match WR is 30x(b+d),
          prefer the deposit+bonus figure as 30. Null if unknown.
        - minimum_deposit: include currency symbol/code as shown (e.g. "$30", "€20"). Null if not stated.

        JSON schema:
        {{"welcome_bonus": string, "wagering_requirement_multiplier": number|null, "minimum_deposit": string|null}}
        """
    ).strip()

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content or "{}"
    data = json.loads(content)
    return {
        "welcome_bonus": data.get("welcome_bonus") or raw.bonus_headline,
        "wagering_requirement_multiplier": data.get("wagering_requirement_multiplier"),
        "minimum_deposit": data.get("minimum_deposit"),
    }


def build_output(
    robots_meta: dict[str, Any],
    raw_bonuses: list[RawBonus],
    llm_meta: dict[str, str],
    llm_ran: bool,
) -> dict[str, Any]:
    casinos: list[dict[str, Any]] = []
    for raw in raw_bonuses:
        entry: dict[str, Any] = {
            "casino_name": raw.casino_name,
            "source_url": raw.source_url,
            "wr_short_scraped": raw.wr_short,
            "raw_terms_excerpt": raw.terms_text[:500],
        }
        if llm_ran and llm_meta.get("_client") and llm_meta.get("_model"):
            structured = extract_with_llm(llm_meta["_client"], llm_meta["_model"], raw)
            entry.update(structured)
            entry["extraction"] = "llm"
        else:
            entry.update(regex_fallback_extract(raw))
            entry["extraction"] = "regex_fallback_no_llm_key"
        casinos.append(entry)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "candidate": "Bohlokoa Machaha",
        "source": {
            "name": "LCB.org exclusive casino bonuses",
            "list_url": SOURCE_LIST_URL,
            "why": (
                "Public comparison/listing site with static HTML bonus tables, "
                "per-bonus terms on casino pages, and robots.txt allows crawling."
            ),
        },
        "robots": robots_meta,
        "llm": {
            "ran": llm_ran,
            "provider": llm_meta.get("provider"),
            "model": llm_meta.get("model") if llm_ran else None,
            "env_vars": [
                "LLM_API_KEY",
                "OPENAI_API_KEY",
                "LLM_PROVIDER",
                "LLM_MODEL",
                "LLM_BASE_URL",
            ],
            "groq_default_base_url": GROQ_OPENAI_BASE_URL,
            "groq_default_model": GROQ_DEFAULT_MODEL,
        },
        "casinos": casinos,
    }


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    s = session()

    robots_text, robots_meta = fetch_robots(s)
    if not robots_meta["can_fetch_source"]:
        print(f"robots.txt disallows fetching {SOURCE_LIST_URL}", file=sys.stderr)
        return 2

    raw_bonuses = scrape_raw_bonuses(s)

    client, model, llm_meta = llm_client()
    llm_ran = False
    if client and model:
        llm_meta["_client"] = client
        llm_meta["_model"] = model
        llm_ran = True
    else:
        print(
            "No LLM API key found (set OPENAI_API_KEY or LLM_API_KEY). "
            "Writing JSON with scraped headlines only; re-run after adding a key.",
            file=sys.stderr,
        )

    payload = build_output(robots_meta, raw_bonuses, llm_meta, llm_ran)
    # Remove non-serializable client reference
    llm_meta.pop("_client", None)
    llm_meta.pop("_model", None)

    OUTPUT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH} ({len(payload['casinos'])} casinos, llm_ran={llm_ran})")

    try:
        from scripts.build_docs import build_docs

        build_docs()
    except Exception as exc:  # noqa: BLE001
        print(f"Warning: docs build failed: {exc}", file=sys.stderr)

    return 0 if llm_ran else 1


if __name__ == "__main__":
    raise SystemExit(main())
