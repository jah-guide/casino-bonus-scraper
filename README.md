# Casino bonus scraper (screening task)

Candidate: **Bohlokoa Machaha**

Small Python scraper plus a static HTML table showing three casino welcome-style bonuses from one public source ([LCB.org exclusive bonuses](https://lcb.org/bonuses/exclusive)).

**Live page:** [https://jah-guide.github.io/casino-bonus-scraper/](https://jah-guide.github.io/casino-bonus-scraper/) (GitHub Pages from `/docs` on `main`).

## What it does

1. Fetches and saves `https://lcb.org/robots.txt` to `data/robots_lcb_org.txt`.
2. Scrapes three deposit-style offers from the exclusive bonuses list (HTML table).
3. Loads full free-text terms from each casino’s LCB review page (`#bonus-item-<id>`).
4. Calls a configurable LLM (OpenAI-compatible API) to turn those terms into structured fields.
5. Writes `data/bonuses.json` and copies it to `docs/data/bonuses.json` for the web page.

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
python scrape.py
```

Optional LLM configuration (at least one API key is required for full structured extraction):

| Variable | Purpose |
|----------|---------|
| `LLM_API_KEY` | Groq API key (default path when set and `LLM_BASE_URL` is unset) |
| `OPENAI_API_KEY` | OpenAI key; use with `LLM_PROVIDER=openai`, or alone if `LLM_API_KEY` is not set |
| `LLM_PROVIDER` | `openai` to force OpenAI when both keys might be present |
| `LLM_MODEL` | Override model ID (Groq default: `openai/gpt-oss-120b`; OpenAI default: `gpt-4o-mini`) |
| `LLM_BASE_URL` | Override API base (Groq default: `https://api.groq.com/openai/v1`) |

**Groq (default when `LLM_API_KEY` is set):** the scraper uses Groq’s OpenAI-compatible endpoint and model `openai/gpt-oss-120b`. Groq [retired `llama-3.3-70b-versatile` on 2026-08-16](https://console.groq.com/docs/deprecations); override with `LLM_MODEL` if you use another hosted model.

```bash
export LLM_API_KEY="gsk_..."
python3 scrape.py
```

**OpenAI:**

```bash
export LLM_PROVIDER=openai
export OPENAI_API_KEY="sk-..."
python3 scrape.py
```

Exit code `0` when the LLM step runs; `1` when scraping succeeded but no API key was set (JSON still written with headlines only).

Rebuild the static page data only:

```bash
python scripts/build_docs.py
```

Preview locally:

```bash
python3 -m http.server 8765 --directory docs
```

Open `http://127.0.0.1:8765/`.

## Source and robots.txt

- **Source:** [https://lcb.org/bonuses/exclusive](https://lcb.org/bonuses/exclusive) — public bonus comparison/listing with static HTML rows and linked terms on casino pages.
- **robots.txt:** [https://lcb.org/robots.txt](https://lcb.org/robots.txt) — `User-agent: *` with `Allow: /`; the bonuses path is not disallowed. The scraper checks `can_fetch` for the list URL before requesting it. Saved copy: `data/robots_lcb_org.txt`.

No logins, CAPTCHAs, or paywalls are bypassed. Standard `User-Agent` only.

## LLM step

`extract_with_llm()` in `scrape.py` sends scraped free-text terms to the configured chat model and expects JSON:

- `welcome_bonus`
- `wagering_requirement_multiplier` (number)
- `minimum_deposit`

If no key is present, the script documents `llm.ran: false` in the JSON and fills wagering/min-deposit using **regex on the scraped terms** (`extraction: regex_fallback_no_llm_key`) — not hand-typed and not LLM output. Re-run with a key for LLM-based extraction.

## Static hosting (GitHub Pages)

1. Push this repo to GitHub.
2. **Settings → Pages → Build and deployment:** deploy from branch `main`, folder `/docs`.
3. The site serves `docs/index.html` and `docs/data/bonuses.json`.

No build step is required on Pages beyond running `python scrape.py` before commit.

## Known limitations

- Only three casinos from one list page; not production scale.
- LCB HTML/layout changes would break selectors.
- Wagering rules can be ambiguous (e.g. separate WR for free spins vs. deposit match); the LLM prompt asks for a best-effort primary multiplier.
- Minimum deposit is not on the list table; it comes from casino page terms via LLM parsing.
- No database, scheduler, or monitoring (see `PRODUCTION_NOTES_DRAFT.md` for a production sketch).
