# Infrastructure — running FirstMover on Cloudflare

Target: **under $10/month** all-in at launch. Costed 30 Aug 2026 against published
rates and measured against this repo's actual corpus, not estimated from feel.

## The bill

| Service | What it does | $/month |
|---|---|---:|
| **Workers Paid** | Base plan. Unlocks Containers, Cron Triggers, and D1's paid limits. | **5.00** |
| Workers requests | API, Stripe webhook, cron handlers | 0.00 — 10M/mo included |
| Cloudflare Containers | The Python pipeline, unchanged | 0.00 — 375 vCPU-min included |
| Cron Triggers | Scheduling | 0.00 |
| R2 | PDFs, text dumps, rendered digests + CSVs | 0.00 — 10 GB free, we use ~0.15 |
| D1 | Subscribers, preferences, licences, events | 0.00 — 5 GB free |
| Workers Static Assets | The landing site | 0.00 |
| Email Routing | Inbound `objection@`, `hello@` → your mailbox | 0.00 |
| Cloudflare Registrar | Domain, sold at cost | **~0.85** |
| Resend | Outbound digest delivery | 0.00 — 3,000/mo free |
| **Claude API** | Extraction — Haiku 4.5, standard | **3.71** |
| Stripe | Billing | 0.00 fixed (1.5% + 20p per UK card) |
| | **Total** | **$9.56** |

That is $0.44 of headroom, and the two numbers that can move are the domain
(a `.co.uk` is cheaper than a `.com`) and the model. Everything else is either
a fixed $5 or comfortably inside a free tier.

**One-off:** extracting the 270-release 2026 backfill for Stage 3 calibration —
$28.62 on Haiku 4.5 standard, or **$14.31 via the Batch API**, which is the right
tool for it because nobody is waiting on the result.

## The constraint that shapes the architecture

Cloudflare's Python Workers run on **Pyodide**: pure-Python and PyEmscripten
wheels only. `pdfplumber` pulls in `pdfminer.six` → `cryptography` (Rust) and
`pypdfium2` (native C). Neither compiles for that runtime, so **the PDF text
extraction step cannot run in a Python Worker.** No amount of configuration
changes this; it is a packaging boundary.

That sounds worse than it is, because the pipeline already has a clean seam at
exactly the right place. `haulier dump` caches per-page text as
`data/text/{region}/{release}.json.gz`, keyed by the PDF's SHA-256. Everything
downstream of that cache — heading analysis, licence harvesting, LLM extraction,
lead normalisation, digest and CSV rendering — is JSON manipulation and Jinja2,
which are pure Python and run on Workers without modification.

So: **put the PDF→text step in a Cloudflare Container and everything else in
Python Workers.** You keep the existing code, unchanged, and you are still
entirely on Cloudflare.

The measured cost of that decision is the good news:

```
PDF text extraction, 8 releases sampled across the corpus
  0.79 s per release, 41 ms per page

  ongoing:   35 releases/month  →   28 vCPU-seconds/month
  backfill:  270 releases       →  3.6 vCPU-minutes (one-off)

  Workers Paid includes           375 vCPU-minutes/month
```

Extraction uses **0.13%** of the included container allowance. Even budgeting a
`basic` instance (¼ vCPU, 1 GiB) staying up ten minutes a week to wait on the
Claude API, you land near 11 vCPU-minutes/month — 3% of the allowance. Containers
are effectively free here; the $5 plan fee is the whole cost.

## Architecture

```
                    ┌─ Cron Trigger (6-hourly) ─────────────┐
                    │                                        ▼
  GOV.UK Content API ──────────────────────────►  Python Worker: watcher
                                                   (JSON only — pure Python)
                                                            │ new release?
                                                            ▼
                                              Container: haulier capture + dump
                                              (pdfplumber — the one native step)
                                                            │
                                              PDFs + text dumps ──► R2
                                                            │
                                                            ▼
                                              Container: haulier extract
                                              (Claude API → records JSON) ──► R2
                                                            │
                    ┌─ Cron Trigger (17:00 daily) ──────────┤
                    ▼                                        ▼
        Python Worker: digest                   Python Worker: validate + enrich
        render HTML + CSV (Jinja2)              Companies House → D1
                    │                                        │
                    ├──────────────► R2 (artefacts)          ▼
                    └──────────────► Resend (send)          D1: licences, events,
                                                                subscribers, prefs

  Static Assets ──► the landing site (site/dist)
  Python Worker ──► Stripe webhook → D1 subscription status
```

Only the two container steps are not Python Workers, and only the first of those
is forced — `haulier extract` is in a container purely because it is convenient
to keep it next to `dump`. Move it to a Worker if you ever want to.

## Services to set up, in order

**1. Cloudflare account + Workers Paid — $5/mo.** Everything else hangs off this.
Containers and D1's paid limits both require it. Nothing here works on the free plan.

**2. Cloudflare Registrar — ~$10/yr.** Registrar sells at wholesale cost with no
markup and no first-year-cheap-then-renewal-expensive trick. A `.co.uk` runs
cheaper than a `.com` if you want the $0.44 headroom back.

