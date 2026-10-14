# PRODUCTION_NOTES_DRAFT.md

**Draft notes for Bohlokoa Machaha — rewrite in your own words before submitting the written half-page.**

## Scale target

- ~200 casinos, refresh bonus fields once per day
- Same fields as screening JSON + scrape timestamp + raw terms hash for change detection

## Where it runs (and why)

- **AWS ECS Fargate** scheduled task (or **GCP Cloud Run Jobs**) for the scraper — no server to patch, scales to zero, easy secrets via SSM/Secret Manager
- **Alternative:** single small **Hetzner VPS** (~€5/mo) with cron if cost must be minimal and team comfortable patching OS
- Static comparison site on **Cloudflare Pages** or **GitHub Pages** (free CDN, HTTPS automatic)

## Database and backups

- **PostgreSQL** (RDS `db.t4g.micro` or **Neon** serverless) — tables: `casinos`, `bonus_snapshots`, `scrape_runs`
- Store structured fields + `source_url` + `raw_terms` + `content_sha256`
- **Backups:** RDS automated backups 7–14 days; or Neon PITR; weekly logical dump to S3 with lifecycle (30 days)

## Domain, DNS, HTTPS

- Domain on **Cloudflare** (registrar or DNS-only)
- `A`/`CNAME` to Pages host; scraper API (if any) on subdomain `api.example.com`
- HTTPS via host-managed certs (Pages/Cloudflare); enforce HSTS on static site

## Scheduling and failure alerting

- **EventBridge** rule (daily 04:00 UTC) → Fargate task, or **cron** on VPS
- Scraper exits non-zero on: robots disallow, HTTP block, <95% casinos parsed, LLM schema validation fail
- **Alerting:** SNS → email/Slack, or **Better Stack** / **PagerDuty** on failed run metric
- Dashboard: last success time, rows updated, LLM token spend

## Rough monthly cost (USD / ZAR)

Assumptions: 200 casinos, 1 run/day, ~2 HTTP requests/casino, ~1k tokens LLM/casino.

| Item | USD/mo | Basis |
|------|--------|--------|
| Fargate scraper (5 min/day, 0.25 vCPU) | ~$3–8 | AWS pricing calculator |
| RDS db.t4g.micro | ~$15–20 | single-AZ |
| S3 logs/backups | ~$1–3 | few GB |
| LLM (gpt-4o-mini class) | ~$5–15 | 200k tokens/day order-of-magnitude |
| Static hosting | $0 | Cloudflare Pages free tier |
| **Total** | **~$25–45/mo** | |
| **ZAR** (USD × 18) | **~R450–R810/mo** | illustrative FX |

Cheaper path: VPS + SQLite + regex-heavy parsing + smaller LLM only on changed hashes → **~$10–15 USD/mo** but more ops burden.

## Not covered in screening repo

- Legal/compliance review per jurisdiction
- Affiliate link tracking
- Rate limiting / polite crawl delays across 200 sites
- Human review queue for low-confidence LLM extractions
