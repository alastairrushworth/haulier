# Build Specification — "FirstMover" HGV Operator-Licence Lead Alerts

| | |
|---|---|
| **Version** | 1.0 (draft for team review) |
| **Status** | Ready for Phase 0 |
| **Audience** | Engineering, plus whoever runs QA and customer emails |
| **Product owner** | Founder |
| **Working name** | FirstMover (placeholder — rename freely) |

---

## 1. Executive summary

We are building a **subscription data product** that converts the UK Traffic Commissioners' fortnightly *Applications & Decisions* (A&D) publications into a clean, enriched, territory-filtered **sales-lead feed** for companies that sell to road hauliers.

When a business applies for a goods vehicle operator licence (an "O-licence"), it is signalling — roughly **nine weeks before trucks are on the road** — that it is about to buy vehicles, finance, insurance, fuel cards, telematics, tachograph analysis, driver agency services, and compliance support. That signal is published, but it is buried across eight regional publication streams in unfriendly PDF documents that no salesperson wants to read. Our product reads them, structures them, enriches them with Companies House data, and delivers a fortnightly digest + CSV to subscribers filtered by territory and event type.

**Business model:** B2B subscription. Single region £79/mo, all regions £149/mo, annual = 10 months. Founding customers ~50% off for life in exchange for testimonials and feedback calls. No free tier; a static sample issue instead of a trial. A £299/mo API/CRM tier is deferred until a customer asks.

**Why this can win:** the source data is public but painful; the value is completeness + change detection + enrichment + territory relevance + timing. The equivalent product category ("new authority leads") is a proven, established industry in the US trucking market. No direct UK competitor was found in our market scan (see §2.4) — verify again during Phase 0.

**V1 definition of done:** a paying subscriber receives, within 24 hours of each A&D publication in their chosen region(s), an accurate email digest and CSV of new applications, grants, variations, surrenders, and revocations, with Companies House enrichment, at ≥99% precision on licence numbers and ≥97% on operator names, produced by a pipeline that alerts us when anything looks wrong.

---

## 2. Business context

### 2.1 Origin and strategy
This product came out of a first-principles search for niche data-aggregation subscriptions: fragmented public data, perishable, upstream of a high-value decision, serving a small but motivated professional audience. This vertical won because the source set is **bounded** (eight regional publication streams, not 300 councils), the buyers carry **sales quotas** (purchase decision is arithmetic), and the **US precedent** de-risks demand. The pipeline is deliberately designed so it can later be cloned onto adjacent verticals (premises licence applications, EPC/MEES retrofit leads) with the extraction machinery intact.

### 2.2 Target customers (personas)
1. **Truck & trailer dealers** (new and used) — want new applications and vehicle-increase variations in their patch.
2. **Asset finance brokers/lenders** — same signals; value director info and incorporation date for pre-qualification.
3. **Commercial insurance brokers** (fleet, GIT) — new operators need cover before vehicles operate.
4. **Telematics / camera / tachograph-analysis vendors** — new operators must run compliance systems.
5. **Fuel card resellers** — high-churn sales teams that live on fresh lead lists.
6. **Transport consultants & TM services** — applications (help them get granted), plus revocations/PIs (rescue work).
7. Secondary: driver agencies, tyre fleets, insurers' MGAs, workshop chains.

### 2.3 Jobs to be done
- "Tell me about every new operator in my territory before my competitors know they exist."
- "Tell me when an existing operator is authorised for more vehicles" (expansion = buying moment).
- "Tell me when a licence is surrendered/revoked" (win-back, risk management, distressed-asset signals).
- "Give me enough context (directors, company age, address, fleet size) to make the first call intelligent."

### 2.4 Competitive landscape (as scanned July 2026 — re-verify in Phase 0)
No UK service found selling A&D-derived leads. Adjacent players: O-licence application consultancies (not data products), enterprise construction/transport lead platforms (do not cover this), and the free-but-painful DIY route (GOV.UK pages + VOL public register). **Phase 0 task:** search trade press (Commercial Motor, Motor Transport, Transport Operator), Facebook/LinkedIn groups for transport managers, and ask every pilot prospect "how do you find new operators today?" — sub-scale competitors don't rank in Google.

### 2.5 Commercial guardrails
- This is a side-income business, deliberately small: target 50–80 subscribers, £5–8k MRR, a few hours/week steady-state.
- **Kill criterion:** if 20 well-targeted pitches cannot produce 3 paying pilots (£49/mo founding rate) by end of Phase 2, stop and redeploy the pipeline onto the premises-licence vertical.
- Nothing in this spec should take on infrastructure or complexity that assumes venture scale.

---

