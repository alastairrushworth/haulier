# Build Plan — FirstMover

Companion to `spec.md`. This document records (a) Phase 0 findings that change the spec's assumptions, (b) defects in the spec worth fixing before code, and (c) the build sequence.

Status: draft, 2 Aug 2026. Supersedes spec assumptions listed in §14 items 1–3 and 10.

---

## 1. Phase 0 findings (already verified)

Four of the spec's open questions are now answered. Two of the answers change the build.

### 1.1 The eight sources — resolved (§14 Q1)

All eight are GOV.UK **guidance** pages under `/guidance/applications-and-decisions-for-*`, linked from
`https://www.gov.uk/government/collections/traffic-commissioner-applications-and-decisions`
(note: singular "commissioner" — the spec's plural form 404s).

| Region | Path |
|---|---|
| East of England | `/guidance/applications-and-decisions-for-the-east-of-england` |
| London & South East | `/guidance/applications-and-decisions-for-london-and-the-south-east-of-england` |
| North East England | `/guidance/applications-and-decisions-for-the-north-east-of-england` |
| North West England | `/guidance/applications-and-decisions-for-the-north-west-of-england` |
| West Midlands | `/guidance/applications-and-decisions-for-the-west-midlands` |
| West of England | `/guidance/applications-and-decisions-for-the-west-of-england` |
| Scotland | `/guidance/applications-and-decisions-for-scotland` |
| Wales | `/guidance/applications-and-decisions-for-wales` |

PSV lives on a parallel set of `/guidance/notices-and-proceedings-for-*` pages — correctly out of scope for v1, and confirmation that the `licence_category` field earns its place.

### 1.2 Cadence is WEEKLY, not fortnightly — the biggest correction

Observed: North West published AD-7165 / 7166 / 7167 on 17, 24, 31 July 2026 (Fridays). Scotland published AD-2478 / 2479 / 2480 / 2481 on 6, 13, 20, 27 July (Mondays). Seven-day spacing in both, on **region-specific weekdays**.

Consequences:

- **Volume doubles.** ~416 documents/year, ~35/month — not the spec's 16–20/month. Every capacity assumption downstream (QA hours, extraction spend, digest sends) doubles.
- **The product gets better.** "Weekly leads" beats "fortnightly leads" in the pitch, and shortens time-to-first-value for a new subscriber from ~2 weeks to ~1.
- **§3.4 and §5.3[1] need rewriting.** Silence alarm drops from >21 days to **>14 days** (two missed weeks). Cadence is still an observation per region, not a constant — but the baseline is 7 days.
- **§4.3 changes.** Digest is weekly per region. All-regions subscribers get a daily batch, and because the eight regions publish on different weekdays they will receive something most weekdays. That needs a defined cutoff (see §2.7).
- Founder time in §2.5 ("a few hours/week") is now load-bearing on QA automation, not optional. See §2.6.

### 1.3 Format confirmed: PDF, with structured metadata via the Content API (§14 Q1, Q7)

The GOV.UK Content API (`https://www.gov.uk/api/content/guidance/applications-and-decisions-for-*`) returns `details.attachments[]` with everything the watcher needs — **no HTML scraping required**:

`url`, `title` (carries release number, publication date, and objection deadline), `filename`, `file_size`, `number_of_pages`, `content_type` (`application/pdf`), `id`, `asset_manager_id`, `accessible` (bool), `attachment_type`, `alternative_format_contact_email` (`press.office@otc.gov.uk`).

Three things fall out of this:

- **`accessible: false` is *not* a text-layer signal — do not wire it to the OCR alarm.** An earlier draft of this plan claimed it was, on the strength of 2 flagged attachments out of 32 in the North West. Measurement disproved it: of the 30 East of England releases captured, **19 are flagged `accessible: false` and all 30 have a perfectly good text layer**. The flag reports formal accessibility compliance (tagged PDF, reading order, alt text), not extractability. Wiring it to §5.3[2]'s alarm would have fired a false positive on 63% of the lead region's releases — the kind of noisy alarm that gets muted and then hides a real one. The pdfplumber probe is the only signal for `has_text_layer`.
- **Publication dates live in `change_history`, not on the attachment.** Parse the date from the attachment `title`, cross-check against `change_history`, and disagree loudly rather than guessing.
- **Only the current year is on the live page** (~32 attachments for NW in 2026); prior years are archived to the National Archives. Historical backfill (spec §11 Phase 3) must go through the National Archives, not the live page — and the live page will silently drop last year's releases on 1 January. Fetch and store everything you see, immediately.

Release numbers are **per-region sequential** (NW at 7167, Scotland at 2481), which validates the spec's `UNIQUE (source_id, release_no)` constraint and rules out a global sequence.

### 1.4 Model string is stale (§14 Q10)

`claude-sonnet-4-6` in §5.2 is a previous-generation model. Use **`claude-opus-5`** (1M context, adaptive thinking on by default). Note the API surface has moved on since the spec was written:

- `temperature` is **rejected** (400) on this model family. The spec's "temperature 0" instruction in §5.2/§6.1 cannot be implemented as written — determinism now comes from `output_config: {"effort": "low"}` plus a tight prompt, and from the verbatim guards, which are the real determinism mechanism anyway.
- Use structured outputs via `output_config.format` with the Appendix A schema, or `client.messages.parse()` with a Pydantic model. Do not use assistant prefill (400 on this model).
- Thinking is on by default; `max_tokens` caps thinking *plus* output, so size it generously.

**Cost sanity check at the corrected volume:** ~35 docs/month × ~20 pages × ~700 tokens/page ≈ 630k input tokens/month after chunk overlap, plus ~210k output. At Opus 5 rates ($5/$25 per Mtok) that is **~$9/month**, call it $15 with retries and golden-set CI runs. The spec's §5.3[3] instruction — "do not micro-optimise at the expense of accuracy" — is correct and now has a number behind it. Use the best model available.

### 1.5 Measured: volume per traffic area, prefix map, and the real section taxonomy

Measured directly by downloading the four most recent releases from each of the eight regions (32 PDFs) and counting. **Superseded by the full-2026-corpus measurement** once Stage 0 item 2 completed — the four-release sample ran high everywhere, but the ranking did not move, so no decision built on it changes.

**Distinct licence numbers per release** — the reliable proxy for lead volume:

| Traffic area | 32-PDF sample | Full 2026 corpus | Home-prefix share | Prefix |
|---|---:|---:|---:|---|
| **East of England** | 167.2 | **156.0** | 99.94% | `OF` |
| North East | 112.0 | 105.6 | 99.86% | `OB` |
| West of England | 94.5 | 99.7 | 99.81% | `OH` |
| West Midlands | 89.5 | 90.5 | 99.95% | `OD` |
| North West | 88.0 | 89.7 | 99.89% | `OC` |
| London & South East | 81.5 | 80.1 | 99.82% | `OK` |
| Scotland | 48.2 | 43.2 | 99.78% | `OM` |
| Wales | 32.2 | 36.2 | 99.62% | `OG` |

The full-corpus column is 270 releases (~34 per region) as at 30 Aug 2026 and moves a little each week as new releases land. `data/recon/licences.json` is the source of truth — regenerate with `haulier licences --all` rather than trusting this table to be current. Quote these numbers, not the 32-PDF sample.

**§14 Q2 answered — `licence_prefix_map` seeded empirically.** All eight prefixes are `O` + a region letter, exactly as tabulated above; cross-region contamination in the sample was 3 occurrences out of ~2,900 (incidental cross-references). The spec's `^[OP][A-Z][0-9]{6,7}$` regex holds. No `P`-prefixed (PSV) numbers appeared in any goods document, which also answers §14 Q3: **there are no combined goods+PSV documents** in this corpus.

**§14 Q3 answered, and the answer is much better than the spec feared.** The documents are not organised around drifting prose headings. They are organised around **statutory section references from the Goods Vehicles (Licensing of Operators) Act 1995**, and all eight regions use an identical scheme:

| Marker | Meaning | Maps to |
|---|---|---|
| `S13` | Consideration of new application under Section 13 | `NEW_APPLICATION`, `APPLICATION_GRANTED`, `APPLICATION_REFUSED` |
| `S17` | Consideration of variation application under Section 17 | `VARIATION_APPLICATION`, `VARIATION_GRANTED` |
| `S19` | Objection/representation received against variation application | context on an S17 |
| `S21` / `S23` | Consider attaching conditions | `OTHER` (rare) |
| `S26` | Disciplinary action under Section 26 | `REVOCATION`, `CURTAILMENT`, `SUSPENSION`, formal warning |
| `S27` | Disciplinary action under Section 27 (professional competence / TM) | `REVOCATION`, period of grace |
| `S28` | Disciplinary action under Section 28 | disqualification |

Critically, **the outcome sits on the same line as the marker**: `S13 - Application granted as applied for`, `S17 - Variation application refused`, `S26 - Licence curtailed to 4 vehicles and 3 trailers for a period of 8 weeks`, `S28 - CWM Transport Ltd and Carl Wood are disqualified indefinitely with immediate effect`. Variations frequently state the delta in prose — `The application to increase authority from 6 to 15 vehicles and trailers is granted` — which is exactly the ★★★ signal §4.1 wants.

Three consequences for the build:

1. **Event classification becomes largely deterministic.** Section marker plus outcome phrase yields the event type by rule, not by model judgement. The LLM's job narrows to field extraction. This makes the §7 "events wrongly typed ≤1%" gate much easier to hold, and it means a classification error is a rule bug — findable and fixable — rather than a model behaviour to be coaxed.
2. **The §13 "publication format changes silently" risk drops materially.** A statutory numbering scheme is far more stable than editorial headings, and it is uniform across all eight regions rather than per-region. The `section_heading_map` stays (outcome phrasing does vary) but its keys are now section numbers.
3. **Curtailments and variations carry explicit vehicle/trailer counts** in the outcome line, so `vehicles_delta` is often directly extractable rather than inferred from a prior state.

One caveat: Scotland showed no `S13` in its four-release sample. Almost certainly sampling noise at 48 licences/release rather than a real difference — confirm against the full backfill in Stage 0, do not assume.

**Method note:** a parallel attempt to count events per type by grepping marker frequency was measuring section *headings*, which appear once per section while records appear many times beneath them. Those numbers are not event counts and are not reported here. Distinct licence numbers per release is the measure that holds up; per-event-type volume needs the real segmenter, and lands in Stage 2.

### 1.6 No API spend during build — the extractor gets a pluggable backend

All development, golden-set labelling, prompt iteration, and testing run locally through Claude Code on the founder's Max subscription. No API key exists until Stage 4 at the earliest (§4, decision 4). This is a constraint that improves the design rather than compromising it:

```
extract/backends/
  claude_code.py    # shells out to `claude -p`, used for dev + labelling
  fixture.py        # replays cached responses keyed by chunk_hash — CI default
  api.py            # anthropic SDK; written at Stage 4 if chosen
```

- **Every model response is cached to disk** on first execution, keyed by `(prompt_version, chunk_hash)`. The golden-set regression suite then replays from `fixture.py` — offline, free, deterministic, and fast enough to run on every commit. That is what you want in CI regardless of who is paying for tokens.
- A prompt change invalidates its cache entries and forces a re-run through `claude_code.py`, which is exactly the "prompt changes require re-running the golden set" discipline §6.1 asks for. The cache key enforces it mechanically instead of by convention.
- The production backend decision is deferred to Stage 4 and costs nothing to defer, because the interface is needed either way.

Note that §6.1's "temperature 0" is unimplementable on the current model family (see §1.4). Determinism in practice comes from the fixture cache in CI, the verbatim guards at runtime, and `effort: low` on the extraction call — not from a sampling parameter.

---

## 2. Defects and gaps in the spec

Ordered by how much they change the build.

### 2.1 `deliveries` cannot represent the all-regions email

`UNIQUE (subscriber_id, publication_version_id)` assumes one delivery per publication. But §4.3 requires all-regions subscribers to get **one combined email covering several publications**. The schema can't express that.

Fix: separate the artefact from the send.

```sql
CREATE TABLE digests (             -- one rendered artefact set
  id uuid PK, kind text,           -- 'region_release' | 'daily_combined'
  cutoff_at timestamptz, csv_r2_key text, html_r2_key text,
  preference_signature text,       -- regions ∩ event_types, so identical filters share a render
  created_at timestamptz);

CREATE TABLE digest_publications (  -- many-to-many
  digest_id uuid REF digests, publication_version_id int REF publication_versions,
  PRIMARY KEY (digest_id, publication_version_id));

CREATE TABLE deliveries (
  id serial PK, subscriber_id int, digest_id uuid REF digests,
  postmark_message_id text, sent_at timestamptz, status text,
  UNIQUE (subscriber_id, digest_id));
```

`preference_signature` also removes the need to re-render per subscriber: at 80 subscribers most will share a handful of distinct filters.

### 2.2 `events` uniqueness collides on legitimate duplicates

`UNIQUE (licence_number, event_type, publication_version_id)` breaks when one licence has two events of the same type in one publication — two operating-centre variations, or a licence appearing twice in a section. The extractor would silently drop the second record, which is a **recall failure that the recall metric cannot detect** (the regex reconciliation in §5.3[3] counts occurrences, but the constraint discards after that check).

Fix: `UNIQUE (publication_version_id, licence_number, event_type, content_hash)`, and keep cross-release delivery dedupe on `(licence_number, event_type, content_hash)` as §5.3[5] already specifies.

### 2.3 Enrichment is keyed wrong

`enrichments` has `licence_number` as PK, so a company holding four licences gets its director blob stored four times and re-fetched four times against a rate-limited API. Split it:

```sql
CREATE TABLE companies (ch_company_number text PK, status text, incorporated_on date,
  directors jsonb, sic jsonb, registered_postcode text, fetched_at timestamptz);
CREATE TABLE licence_company_match (licence_number text PK REF licences,
  ch_company_number text NULL REF companies, match_confidence numeric, match_method text,
  is_sole_trader_or_partnership bool, matched_at timestamptz);
```

### 2.4 The verbatim-substring guard will false-fail constantly unless normalisation is shared

§5.3[3] and §6.4 make verbatim matching a hard requirement. pdfplumber output contains soft hyphens, ligatures (`ﬁ`), non-breaking spaces, line-break hyphenation, and inconsistent whitespace. A naive `value in source_block` check fails on correct extractions.

Fix: **one** `normalise()` function, applied to the text sent to the model *and* to both sides of every guard comparison. Unicode NFKC, collapse whitespace, strip soft hyphens, de-hyphenate across line breaks, casefold for name comparison only. This function is the single highest-risk piece of code in the system — it gets its own test file and property tests.

### 2.5 The record-count sanity check is not sound

`±10%` is meaningless for small blocks (with 3 records it rounds to exact match; with 40 it permits 4 missing records to pass silently). And a naive regex count over-counts: a licence number often appears twice in one entry (heading plus body notes).

Fix: count **distinct** licence numbers, and use `abs(llm_count - regex_count) <= max(1, ceil(0.05 * regex_count))`. Tighten from there once the golden set gives a real baseline.

### 2.6 The ≤24h SLO conflicts with the 100% human-review ramp gate

§7 requires publication→digest ≤24h with an alarm at 18h. §5.3[9] requires a human to review 100% of records for the first three clean cycles per region. At the corrected weekly cadence that is ~8 documents/week, ~35/month, perhaps 1,500 records/month during ramp. That is not compatible with a 24-hour clock or with "a few hours/week."

**Decision: all 8 regions live from day one with sampled QA** (§4, decision 1). The §5.3[9] 100%-review ramp gate is removed. This is the fastest route to the full product and it keeps the 24h SLO intact, but it means the first digests ship without every record having been read by a human — so the sampling has to be earned rather than assumed.

**It is earned by calibrating against the backfill, not against live customer data.** Decision 3 gives us ~250 historical 2026 documents. Before any subscriber exists, run the extractor across that whole corpus and hand-verify a stratified sample of it. That produces a measured per-field error rate on real documents from all eight regions, which is what sets the sampling rate. Launching with a sampler tuned to a number you measured beats launching with a guessed 25% and finding out from a customer.

Four things make sampled QA safe enough to ship on:

1. **Stratify by commercial cost, not uniformly.** Always review 100% of: `needs_review` records, records where a guard fired and the retry recovered, and any record from a section whose heading we are seeing for the first time. Then sample the ★★★ event types (`NEW_APPLICATION`, `VARIATION_*`, `APPLICATION_GRANTED`) hard and the ★ context types (`REFUSED`, `WITHDRAWN`, `PUBLIC_INQUIRY`) lightly. A wrong refusal record costs nothing; a wrong new-application record costs a customer.
2. **Risk-rank the queue.** Order the QA queue by a computed risk score (guard margin, extraction confidence, unusual field combinations, first-time heading, CH match failure) so the founder's limited review time lands on the riskiest records first rather than a random slice. This is the single biggest lever on making this choice work and it is cheap to build.
3. **Circuit breaker, independent of sampling.** A publication cannot reach `ready` if its guard-failure rate exceeds 2% of records, or if regex/LLM reconciliation is outside tolerance — regardless of what the sample said. Sampling decides how much gets read; the breaker decides whether anything ships.
4. **Weekly accuracy report.** The random audit sample feeds a running per-field accuracy number in the ops digest. If it drifts below the §7 gates, the sampling rate goes back up automatically.

### 2.7 All-regions batching has no defined cutoff

"One combined email per publication day" (§4.3) races the 6-hourly watcher. Define it: **a daily batch job at 17:00 Europe/London** covering everything that reached `ready` since the previous batch. Deterministic, testable, and gives QA a predictable daily window.

### 2.8 `first_seen_date` is actively misleading at launch

Every licence is "first seen" in the first publication processed, so in month one the field labels decade-old operators as new. This is precisely the error that destroys trust in a lead product — a salesperson calls a ten-year-old haulier as a "new operator."

Fix: seed `licences` from the data.gov.uk bulk register **before the first digest ships**. Any licence present in that snapshot gets `first_seen_date = NULL` and a `pre_existing = true` flag; only licences absent from the snapshot are genuinely new. This moves a slice of §11 Phase 3 into Phase 1, and it is worth it — it is the difference between a credible product and a plausible one.

### 2.9 The idempotency property test cannot pass as written

§10 asserts "run pipeline twice, DB state identical." It won't be — `events.id` is a random uuid and timestamps differ.

Fix: make event IDs content-addressed (`uuid5(NAMESPACE, publication_version_id + licence_number + event_type + content_hash)`). The test then becomes "identical modulo audit columns," which is real, and re-runs become genuinely idempotent rather than merely non-duplicating.

### 2.10 Section detection: statutory markers first, font metadata as fallback

§5.3[1] proposes a `section_heading_map` of raw heading strings, on the assumption that section names "vary by region and over time." The measurement in §1.5 shows the primary structure is actually the statutory `S13`/`S17`/`S19`/`S21`/`S23`/`S26`/`S27`/`S28` scheme, identical across all eight regions.

Segmentation therefore runs three detectors in priority order:

1. **Statutory marker regex** — `^\s*S(\d{1,3}[A-Z]?)\s*-\s*(.*)$`. Primary. Captures the section number and the outcome phrase in one match.
2. **Font/size outlier** — pdfplumber exposes per-character `fontname` and `size`; headings are typographically distinct. Catches structural boundaries that carry no S-number (the document preamble, operator-entry starts).
3. **`section_heading_map` lookup** — now keyed on section number with outcome phrasing as the varying part, rather than on free prose.

An unrecognised S-number, or a heading detected by (2) that matches neither (1) nor (3), routes its segment to QA and raises the format-change alarm — never guessed at. This is a stronger position than the spec assumed and meaningfully reduces the top-rated risk in §13.

### 2.11 Legal deliverables are sequenced too late

The LIA, privacy notice, and suppression route are in Phase 2 (§11), but the Phase 0 pilot digest already sends real directors' names to 15–20 prospects. Pull the privacy notice and a working objection inbox forward to Stage 0 — a one-page notice on a static URL costs an hour and removes the only genuinely uncomfortable risk in the plan.

Related: the **public sample digest** (§4.8) publishes named directors of real companies on an open URL. Redact directors to initials in the public sample. The pitch works fine without them, and it takes the sample out of scope for the most likely complaint.

### 2.12 Territory filtering needs postcode radius as well as traffic area

Buyers describe their patch differently depending on type — national brokers and finance houses think in regions, dealers and workshops think "within 60 miles of me" (§4, decision 2). The spec's `preferences.regions text[]` only supports the first. A Manchester dealer covering a patch that straddles North West and West Midlands is currently forced onto the £149 all-regions tier for two regions of value, or walks.

Support both, with region as the default:

```sql
ALTER TABLE preferences ADD COLUMN radius_filters jsonb;
-- [{"postcode": "M1 1AA", "miles": 60}, ...]

CREATE TABLE postcodes (            -- ONS Postcode Directory, OGL v3
  postcode text PRIMARY KEY,        -- normalised, no space
  lat double precision, lon double precision, region text);
```

A lead matches if **either** its traffic area is in `regions` **or** any of its operating centres falls inside any `radius_filters` entry. Requires the [ONS Postcode Directory](https://geoportal.statistics.gov.uk/) (free, OGL v3, ~2.6M rows — a static load, refreshed a couple of times a year).

**Amended by §4 decision 7:** the distance query was specified as `earthdistance`/PostGIS, and D1 has neither. It becomes a bounding-box prefilter in SQL (cheap, indexed on lat/lon) plus a haversine check in the Worker. At 2.6M postcodes and ~80 subscribers that is fine; at 10,000 subscribers it would not be, and that is the point to revisit the database.

Two consequences worth naming:

- **Operating-centre postcode becomes a first-class extracted field**, not best-effort. It is now load-bearing for delivery targeting, so it needs its own guard (matches the UK postcode regex *and* appears verbatim in the source block) and its own accuracy gate in the golden set. Add it to §7's SLO table at ≥98%.
- **Pricing tiers may need rethinking**, since "single region" stops being the natural unit for radius buyers. Defer to Phase 2 alongside the rest of the pricing question — but the schema supports it either way from Stage 1, which is the point of settling this now.

### 2.13 Smaller corrections

- **Stripe Tax / VAT:** at the target £5–8k MRR the business is well under the £90k UK VAT registration threshold. Don't register, don't enable Stripe Tax, revisit at £70k ARR. Removes a whole category of billing complexity from Phase 2.
- **Phase 0 pitch emails must not go via Postmark.** Twenty cold emails from a brand-new sending domain is the fastest route to a poor sender reputation, and it would poison the deliverability of the actual product later. Send them by hand from a normal mailbox. Postmark comes online in Stage 4 for internal digests, with SPF/DKIM/DMARC configured and a two-week warm-up before the first paying send.
- ~~**Managed Postgres, not self-hosted.**~~ **Superseded by §4 decision 7 — see INFRA.md.** The reasoning still holds (§9 mandates nightly backups plus a *weekly scripted restore test*, and on a side project that chore gets skipped by month two), but the conclusion does not: D1 has point-in-time recovery on the plan we are already paying for, which deletes the same runbook for £0 rather than ~£20/month. That £20 would have been twice the entire infrastructure budget.
- **Onboarding gap:** a subscriber who pays on day 2 of their region's week waits until day 8 for anything. Send the most recent already-published digest for their regions immediately on `checkout.completed`. One query, large churn effect.
- **Phase 0 is not "no product code."** Resolving URLs, pulling releases, cataloguing headings, and building a golden set all require a fetcher and a text extractor. Write them as real code (§3, Stage 0) — they become the watcher and fetcher rather than being thrown away.

### 2.14 Two columns missing from the §4.4 CSV contract

§4.4 fixes the CSV columns as "a stable API — additive changes only", but its own list omits two fields the rest of the spec relies on. Both are appended now, while the contract is still cheap to change and no subscriber has seen it.

- **`is_sole_trader_or_partnership`** — §4.2 lists it as a derived field and §8.4 asks for it "prominently in the CSV so customers can route those to phone/post rather than cold email". It is PECR-load-bearing: the whole point is that a subscriber must treat these leads differently. Derived three-state from `people_role` (the source names *directors* for a company and *partners* for a partnership), falling back to the operator name — a bare personal name is a sole trader, a legal-form or public-body token is not. Anything else stays **empty rather than guessed**, because an empty cell tells the subscriber to check while a wrong `no` invites them to cold-email an individual. On East of England 5599 that is 11 flagged, 113 corporate, 7 unknown — the unknowns being transport-manager public inquiries with no operator at all.
- **`operating_centre_postcodes`** — §2.12 promotes operating-centre postcode to a first-class field because radius filtering depends on it, but the CSV only had the `operating_centres` address blob, which cannot be filtered on. Pipe-separated, de-duplicated, in centre order.

A useful side effect: the transport-manager public inquiries that appear in a region's publication but are *held* elsewhere (Leeds, Warrington, Edinburgh, Belfast in 5599 alone) now carry an empty postcode column. Region filtering still includes them — they were published in that region, which is a fact — and radius filtering will naturally exclude them, which is the correct answer for a lead with no location in anyone's patch.

---

## 3. Build sequence

Six stages. Each has a hard exit criterion; nothing starts until the previous exit is met. Stage 0 and 1 are ordered so that the **sellable artefact exists before the pipeline does**, preserving the spec's sell-first discipline.

### Stage 0 — Recon toolkit + pilot digest (2–3 days)

Real code, kept. A `haulier recon` CLI that:

1. Pulls all 8 pages via the Content API, writes `sources` seed data and the observed cadence/weekday per region.
2. **Downloads every 2026 release on all 8 live pages — ~250 PDFs** (§4, decision 3) to R2 + local cache; records SHA-256, page count, and a pdfplumber text-layer probe; cross-checks against the `accessible` flag. This is time-critical: the live pages drop 2026 on 1 January, after which the same data costs a National Archives crawl.
3. Dumps per-page text with layout, extracts candidate headings by font-size outlier, and emits a frequency table of heading strings per region → seeds `section_heading_map`. With ~250 documents rather than 24, this seed is close to complete rather than indicative.
4. Regex-harvests every licence number seen → seeds `licence_prefix_map` with observed prefix→region mapping, and validates (or corrects) the `^[OP][A-Z][0-9]{6,7}$` assumption against real data.
5. Loads the ONS Postcode Directory into `postcodes` (§2.12).

Then, by hand plus Claude: take one busy region's latest release, extract every record, verify all of them personally, and render the pilot digest HTML + CSV. This is the sales asset.

In parallel: register the Companies House API key, read the VOL terms, confirm the data.gov.uk register dataset's freshness/columns/licence, publish the privacy notice and objection inbox.

**Exit:** pilot digest sent to 15–20 targets at the **£49/mo founding rate** (§4, decision 6 — a named, time-limited price, not the list price); ≥3 verbal yeses. Kill criterion evaluated honestly. All of §14 Q1–Q9 answered in writing.

### Stage 1 — Skeleton, data model, golden-set harness (week 1)

Repo, Docker Compose, Alembic, SQLAlchemy models (with the §2.1–2.3 schema corrections), config, secrets, CLI scaffolding, CI.

Then the golden-set harness **before the extractor**, so the extractor is developed against a measurable target rather than eyeballed. Draw the fixtures from the Stage 0 backfill, stratified so all eight regions and every distinct section heading are represented. Hand-label 100–150 records covering the nasty cases (records split across pages, hyphenated names, `T/A` trading names, multiple operating centres, variations with deltas, and operating-centre postcodes per §2.12) rather than chasing the spec's 300–600 — labelling is the scarce resource, and coverage of hard cases beats volume. Label via Claude Code and adjudicate every disagreement by hand; that is where the real errors surface.

Also in this stage: the backend interface and fixture cache from §1.5, so labelling output is captured for CI replay from the first record onward.

**Exit:** `pytest` runs the golden set against a stub extractor and reports precision/recall per field. Numbers are wrong; the harness is right.

### Stage 2 — Watcher → Fetcher → Segmenter → Extractor (week 2)

The crown jewels, in dependency order. Content-API watcher (6-hourly), fetcher with versioning and supersede handling, font-aware segmenter, the shared `normalise()` function with its own test suite, LLM extraction against the Appendix A schema, and the four post-parse guards with the §2.5 corrected reconciliation.

**Exit:** golden-set gates met — licence-number precision ≥99.5% / recall ≥99%, operator name ≥97%, event type ≥99%, numerics ≥99%, operating-centre postcode ≥98% (§2.12). CI blocks below these.

### Stage 3 — Validator, resolver, enricher, QA UI (week 3)

Field rules and cross-source checks against the bulk register; the §2.8 pre-existing-licence seed; entity resolution with content-addressed event IDs; the Companies House enricher (nightly batch, `manual_overrides` wins); and the QA review UI — side-by-side source block vs extracted fields, one-click accept/edit/reject, **ordered by the §2.6 risk score**.

Build the QA UI before the digest generator. It is the gate on everything downstream and the thing the founder will spend the most time in; discovering it is slow in week 5 is expensive.

**Then the calibration run — the piece that makes sampled QA defensible.** Extract the entire ~250-document 2026 backfill, review a stratified sample through the QA UI, and measure the real per-field error rate across all eight regions. That number sets the launch sampling rate and the risk-score thresholds. It happens before any subscriber exists, on data nobody is waiting for, which is the whole reason decisions 1 and 3 work together.

It also produces two things you cannot get any other way: a near-complete `section_heading_map` (250 documents of heading variation instead of 24), and ~8 months of `first_seen_date` history so that §2.8's pre-existing-licence detection has real observations behind it rather than only a bulk-register flag.

**Exit:** backfill fully extracted and calibrated; measured accuracy meets the §7 gates; sampling rate and risk thresholds recorded in config with the evidence behind them.

### Stage 4 — Digest generator, sender, monitoring (week 4)

Jinja + premailer templates (mobile-first, inline CSS, plain-text alternative), the stable CSV contract from §4.4, R2 artefact storage, Postmark with idempotency keys and the §2.7 daily cutoff. Subscriber matching implements **both** territory filters from §2.12 (region membership OR operating-centre postcode within radius). Heartbeats on every cron job, the alarm set from §5.3[8] with the corrected 14-day silence threshold, plus the §2.6 circuit breaker and weekly accuracy report, Sentry, dead-man's-switch, weekly ops digest.

Decide the production extraction backend here (§1.5, §4 decision 4) — by this point the real volume, latency, and failure profile are known, which is what makes it an informed decision rather than a guess.

Write the six runbooks now, while the failure modes are fresh.

**Exit (spec §11 Phase 1 exit, corrected):** two consecutive real weekly cycles across **all 8 regions** processed to `ready`, SLOs met, internal digest indistinguishable from the hand-made pilot.

### Stage 5 — Commercialisation (weeks 5–6)

Stripe products, Checkout links, webhooks, delivery gating on subscription status; magic-link preferences page; suppression handling wired into render; the static landing site (plain HTML on Cloudflare Workers Static Assets — same vendor as R2; **built already, see §4 decision 9**) with the redacted sample issue, FAQ, and legal pages; onboarding email with the lawful-use note and immediate back-issue send.

**Exit:** ≥3 paying subscribers on automated delivery. Kill criterion evaluated honestly.

### Suggested repo layout

```
haulier/
  pyproject.toml            docker-compose.yml       alembic/
  src/haulier/
    config.py  cli.py                     # typer; every stage runnable standalone
    db/                                   # models, session
    sources/                              # GOV.UK Content API client + registry
    watcher/  fetcher/                    # R2, SHA-256, pdfplumber probe
    extract/
      segment.py                          # font-aware sectioniser
      normalise.py                        # THE shared normalisation fn
      llm.py  guards.py  prompts/         # versioned prompt files
    validate/  resolve/  enrich/
    digest/                               # templates, CSV writer
    billing/  admin/  monitoring/
  golden/                                 # (source_block, expected_records[])
  site/                                   # static landing + sample digest
  runbooks/  tests/
```

Every stage is a CLI subcommand and a cron entry. No queue, no workers, no orchestrator — the spec is right that this is a small system, and the corrected volume (~35 documents/month) does not change that.

---

## 4. Decisions taken

1. **Ramp: all 8 regions live from day one, sampled QA.** The 100%-review gate in spec §5.3[9] is removed; the 24h SLO stands. Safety comes from calibrating the sampler against the Stage 0 backfill before launch, plus stratified sampling, a risk-ranked queue, and a guard-rate circuit breaker (§2.6).
2. **Territory: support both region and postcode-radius filtering**, region as the default (§2.12). Operating-centre postcode is promoted to a gated extraction field. List prices stay at £79/£149 for now and are revisited in Phase 2 once 20 sales conversations have happened — the schema supports either shape. The £49 pitched at Stage 0 is the founding rate, not a third tier (decision 6).
3. **Backfill: capture all 2026 releases from the live pages during Stage 0** — ~250 PDFs. Doubles as the calibration corpus, the heading-map seed, and 8 months of `first_seen_date` history. National Archives backfill for 2024–25 stays in Phase 3.
4. **Production extraction backend: decided at Stage 4.** Build and test run locally on the Max subscription with a fixture cache for CI (§1.5); no API key exists before then.

5. **Lead region: East of England** (`OF`). Measured over the full 2026 corpus at **~156 distinct licences per release** — 1.5× the next region, 1.7× the median, 4× Wales (§1.5). The traffic area covers Leicestershire, Northamptonshire, Lincolnshire, Bedfordshire, Buckinghamshire, Cambridgeshire, Hertfordshire, Essex, Norfolk and Suffolk, plus Leicester, Luton, Milton Keynes, Peterborough, Rutland, Southend-on-Sea and Thurrock — i.e. the Midlands "golden triangle" logistics corridor, the Thames Gateway, and the Felixstowe hinterland. Both the volume and the geography point the same way. Pilot digest, golden set, and first sales conversations all start here.

   Tradeoff accepted: East of England is also the heaviest QA load per release. That is the right way round — prove the accuracy gates on the hardest region and every other region is easier.

6. **£49 is the founding rate, £79 is the list price.** Stage 0 pitches £49/mo to the first cohort — spec §2.5's kill criterion, §11 Phase 0 and §14 Q8 all already read it that way ("founding price acceptance at £49 → confidence in £79/£149 list"). PLAN §3's exit criterion said only "£49/mo", which reads as the price, so it is now named explicitly. Terms: **the first 10 subscribers, locked for 12 months**, in exchange for testimonials and feedback calls (spec §1); after that, and for everyone else, the list price applies.

   One number to reconcile before Stripe is configured: spec §4.6 defines `founding_*` as **50% off**, which is £39.50 against a £79 list, not £49. £49 is 62% of list. Either the founding products are priced at £49 flat (and §4.6's "50%" is prose to fix) or they are £39.50 (and every "£49" in the spec is wrong). **Decision: £49 flat**, because it is the number in the kill criterion and the one the pitch will actually quote. §4.6's `founding_*` should read "≈62% of list, priced at £49 / £99" rather than "50%".

7. **Platform: Cloudflare, with D1 replacing Postgres for V1.** Costed at **$9.56/month** all-in against a $10 target (INFRA.md, 30 Aug 2026). Workers Paid is the only fixed cost at $5; R2, D1, Cron Triggers, Static Assets and Email Routing all sit inside free tiers at this scale, and the domain is ~$0.85 at Registrar's at-cost pricing.

   This overrides spec §5.2's "Postgres 16, SQLAlchemy + Alembic" and §2.13's managed-Postgres bullet. The written reason spec §5.2 asks for: a managed Postgres at ~£20/month is **twice the entire infrastructure budget**, and at 80 subscribers and ~4,500 events a month, D1's free tier (5 GB, 5M row reads/day) is not remotely stretched. D1 keeps SQLAlchemy usable and keeps PITR, so the §9 backup guarantee survives.

   What it costs us: no PostGIS (see §2.12 as amended), and SQLite's type affinity rather than Postgres types — so the §2.1–2.3 schema fixes need `TEXT`-encoded uuids and explicit `CHECK` constraints where Postgres would have given us native types. **Revisit at ~10,000 subscribers or when the radius query stops being fast**, not before.

8. **Email: Resend at launch, not Postmark.** Spec §5.2 mandates Postmark; its cheapest paid plan is **$15/month**, which breaks the budget on its own, and its free tier is 100 emails/month against a measured need of ~260 at 20 subscribers and ~1,030 at 80. Resend's free tier is 3,000/month (100/day), which covers roughly 150 subscribers. Amazon SES at $0.10/1,000 is the scale-up.

   This is a cost decision, not a quality judgement — Postmark's deliverability reputation is worth paying for once there is a business to protect, and moving back is a one-file change if the sending domain has been warmed properly. **§2.13's rule is untouched: Phase 0 pitch emails go by hand from a normal mailbox, through none of these.**

9. **The pipeline splits at the text-dump cache, because Python Workers cannot run pdfplumber.** Cloudflare's Python Workers run on **Pyodide** — pure-Python and PyEmscripten wheels only. `pdfplumber` → `pdfminer.six` → `cryptography` (Rust) and `pypdfium2` (native C). This is a packaging boundary, not a configuration problem, and **no future session should spend time trying to configure around it.**

   It costs less than it sounds, because `haulier dump` already caches per-page text at `data/text/{region}/{release}.json.gz` keyed by the PDF's SHA-256 — which is exactly the right seam. PDF→text runs in a Cloudflare Container on the existing image; everything downstream (heading analysis, licence harvest, LLM extraction, lead normalisation, digest and CSV rendering) is JSON and Jinja2, and runs on Workers unmodified.

   Measured: **0.79 s per release, 41 ms/page** over 8 sampled releases — 28 vCPU-seconds/month ongoing, against the **375 vCPU-minutes** Workers Paid already includes. That is 0.13% of the allowance. Containers are effectively free here; the $5 plan fee is the whole cost. Use a `basic` instance (¼ vCPU, 1 GiB); nothing measured justifies larger.

10. **Extraction model: costed, still not decided** — decision 4 stands, and Stage 4 still owns the call. The numbers now exist so it is an informed one. At 35 releases/month, ~11.7k input and ~18.9k output tokens each: Haiku 4.5 $3.71/mo standard, Sonnet 5 $7.42, Opus 5 $18.55; Batch API halves each.

    One structural finding worth carrying forward: **output tokens dominate** (660k out against 410k in), because the extracted JSON *is* the product. So prompt caching — normally the first cost lever — saves about $0.20/month here. Model choice is the lever.

    A useful coincidence: Haiku 4.5 on the standard API costs the same as Sonnet 5 on batch ($3.71), but returns synchronously. The Batch API's 24-hour window would consume the whole of spec §7's 24-hour SLO, which alarms at 18 — so **batch is right for the one-off backfill (~$14.31) and wrong for the weekly cycle.**

    **Do not let the $10 target pick the model.** Spec §7 gates extraction at ≥99.5% licence-number precision; whether Haiku 4.5 clears that is a golden-set question for Stage 1. If it does not, Sonnet 5 puts us $3.27 over budget, which against three subscribers at £49 is a rounding error.

### Still open

- **Pricing tier shape** (§2.12) — whether radius buyers need a unit between "one region" and "all regions". Phase 2, informed by Phase 0 conversations.
- **Whether the "grew 3→11 vehicles" time series is a launch pitch or a Phase 3 feature** — determines whether the National Archives crawl gets pulled forward.