**3. R2 bucket.** One bucket, prefixes `raw/`, `text/`, `digests/`. The whole 2026
corpus is ~150 MB against a 10 GB free tier, and R2 charges **no egress**, which
is the reason to use it over S3. Class A/B operation free tiers (1M/10M per month)
are orders of magnitude above a pipeline doing ~35 releases a month.

**4. D1 database.** Free tier is 5 GB, 5M row reads/day, 100k writes/day. At 80
subscribers and ~4,500 events a month you will not come close. This replaces the
Postgres in spec §5.2 for V1 — worth writing down as a deliberate deviation, and
worth knowing D1 has no `earthdistance`/PostGIS, so the radius filter from
PLAN §2.12 becomes a bounding-box prefilter in SQL plus a haversine check in the
Worker. At 2.6M postcodes and 80 subscribers that is fine; it would not be at 10,000.

**5. Cloudflare Container** with the existing `haulier` image. Use `basic`
(¼ vCPU, 1 GiB) — measured usage does not justify anything larger.

**6. Cron Triggers.** Two: a 6-hourly watcher, and a 17:00 Europe/London digest
batch (PLAN §2.7's cutoff). Free with Workers.

**7. Email Routing** for inbound. Free, and it gives you the working
`objection@` inbox that PLAN §2.11 makes a Stage 0 blocker. Point it at your
normal mailbox and set `HAULIER_OBJECTION_EMAIL`.

**8. Outbound email — not a Cloudflare product.** See below.

**9. Stripe.** No monthly fee; 1.5% + 20p per UK card transaction. At 10 founding
subscribers at £49 that is ~£9.35/month in fees — a cost of revenue, not
infrastructure, and it does not exist until you have customers.

**10. Anthropic API key.** PLAN decision 4 defers the production backend to
Stage 4, which is still right — but the numbers below say what it will cost.

## Two places the budget and the spec pull against each other

**Outbound email.** Spec §5.2 mandates Postmark. Postmark's cheapest paid plan is
**$15/month**, which breaks a $10 budget on its own, and its free tier is 100
emails/month. Measured need:

| Subscribers | Emails/month | Notes |
|---|---:|---|
| 3 founding | ~15–65 | single-region gets ~4.3/mo, all-regions ~21.5 |
| 20 mixed | ~260 | |
| 80 mixed | ~1,030 | |

**Recommendation: Resend's free tier** (3,000/month, 100/day) — it covers you to
roughly 150 subscribers, well past the point where £20/month stops mattering.
**Amazon SES** at $0.10 per 1,000 is the cheaper scale-up if you outgrow it. Both
are deviations from spec §5.2, and spec §5.2 says deviate only with a written
reason; the written reason is that Postmark costs 1.5× the entire infrastructure
budget to deliver 260 emails. Revisit at revenue — Postmark's deliverability
reputation is worth paying for once there is a business to protect.

PLAN §2.13's warning still stands regardless: **do not send the Stage 0 pitch
emails through any of these.** Twenty cold emails from a new sending domain is
the fastest way to poison the deliverability you will need later. Send those by
hand from a normal mailbox.

**The 24-hour SLO versus the Batch API.** The Batch API is half price, which is
tempting — but it is asynchronous with a 24-hour completion window, and spec §7
requires publication→digest within 24 hours with an alarm at 18. Batch consumes
the entire SLO budget. Measured monthly extraction cost, 35 releases at ~11.7k
input and ~18.9k output tokens each:

| Model | Standard | Batch (50%) | Total bill, standard |
|---|---:|---:|---:|
| **Haiku 4.5** | **$3.71** | $1.86 | **$9.56** ✅ |
| Sonnet 5 | $7.42 | $3.71 | $13.27 ✗ |
| Opus 5 | $18.55 | $9.28 | $24.40 ✗ |

The useful coincidence: **Haiku 4.5 on the standard API costs exactly what
Sonnet 5 costs on batch** — $3.71 — but returns synchronously, so it meets the
SLO instead of eating it. That is the configuration in the bill above.

Two caveats worth stating plainly. First, output tokens dominate here (660k out
against 410k in), because the extracted JSON *is* the product — so prompt caching,
normally the first cost lever, saves only about $0.20/month. Model choice is the
lever. Second, and more important: **this is a cost estimate, not a model
recommendation.** Spec §7 gates extraction at ≥99.5% licence-number precision and
≥97% operator-name accuracy. Whether Haiku 4.5 clears those bars is a question for
the golden set in Stage 1, not for this table. If it does not, Sonnet 5 costs
$3.71 more and you are $3.27 over budget — which, against 3 subscribers at £49,
is a rounding error. Do not let a $10 target pick your extraction model.

## What this does not cover

Sentry (free tier is ample), a dead-man's-switch (healthchecks.io free), and the
Companies House API (free, rate-limited to 600 requests per 5 minutes) are all
$0 and all listed in spec §5.3/§9. Backups: R2 versioning is free and D1 has
point-in-time recovery on the paid plan, which removes the "weekly scripted
restore test" chore PLAN §2.13 rightly says would get skipped by month two.