## 3. Domain primer (read this before touching code)

### 3.1 The O-licence system in one page
- Operating goods vehicles over 3.5t (and, since 2022, some light goods vehicles ≥2.5t on international work) requires an **operator licence** issued by a **Traffic Commissioner (TC)**.
- Great Britain is divided into **eight traffic areas**, each with its own TC and its own publication stream. (Northern Ireland has a separate regime under DfI NI — **out of scope for v1**, schema should not preclude it.)
- Licence types: **Restricted** (own goods only), **Standard National**, **Standard International**. PSV (bus/coach) licences are a parallel system — **out of scope v1** but the schema carries a `licence_category` field (`goods` | `psv`) for later.
- Licences authorise a number of **vehicles** and **trailers** at one or more **operating centres**. Increasing authorisation requires a **variation** — commercially, a variation to add vehicles is one of the hottest buy-signals in the dataset.
- Applications must be advertised and are open to representations; the TC publishes applications and decisions in the fortnightly **Applications & Decisions (A&D)** documents per traffic area, hosted on GOV.UK guidance pages (e.g. "Goods vehicle applications and decisions for the north west of England"). Each release is numbered (e.g. "release 6861").
- A&D documents contain sections along the lines of: new applications received; applications granted; applications refused/withdrawn; variations received/granted; surrenders; revocations, suspensions and curtailments; public inquiries; transport manager changes. **Exact section names and ordering vary by region and over time — treat section taxonomy as data, not constants.**

### 3.2 Identifiers
- Licence numbers look like a **two-letter prefix + 6–7 digits** (e.g. `OC1234567`). First letter appears to distinguish goods (`O`) vs PSV (`P`); the second letter encodes the traffic area. **Do not hard-code a prefix→region mapping from this spec — build it empirically in Phase 0 from real documents and store it in a reference table** (`licence_prefix_map`), flagged for review whenever an unseen prefix appears.
- Validation regex (working assumption, confirm in Phase 0): `^[OP][A-Z][0-9]{6,7}$`.

### 3.3 Source inventory
| Source | What it gives us | Access | Role |
|---|---|---|---|
| GOV.UK A&D guidance pages (8, one per traffic area) | The fortnightly PDF releases — our primary raw material | Public web; pages list releases with attachment links | **Primary** |
| GOV.UK Content/Search APIs (`www.gov.uk/api/...`) | Machine-readable page metadata to detect new releases | Public, no key | Watcher |
| VOL — Vehicle Operator Licensing public register (`vehicle-operator-licensing.service.gov.uk`) | Authoritative current state of any licence | Public search UI | Validation & deep-link target. **Phase 0: read its terms; keep query volume low and polite** |
| data.gov.uk dataset: *Traffic Commissioners: goods and public service vehicle operator licence records* | Periodic bulk snapshot of the licence register | Open data download | Bulk cross-validation, backfill, entity resolution |
| Companies House API | Company number, status, incorporation date, directors, SIC, registered office | Free API key; rate-limited (verify current limits in CH docs during Phase 0) | Enrichment |
| The Gazette (insolvency notices) | Optional later enrichment (distress signals) | Public | Phase 3+, not v1 |

### 3.4 Timing model
Publication cadence is approximately fortnightly per region but **not guaranteed or synchronised**. The system must treat cadence as an observation (per-region rolling average) and alarm on silence (>21 days without a release) rather than assume a schedule.

---

## 4. Product requirements (V1)

### 4.1 Event taxonomy
Every extracted fact becomes an **event** of exactly one type:

| Event type | Meaning | Commercial heat |
|---|---|---|
| `NEW_APPLICATION` | New O-licence application received | ★★★ the core product |
| `APPLICATION_GRANTED` | Licence granted (incl. grant of new app) | ★★★ operator now live |
| `APPLICATION_REFUSED` | Refused | ★ context |
| `APPLICATION_WITHDRAWN` | Withdrawn before decision | ★ context |
| `VARIATION_APPLICATION` | Change requested (esp. vehicle/trailer increase, new operating centre) | ★★★ expansion signal; capture the delta |
| `VARIATION_GRANTED` | Variation granted | ★★★ |
| `SURRENDER` | Licence surrendered | ★★ win-back / churn intel |
| `REVOCATION` | Licence revoked by TC | ★★ risk + rescue-services signal |
| `SUSPENSION` / `CURTAILMENT` | Disciplinary action | ★★ |
| `PUBLIC_INQUIRY` | PI listed/decided | ★ (consultant audience) |
| `OTHER` | Anything that doesn't fit — must be rare; monitored | — |

### 4.2 Lead record (what a subscriber sees per event)
Required where present in source: operator/entity name; trading name; licence number; licence type; licence category; correspondence address; operating centre(s) with town/postcode; vehicles authorised; trailers authorised; **delta** for variations (e.g. "vehicles 3 → 7"); traffic area; event type; publication release number and date; free-text notes from source (e.g. PI details). Enrichment (best-effort): Companies House number, company status, incorporation date, up to 5 current directors (names + roles), SIC codes, registered office postcode, match confidence. Derived: `first_seen_date` for the licence in our data; deep link to the VOL record; `is_sole_trader_or_partnership` flag when no CH match is expected.

### 4.3 Delivery: the digest
- **Fortnightly email per region-release**, sent within 24h of publication detection, to subscribers whose preferences include that region.
- Structure: subject `[<Region>] <N> new operators, <M> expansions — A&D <release no>`; summary counts; then event-type sections in heat order; each lead as a compact card (see Appendix C for copy template); CSV attached containing the same rows.
- Plain-text alternative part required. Mobile-first HTML, no images required to read, inline CSS.
- **All-regions subscribers** receive one combined email per "publication day" batching whatever arrived that day, rather than eight separate emails.

### 4.4 CSV contract (columns are a stable API — additive changes only)
`event_id, event_type, event_date, publication_region, publication_release, publication_date, licence_number, licence_category, licence_type, operator_name, trading_name, correspondence_address, operating_centres, vehicles_authorised, trailers_authorised, vehicles_delta, trailers_delta, ch_company_number, ch_company_status, ch_incorporated_on, ch_directors, ch_sic_codes, ch_match_confidence, vol_url, source_notes, first_seen_date`

### 4.5 Subscriber preferences & account (V1 minimum)
- Fields: email, company name, regions (1..8 or ALL), event types (default: all "★★★" + surrender/revocation), plan, Stripe customer id.
- **No passwords.** Signed magic-link to a minimal preferences page (change regions/event types, pause, cancel via Stripe portal link).
- Unsubscribe link = pause deliveries (distinct from cancelling billing; page must make the difference clear).

### 4.6 Pricing & billing
- Stripe Checkout links; Stripe Billing portal for self-service. Prices: `single_region_monthly £79`, `all_regions_monthly £149`, annual equivalents at 10×monthly, `founding_*` at 50% with metadata flag. VAT via Stripe Tax.
- Webhooks drive subscription state; **deliveries gate on `subscription_status ∈ {trialing, active, past_due(grace ≤7d)}`**.

### 4.7 Explicit non-goals for V1
No dashboard, no login/passwords, no API, no instant alerts, no PSV, no Northern Ireland, no historical search UI, no CRM integrations, no lead scoring beyond event taxonomy, no mobile app. The email **is** the product until revenue argues otherwise.

### 4.8 Sales assets engineering must support
- A **static sample digest** (real data, ≥2 weeks old, on a public URL) for the pitch email.
- A one-page landing site: proposition, sample, two Stripe links, founding offer, FAQ, legal pages. Static hosting; no framework requirements.

---

## 5. System architecture

### 5.1 Overview

```
GOV.UK pages ──▶ [1 Watcher] ──▶ [2 Fetcher/Store] ──▶ [3 Extractor] ──▶ [4 Validator]
 (8 regions)        cron              R2/S3 + DB           LLM+rules         rules+VOL
                                                                               │
                    [8 Monitoring/Alerting] ◀── every component               ▼
                                                                    [5 Entity Resolver]
Stripe ◀──▶ [7 Billing/Subscribers]                                          │
   ▲                                                                          ▼
   │                                                                 [6 Enricher (CH)]
Subscriber ◀── [9 Digest Generator + Sender] ◀── [QA Review Queue] ◀──────────┘
```

Single Postgres database is the spine; every stage writes its outputs and status there. Components are plain jobs, not microservices.

### 5.2 Stack decisions (defaults — deviate only with a written reason)
- **Language:** Python 3.12 throughout. One monorepo.
- **DB:** Postgres 16. SQLAlchemy + Alembic migrations.
- **PDF handling:** `pdfplumber` for text-layer extraction; `ocrmypdf`/Tesseract fallback path if a text layer is ever absent (alert if triggered — expected never).
- **LLM:** Anthropic API, model `claude-sonnet-4-6`, temperature 0, structured JSON output. Follow current API docs at https://docs.claude.com/en/api/overview (tool-use/structured output patterns, SDK, and rate limits should be taken from the docs at build time, not from this spec).
- **Scheduling:** cron (systemd timers or the host platform's scheduler). No Airflow/Prefect in v1.
- **Object storage:** Cloudflare R2 (S3-compatible) for raw PDFs and rendered digests.
- **Email:** Postmark (separate transactional and broadcast message streams). Templates: Jinja2 + premailer (or MJML if the team prefers — decide once).
- **Billing:** Stripe Checkout + Billing Portal + Stripe Tax + webhooks into a small FastAPI app.
- **Admin/QA UI:** FastAPI + Jinja + HTMX, behind basic auth. (Streamlit acceptable if faster; keep it boring.)
- **Hosting:** one small VPS (e.g. Hetzner) or Fly.io; Docker Compose; that's it.
- **Errors/uptime:** Sentry + a heartbeat/dead-man's-switch service (e.g. Better Stack) for every scheduled job.

### 5.3 Component specs

#### [1] Publication Watcher
- Config table `sources` holds the 8 GOV.UK guidance-page URLs (resolved in Phase 0 from the GOV.UK collection page for traffic commissioner A&Ds).
- Every 6h per source: fetch page via GOV.UK Content API (fallback: HTML), extract the list of releases + attachment URLs, diff against `publications` table.
- New release ⇒ insert `publications` row (`status=discovered`) and enqueue fetch. Also parse release number and stated publication date from the title/metadata.
- Emit heartbeat per run; alarm if a region has no new release for >21 days, or if page structure fails to parse (**format-change alarm, human investigates — never guess**).

#### [2] Fetcher / Document store
- Download attachment(s); store at `r2://raw/{region}/{release}/{filename}`; record SHA-256, byte size, page count, `has_text_layer` (from pdfplumber probe).
- Re-publications/corrections: same release number with different hash ⇒ store as new **version**, mark previous `superseded`, and re-run extraction with diff-against-previous (see [4]).
- `publications.status → fetched`.

#### [3] Extraction service (the crown jewels)
Two-stage design: deterministic segmentation, then LLM field extraction.

1. **Segmentation (deterministic):** extract per-page text with layout via pdfplumber; locate section headings using a per-region heading lexicon table (`section_heading_map`: raw heading → canonical event type), seeded in Phase 0 and extended via QA. Unknown headings ⇒ segment routed to QA, alarm raised. Output: ordered list of `(canonical_section, raw_text_block, page_range)`.
2. **LLM extraction:** per section block (chunk to ≤~8k tokens with overlap at record boundaries), call Claude with a strict JSON Schema for an **array of records** appropriate to that section (schema per event type; see Appendix A). Temperature 0. System prompt forbids inference of absent fields (`null` if not present) and requires every `licence_number` and `operator_name` to be **verbatim substrings of the input text**.
3. **Post-parse guards (hard-fail the record, route to QA):**
   - `licence_number` matches regex AND appears verbatim in the source block.
   - `operator_name` appears verbatim (whitespace-normalised) in the source block.
   - Numeric fields (`vehicles_authorised`, etc.) appear as digits in the block.
   - Record count sanity: LLM record count vs a cheap regex count of licence-number occurrences in the block must match ±10%; mismatch ⇒ whole block to QA.
4. **Idempotency:** extraction keyed on `(publication_version_id, section, chunk_hash)`; safe to re-run.
5. **Cost note:** ~16–20 documents/month at modest page counts — LLM spend is trivial; do not micro-optimise at the expense of accuracy. Batch/async API optional.

#### [4] Validator
- Field-level rules (regex, enum, address plausibility, delta arithmetic for variations).
- **Cross-source check:** for a sample (100% during ramp, then ≥20%) of records, confirm licence number + name against the data.gov.uk bulk register snapshot; use the VOL public register sparingly for spot checks and for records the bulk file can't confirm (e.g. brand-new applications not yet in snapshot — expected; mark `not_yet_in_register` rather than fail).
- **Correction diffing:** for re-published versions, diff extracted record sets; changed records supersede prior events (`events.superseded_by`), and if a correction lands after a digest was sent, flag for a correction note in the next digest.
- Output: records marked `valid` | `needs_review` | `rejected` with machine-readable reasons.

#### [5] Entity resolver & event builder
- Natural key: `licence_number` ⇒ `licences` row (create if unseen; update `last_seen`). `operators` keyed off licence with name/trading-name history (type-2: keep old names with date ranges).
- Event uniqueness: `(licence_number, event_type, publication_version_id)` unique; cross-release duplicate suppression (same event republished) via `(licence_number, event_type, content_hash)` seen-before check.
- `first_seen_date` = earliest publication date at which this licence appeared in **our** data (clearly labelled as such in product copy; it is not an official date).

#### [6] Enricher (Companies House)
- Skip if name pattern strongly implies sole trader/partnership (heuristics + "T/A" handling); set `is_sole_trader_or_partnership=true`, `ch_match_confidence=0`.
- Match algorithm: normalised-name exact ⇒ high; else CH search API top-k, score on token-set ratio + postcode match (correspondence or operating-centre postcode vs registered office) + status=active; accept ≥0.85, review 0.60–0.85, reject <0.60. Store `match_method`, score, and a `manual_overrides` table that always wins.
- Fetch: profile + officers (current, up to 5). Respect CH rate limits per their current docs; exponential backoff; nightly batch, not inline.
- Cache company data 30 days; officers 30 days; re-fetch on demand from QA UI.

#### [7] Subscribers & billing
- Tables: `subscribers`, `subscriptions` (Stripe mirror), `preferences`, `deliveries`, `suppressions`.
- FastAPI endpoints: Stripe webhook (checkout.completed, subscription.updated/deleted, invoice.payment_failed), magic-link auth (`GET /prefs?token=…`, 7-day signed tokens), preference update, pause/unsubscribe.
- Founding-tier flag from Stripe price metadata; grandfathering is just "never migrate their price".

#### [8] Monitoring & alerting (non-negotiable)
- Heartbeats on every cron job; missed heartbeat pages the founder.
- Alarms: watcher parse failure; region silence >21d; `has_text_layer=false`; unknown section heading; extraction guard-failure rate >2% of records in a publication; record-count sanity failure; CH error rate; Postmark bounce/complaint spike; Stripe webhook failures; **digest not sent within 24h of publication `fetched`**.
- Weekly ops digest email to founder: publications processed, records extracted, QA queue size, accuracy spot-check results, MRR, churn.

#### [9] QA review queue + Digest generator/sender
- **Gate:** a publication may be released to subscribers only when `needs_review` records for it are resolved or consciously excluded. During ramp (first 3 clean cycles per region), a human reviews 100% of records in a side-by-side UI (source text block vs extracted fields, one-click accept/edit/reject). Steady state: review only `needs_review` + a random 10% audit sample.
- Generator: per region-release, per subscriber filter (regions ∩ event types), render Jinja templates + CSV, store artefacts in R2, record `deliveries` rows, send via Postmark broadcast stream with per-subscriber metadata; retries with idempotency keys so nobody gets duplicates.
- Suppression list applied at render time (see §9 Legal).

### 5.4 Data model (DDL sketch — Alembic owns the real thing)

```sql
CREATE TABLE sources (id serial PK, region text UNIQUE, guidance_url text, active bool DEFAULT true);

CREATE TABLE publications (
  id serial PK, source_id int REF sources, release_no text, published_on date,
  discovered_at timestamptz, status text CHECK (status IN
    ('discovered','fetched','extracted','validated','qa','ready','sent','superseded','failed')),
  UNIQUE (source_id, release_no));

CREATE TABLE publication_versions (
  id serial PK, publication_id int REF publications, version int,
  r2_key text, sha256 text UNIQUE, page_count int, has_text_layer bool, fetched_at timestamptz);

CREATE TABLE licences (
  licence_number text PK, licence_category text, licence_type text,
  region text, first_seen_date date, last_seen_date date);

CREATE TABLE operators (
  id serial PK, licence_number text REF licences, name text, trading_name text,
  valid_from date, valid_to date);

CREATE TABLE events (
  id uuid PK, licence_number text REF licences, event_type text,
  publication_version_id int REF publication_versions,
  payload jsonb,           -- full extracted record incl. addresses, centres, numbers, deltas, notes
  content_hash text, status text,  -- valid | needs_review | rejected | superseded
  superseded_by uuid NULL, created_at timestamptz,
  UNIQUE (licence_number, event_type, publication_version_id));

CREATE TABLE enrichments (
  licence_number text PK REF licences, ch_company_number text, ch_status text,
  ch_incorporated_on date, ch_directors jsonb, ch_sic jsonb, ch_registered_postcode text,
  match_confidence numeric, match_method text, is_sole_trader_or_partnership bool,
  fetched_at timestamptz);

CREATE TABLE manual_overrides (licence_number text PK, ch_company_number text, note text, set_by text, set_at timestamptz);
CREATE TABLE section_heading_map (id serial PK, region text NULL, raw_heading text, event_type text, active bool);
CREATE TABLE licence_prefix_map (prefix text PK, region text, licence_category text, confirmed bool);

CREATE TABLE subscribers (id serial PK, email citext UNIQUE, company text, stripe_customer_id text, created_at timestamptz);
CREATE TABLE subscriptions (id serial PK, subscriber_id int, stripe_subscription_id text UNIQUE,
  plan text, status text, current_period_end timestamptz, founding bool DEFAULT false);
CREATE TABLE preferences (subscriber_id int PK, regions text[], event_types text[], paused bool DEFAULT false);
CREATE TABLE deliveries (id serial PK, subscriber_id int, publication_version_id int,
  csv_r2_key text, html_r2_key text, postmark_message_id text, sent_at timestamptz, status text,
  UNIQUE (subscriber_id, publication_version_id));
CREATE TABLE suppressions (id serial PK, kind text CHECK (kind IN ('person','company','licence')),
  match_value text, reason text, created_at timestamptz);
```

---

## 6. LLM engineering standards

1. **Determinism:** temperature 0; fixed prompts under version control; prompt changes require re-running the golden set (below) and a recorded diff.
2. **Golden set:** Phase 0 produces ≥3 fully hand-labelled publications per region style encountered (aim ~300–600 labelled records). Stored in-repo as `(source_block, expected_records[])`. CI runs the extractor against it on every prompt/model/code change.
3. **Accuracy gates (block deploy if breached):** licence-number precision ≥99.5% & recall ≥99%; operator-name exact-match ≥97%; event-type classification ≥99%; numeric fields ≥99%.
4. **Hallucination containment:** verbatim-substring guards (see §5.3[3]) are hard requirements — an extracted value that cannot be located in the source text must never reach a subscriber, no matter how plausible.
5. **No silent degradation:** model deprecations/upgrades are treated like schema migrations — golden-set run, human sign-off, then release. Check current model availability and API behaviour against https://docs.claude.com rather than assuming.
6. **Escalation path:** blocks that fail guards get one retry with the failure reason appended; still failing ⇒ QA queue. No auto-accept of retries at lower confidence.

---

## 7. Data quality SLOs & release gates

| Metric | Target | Enforcement |
|---|---|---|
| Time: publication detected → digest sent | ≤24h (aspiration ≤6h) | Alarm at 18h unsent |
| Licence-number precision | ≥99.5% | Golden set in CI + 10% human audit sample |
| Operator-name accuracy | ≥97% exact | Same |
| Events wrongly typed | ≤1% | Same |
| Missed records per publication (recall) | ≤1% | Regex licence-count vs extracted-count reconciliation, human audit |
| Duplicate leads delivered | 0 tolerated | Uniqueness constraints + delivery idempotency |
| Corrections handling | Correction note in next digest, 100% of affected subscribers | `superseded_by` chain + generator rule |

A publication cannot move to `ready` unless: all guards passed or QA-resolved, reconciliation within tolerance, enrichment attempted for every eligible record, and (during ramp) human sign-off recorded.

---

## 8. Legal & compliance (build these in, don't bolt on)

1. **Source licensing:** GOV.UK content is Crown copyright under the **Open Government Licence v3.0**. Include attribution in the product footer and CSV README: "Contains public sector information licensed under the Open Government Licence v3.0." Verify the data.gov.uk register dataset carries OGL (expected) during Phase 0; record the licence of every source in the repo.
2. **Scraping etiquette:** GOV.UK pages/APIs — low volume, identify with an honest User-Agent including contact email. VOL public register — **read its terms in Phase 0**; keep to low-rate spot checks; never bulk-hammer a search UI; prefer the bulk dataset for volume.
3. **UK GDPR:** we process personal data (sole traders' names/addresses, directors' names). Lawful basis: **legitimate interests** (B2B lead intelligence from public registers). Deliverables: a Legitimate Interests Assessment (one page, written honestly), a privacy notice on the site covering data sources/purposes/retention, and a working **objection/erasure route**: requests land in a shared inbox, are actioned within 30 days, and feed the `suppressions` table so the person/company never appears in future digests. Retention: raw publications kept indefinitely (public record); enrichment data refreshed/pruned on a 12-month cycle.
4. **PECR reality check for customers:** our *subscribers* do outbound. UK PECR treats corporate subscribers differently from sole traders/partnerships for email marketing. Ship a short "using this data lawfully" note in the onboarding email and mark `is_sole_trader_or_partnership` prominently in the CSV so customers can route those to phone/post rather than cold email. We are not their lawyer; say so.
5. **Customer terms:** subscription licence for internal business use; no resale/redistribution; no scraping our digests into competing products; accuracy disclaimed to the level of "verified against public registers, provided as-is"; cancellation anytime via Stripe portal.
6. **Positioning discipline:** we sell factual public-record data plus enrichment. No creditworthiness scores, no "risk ratings" of named operators in v1 — that invites disputes we don't need.

---

## 9. Security & ops

- Secrets in the platform's secret store (never in repo); least-privilege API keys; Stripe webhook signature verification mandatory.
- Postgres: nightly automated backups + weekly restore test (scripted); R2 versioning on.
- Environments: `dev` (sample PDFs, Stripe test mode, Postmark sandbox) and `prod`. No staging theatre.
- Admin UI behind basic auth + IP allowlist if convenient; audit log on QA edits and manual overrides.
- **Runbooks (write during build, keep in repo):** (a) watcher parse failure; (b) extraction guard-rate alarm; (c) "we sent wrong data" — correction email template, affected-subscriber query, postmortem note; (d) publication silence; (e) Stripe webhook backlog; (f) restore from backup.

---

## 10. Testing strategy

- **Unit:** parsers, guards, matchers, delta arithmetic, dedupe keys.
- **Golden-set regression (CI-blocking):** as §6. Include at least one deliberately nasty synthetic PDF (split rows across pages, hyphenated names, multiple operating centres, "T/A" names).
- **Property tests:** every extracted value passes its verbatim/regex guard; event uniqueness holds under re-runs (idempotency test = run pipeline twice, DB state identical).
- **Integration:** end-to-end on a fixture publication → digest HTML + CSV snapshot tests (approved-file pattern).
- **Billing:** Stripe test-clock scenarios: subscribe, fail payment, grace, cancel, resubscribe; delivery gating asserted for each state.
- **Email:** rendering across major clients via Postmark previews/Litmus-style spot checks; plaintext part always generated; unsubscribe/prefs links signed and tested.

---

## 11. Delivery plan

### Phase 0 — Verification sprint (≈1 week, founder-led, no product code)
1. Resolve the 8 A&D guidance-page URLs from GOV.UK; record cadence and release-numbering per region.
2. Pull the last 3 releases per region; confirm text layer; catalogue section headings per region → seed `section_heading_map`; empirically build `licence_prefix_map`.
3. Confirm data.gov.uk register dataset: freshness, columns, licence. Read VOL terms. Register Companies House API key; confirm current rate limits from CH docs.
4. Hand-build (LLM-assisted, human-verified) the golden set from ≥2 regions, and simultaneously produce the **manual pilot digest** for one busy region.
5. **Sell:** send the pilot digest to 15–20 targets (persona list §2.2) at £49/mo founding. Gate: ≥3 verbal yeses → proceed to Phase 1. Also: competitor re-scan per §2.4.
6. Re-confirm pricing/copy against what prospects say. Deliverable: Phase 0 report updating this spec's assumptions (list in §14).

### Phase 1 — Pipeline MVP (≈3–4 weeks engineering)
Watcher, fetcher, extractor with guards, validator, resolver, CH enricher, QA UI, digest generator, monitoring. Exit criteria: two consecutive real publication cycles across ≥4 regions processed to `ready` with SLOs met and founder QA sign-off; internal digest indistinguishable from the hand-made pilot.

### Phase 2 — Commercial launch (≈2 weeks)
Stripe products/webhooks, preferences + magic links, suppression handling, landing page + sample issue, onboarding email with lawful-use note, founding customers migrated from manual to automated sends. Exit criteria: ≥3 paying subscribers on automated delivery; kill criterion evaluated honestly.

### Phase 3 — Deepening (pull-based, post-revenue)
Historical backfill of past releases (the proprietary time series: "operator grew 3→11 vehicles in 2 years"), licence-history search for QA/marketing content, £299 API/CRM tier when first requested, PSV toggle, The Gazette distress enrichment, clone assessment for premises-licence vertical.

### Suggested workstream split (2 people)
Engineer A: watcher/fetcher/extractor/validator + golden set harness. Engineer B (or founder): data model, enrichment, billing, digest/QA UI, monitoring. Founder throughout: Phase 0, QA sign-offs, sales.

---

## 12. KPIs & kill criteria

- **North star:** paying subscribers on automated delivery. Targets: 3 by end Phase 2; 15 by +2 months; 50–80 long-run.
- MRR £2k by month 3 post-launch, else execute the pivot (pipeline → premises licences) per §2.5.
- Ops health: digest latency, QA queue size, guard-failure rate, audit accuracy — reviewed in the weekly ops digest.
- Churn: monthly logo churn <5% steady-state; exit interviews (one question: "what would have kept you?").

---

## 13. Risks & mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Publication format changes silently | Medium | High | Heading-lexicon alarms, guard-rate alarms, golden set, human-in-loop ramp |
| PDFs lose text layer / scanned pages appear | Low | Medium | OCR fallback + alarm |
| GOV.UK reorganises pages/URLs | Medium | Medium | Watcher alarms on parse failure; sources table editable in admin |
| VOL/register terms restrict a validation path | Low | Low | Bulk dataset is primary validator; VOL is spot-check only |
| A competitor exists below our search radar | Medium | Medium | Phase 0 trade-press scan; differentiation = enrichment + territory + timing |
| Demand assumption wrong | Medium | High | Phase 0 sell-first gate; £49 founding pilots; hard kill criterion |
| Data protection complaint | Low | Medium | LIA, privacy notice, suppression workflow, no risk-scoring, B2B framing |
| Wrong data sent to customers | Low | High | Guards, QA gate, correction runbook, disclaim + fix fast |
| Founder time (side project) drifts | High | Medium | Non-goals list §4.7; boring stack; alarms instead of vigilance |

---

## 14. Open questions & assumptions to verify (Phase 0 owns all of these)

1. Exact list/URLs of the 8 A&D publication streams and their real cadence.
2. Licence-number format + prefix→region mapping (empirical).
3. Section heading taxonomy per region; existence of combined goods+PSV documents anywhere.
4. data.gov.uk register dataset freshness/columns/licence.
5. VOL public register terms of use.
6. Companies House API current rate limits and terms (check CH developer docs).
7. Whether A&D releases are ever amended in place (drives correction-diff priority).
8. Founding price acceptance at £49 → confidence in £79/£149 list.
9. Competitor re-scan results (trade press, LinkedIn, forums).
10. Anthropic API: confirm current model string, structured-output pattern, and limits at https://docs.claude.com at build time.

---

## Appendix A — Extraction JSON Schema (per-record core; per-section variants extend it)

```json
{
  "type": "object",
  "required": ["licence_number", "operator_name", "event_type"],
  "additionalProperties": false,
  "properties": {
    "licence_number": {"type": "string", "pattern": "^[OP][A-Z][0-9]{6,7}$"},
    "operator_name": {"type": "string", "minLength": 2},
    "trading_name": {"type": ["string", "null"]},
    "event_type": {"enum": ["NEW_APPLICATION","APPLICATION_GRANTED","APPLICATION_REFUSED","APPLICATION_WITHDRAWN","VARIATION_APPLICATION","VARIATION_GRANTED","SURRENDER","REVOCATION","SUSPENSION","CURTAILMENT","PUBLIC_INQUIRY","OTHER"]},
    "licence_type": {"enum": ["restricted","standard_national","standard_international", null]},
    "correspondence_address": {"type": ["string", "null"]},
    "operating_centres": {"type": "array", "items": {"type": "object", "properties": {"address": {"type": "string"}, "vehicles": {"type": ["integer","null"]}, "trailers": {"type": ["integer","null"]}}}},
    "vehicles_authorised": {"type": ["integer", "null"]},
    "trailers_authorised": {"type": ["integer", "null"]},
    "vehicles_previous": {"type": ["integer", "null"]},
    "trailers_previous": {"type": ["integer", "null"]},
    "source_notes": {"type": ["string", "null"]}
  }
}
```

## Appendix B — Extraction system-prompt skeleton (v0; iterate against golden set)

```
You extract structured records from a section of a UK Traffic Commissioner
"Applications and Decisions" publication. The section type is: {SECTION_TYPE}.

Rules:
- Output ONLY JSON matching the provided schema: an array of records.
- Copy licence numbers and names VERBATIM from the text. Never normalise,
  never infer, never complete a truncated value.
- If a field is not present in the text, use null. Do not guess.
- One record per licence entry. Do not merge or split entries.
- Text may contain page-break artefacts and hyphenation; a record's fields
  may continue across lines. Keep fields with their correct licence entry.
```

## Appendix C — Digest lead-card copy template

```
{OPERATOR NAME} {(T/A {TRADING NAME})}
{EVENT LABEL} · {LICENCE TYPE} · {LICENCE NO}
Fleet: {vehicles} vehicles / {trailers} trailers {(was {prev} → now {new})}
Operating centre: {town, postcode} {(+N more)}
Company: {CH number}, inc. {year} · Directors: {D1}, {D2}, {D3}
{⚑ Sole trader / partnership — no Companies House record}
Source: A&D {release}, {region}, {date} · View on VOL →
```

## Appendix D — Glossary
**A&D** Applications & Decisions publication · **TC** Traffic Commissioner · **VOL** Vehicle Operator Licensing service (public register) · **O-licence** goods vehicle operator licence · **Variation** change to an existing licence (vehicles/trailers/centres) · **PI** public inquiry · **CH** Companies House · **OGL** Open Government Licence · **LIA** Legitimate Interests Assessment.

---
*End of specification v1.0. Phase 0's report is the mandatory first revision of this document.*