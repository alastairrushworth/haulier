# Progress — FirstMover

Working log for picking up between sessions. Companion to `PLAN.md` (build plan)
and `spec.md` (product spec), plus `INFRA.md` (what it costs to run).
Last updated: **1 Sep 2026**.

## Where we are

**Stage 0 (recon + pilot digest) — code complete and under test; the exit gate is
now founder work.**

## Done to date

### Recon toolkit (committed `f31e0ed`)
- `haulier` CLI: `areas` / `releases` / `capture` / `status` / `probe` over the
  GOV.UK Content API. Capture is idempotent, fingerprints SHA-256, probes text layer.
- Full 2026 corpus captured: **275 goods releases, all 8 regions** as at 1 Sep.
  That number moves every week — five landed in the two days after the 30 Aug
  capture — so trust `haulier status` over this line, and run
  `haulier capture --all` before quoting a figure anywhere.

### Corpus analysis (committed `dbe732d`)
- `haulier dump` — cached per-page text extraction (line + font size + bold),
  keyed by PDF SHA-256, parallel workers. Cache in `data/text/`.
- `haulier headings` — S-marker + font-outlier heading frequency tables
  → `data/recon/headings.json` (the `section_heading_map` seed).
- `haulier licences` — full-corpus licence harvest → `data/recon/licences.json`.
  **Regex `^[OP][A-Z]\d{6,7}$` and the prefix→region map validated**: home-prefix
  share ≥99.6% in all 8 regions; near-misses are company/case numbers, not
  missed licence formats. Full-corpus means in README (EoE lead at ~156/release).

### Pilot digest (committed `5b367ad`)
- All **131 records extracted from East of England AD-5599** (5 Aug 2026) via
  parallel Claude subagents → `data/pilot/records.json`. Reconciliation: all 122
  distinct licence numbers in the source accounted for, nothing extracted that
  isn't in the source.
- `src/haulier/digest/`: lead normalisation (fleet parsing, postcode/town,
  content-addressed event ids), spec §4.4 CSV, heat-ordered mobile-first HTML.
- `haulier render-digest` (+ `--redact` for the public sample).
  Subject: "[East of England] 25 new operators, 27 expansions — A&D 5599".

### Review pass and fixes (30 Aug 2026)

A full review of the Stage 0 code found five correctness bugs, two contract gaps
and no tests at all. All are now fixed, each with a regression test.

**Bugs fixed**

1. **`event_id` collisions.** The content key was
   `release|section|licence|event_type|operator|notes` — no `content_hash`, so
   it reproduced the exact defect PLAN §2.2 warns about. AD-5599 carried two
   DPDGROUP variations on `OF0217601` differing only in which centre changed;
   they hashed identically, and any dedupe on `event_id` would have dropped a
   50-vehicle/32-trailer expansion. **A recall failure the recall metric cannot
   see**, because reconciliation counts licence numbers before dedupe happens.
   Now `uuid5(ns, release|licence|event_type|sha256(canonical record))` per
   PLAN §2.9. All 131 ids are distinct. **Every pilot event_id changed** — fine
   pre-launch, nobody has seen them.
2. **`--redact` leaked nine full names** into the public sample, in both HTML
   and CSV, through three channels the old code didn't touch: TM public-inquiry
   `notes` name the individual in free text; a sole trader's or partnership's
   `operator_name` *is* a personal name; and their `correspondence_address` is
   usually a home address. Redaction now scrubs known names out of every
   free-text field, initialises non-corporate operator names structurally
   ("Wyndham & Partners" → "W. & Partners" — a partnership name need not
   contain any partner's full name), and reduces non-corporate addresses to
   town + postcode. Verified: 288 names checked, zero leaks. Registered company
   names survive intact — no over-redaction.
3. **`Sch.3` was invisible to the marker taxonomy.** `MARKER_RE` anchored on
   `S<digit>`, so it could not match `Sch.3 - Consideration of Transport
   Managers Repute` — which is the **most frequent marker in the whole corpus**
   (252 occurrences across 30 of 31 EoE releases, present in all 8 regions) and
   was entirely absent from the segmenter seed. Now recognised everywhere.
4. **One bad PDF sank a whole `capture --all` run.** A `probe_pdf` exception
   escaped before `write_manifest`, losing that region's manifest and skipping
   every region after it. Faults are now isolated per release: a probe error is
   recorded on the row, a fetch failure is reported and the previous row
   carried forward.
5. **A re-issued PDF was invisible.** Capture checked existence, not bytes,
   despite the docstring claiming digest matching — so spec §5.3[2] supersede
   handling and the §7 corrections SLO had no input at all. Now compares the
   Content API's advertised `file_size` and records `superseded_sha256` when
   the bytes change. `--refresh` forces a full re-download for same-length edits.

Smaller: `town_of` rendered `KING'S LYNN` as "King'S Lynn"; the client retried
4xx (a 404 cost three backoffs); `capture` now exits non-zero when anything
needs a human, so it is safe to cron.

**Contract gaps closed** (PLAN §2.14 — additive, columns appended)

- **`is_sole_trader_or_partnership`** — required by spec §4.2 and §8.4
  ("prominently in the CSV") but missing from §4.4's own column list. It is
  PECR-load-bearing. Three-state, derived from `people_role` first and the
  operator name second; **unknown stays empty rather than guessed**, because a
  wrong `no` invites a subscriber to cold-email an individual. On 5599: 11 yes,
  113 no, 7 unknown (the TM inquiries with no operator).
- **`operating_centre_postcodes`** — PLAN §2.12 makes this load-bearing for
  radius filtering, but it was buried in the address blob. Draws from
  `variation_changes` as well as `operating_centres`: 51 of 131 leads state
  their only location in the former, and they are all expansions. Locatable
  leads went 35 → 86 of 131; the remaining 45 are surrenders, revocations,
  withdrawals and inquiries where the source genuinely names no centre.
- Side effect: the TM public inquiries published in one region but *held*
  elsewhere (Leeds, Warrington, Edinburgh, Belfast in 5599 alone) now carry an
  empty postcode. Region filtering still includes them, correctly — they were
  published in that region. Radius filtering will exclude them, also correctly.

**Legal (PLAN §2.11, pulled forward)** — the digest footer now carries a
**working objection route** (defaults to the contact address, so it works from
the first send), the legitimate-interests basis, a privacy-notice link when
`HAULIER_PRIVACY_NOTICE_URL` is set and honest prose when it isn't, and the
PECR note pointing subscribers at the sole-trader column.

**Tooling and CI** — `tests/` now exists (was `testpaths = ["tests"]` pointing
at nothing; `pytest` exited 5). 87 tests, none touching the network. mypy
`strict` is green on `src` **and** `tests` for the first time — fixing it
surfaced that `capture_area` was welded to the concrete `GovUkClient`, now a
`ReleaseSource` protocol. `ruff format` adopted with `# fmt: off` guards around
the hand-compacted CSV/heat literals. GitHub Actions CI runs lint, format,
types and tests. `.env.example` added.

Corpus tests skip when `data/` is absent, so CI is green on a fresh clone; the
same regressions are pinned against `tests/fixtures/release_sample.json`, a
synthetic release with invented names carrying every awkward shape in the real
corpus (the double-variation collision, a TM inquiry naming someone in `notes`,
a sole trader, a partnership, a council, an ambiguous trade name).

### Infrastructure decided and priced (1 Sep 2026) — `INFRA.md`

The backend runs on **Cloudflare**, costed at **$9.56/month** all-in against a
$10 target. Workers Paid ($5) is the only fixed cost; R2, D1, Cron Triggers,
Static Assets and Email Routing are all inside free tiers at this scale.
Recorded as PLAN §4 decisions 7–10. Four things a future session should not
have to rediscover:

1. **Python Workers cannot run pdfplumber** — they are Pyodide, so pure-Python
   and PyEmscripten wheels only, and pdfminer.six pulls in `cryptography` (Rust)
   plus `pypdfium2` (C). This is a packaging boundary, not a config problem.
   **Do not spend time trying to work around it.** The pipeline splits at the
   existing `data/text/` cache instead: PDF→text in a Container, everything
   downstream on Workers unmodified. Measured at 0.79 s/release, that container
   step uses 0.13% of the 375 vCPU-minutes the $5 plan already includes.
2. **D1 replaces Postgres for V1**, overriding spec §5.2 and PLAN §2.13. A
   managed Postgres at ~£20/mo is twice the whole budget. Cost: no PostGIS, so
   §2.12's radius filter becomes a bounding-box prefilter plus a haversine check
   in the Worker — fine at 80 subscribers, not at 10,000.
3. **Resend, not Postmark**, whose cheapest paid plan is $15/mo. §2.13's rule is
   untouched: the Phase 0 pitch emails still go by hand from a normal mailbox.
4. **Extraction model costed but still undecided** (decision 4 stands). Output
   tokens dominate, so prompt caching saves ~$0.20/mo and model choice is the
   lever. Batch is right for the one-off backfill (~$14.31) and wrong for the
   weekly cycle, because its 24-hour window eats the whole §7 SLO.

### Landing site built (1 Sep 2026)

`haulier build-site [--serve]` renders the spec §4.8 site — landing page,
privacy notice, terms, and the redacted 5599 sample — as plain HTML with no
framework. Output is gitignored; rebuild it rather than reading `site/dist/`.

Every service that would cost money is a placeholder, and **the dry-run state is
deliberately loud**: while any placeholder is unresolved the build carries a
banner naming the missing env vars, badges each stub link, and sets `noindex`.
Set the three `HAULIER_CHECKOUT_*_URL` vars and it clears itself — there is no
separate production flag to forget to flip.

The privacy notice is a real draft, not filler: Article 14 basis (we did not get
the data from the subject), both sources named, legitimate interests, and a
working objection route. **It still needs a solicitor**, and the page says so
while `dry_run` is true. This discharges most of PLAN §2.11's Stage 0 blocker.

### Findings that changed the plan (see also PLAN.md §1–2)
1. **Title format drifted live on 5 Aug**: `AD_6720` (underscore) alongside
   `AD - 6720`. Parser accepts both. No unparsed titles in the 30 Aug refresh.
2. **PSV (NP) documents stray onto goods pages** (Scotland, West Midlands).
   Stream membership = `AD`/`NP` title prefix, not the page. Capture filters NP.
3. **Documents are two-level**: numbered sections ("Section 1 – Applications
   Received" … "Section 9 – Corrections") identical across all 8 regions, with
   statutory S-markers only inside decision sections. **New applications carry
   no S-marker** — PLAN §1.5's S13→NEW_APPLICATION mapping was incomplete.
   `Sch.3` is in every region and is the most frequent marker of all; rare
   S14/S19/S21/S23/S24/S25/S30/S36 also occur.
4. **Deltas need history**: the source states only the *new* authorisation, so
   "3 → 7 vehicles" requires licence state (arrives with the Stage 3 backfill).
   Pilot digest carries per-centre change text instead; CSV delta columns empty.
5. **£49 is the founding rate, not the list price** (PLAN §4, decision 6). Note
   spec §4.6 defines `founding_*` as 50% off, which is £39.50 against a £79
   list — £49 is 62%. Decided: **£49 flat**; §4.6's "50%" is the prose to fix
   before Stripe is configured.

## Next up

### Founder tasks (Stage 0 exit gate — nothing ships until these)
- [ ] **Verify all 131 pilot records by hand** — open `data/pilot/digest_5599.html`
      beside `data/raw/the-east-of-england/5599/*.pdf`. Licence reconciliation
      passed but field-level errors are what this check is for.
- [ ] **Cut the pitch digest on release 5602** (26 Aug, objection deadline
      16 Sep). 5599's deadline expired on 26 Aug, so it is the wrong artefact to
      pitch — but it is the *right* public sample, which spec §4.8 wants ≥2
      weeks old. 5602's PDF is captured; it needs the extraction pass.
- [ ] Companies House API key; read VOL terms; confirm data.gov.uk bulk register
      dataset (freshness/columns/licence).
- [ ] **Get the privacy notice and terms reviewed**, then deploy the site and set
      `HAULIER_PRIVACY_NOTICE_URL`. Both are drafted (`haulier build-site`) and
      describe what the system actually does; neither has seen a solicitor.
      Confirm the objection inbox is monitored — the digest footer already
      links a working route (PLAN §2.11).
- [ ] Send pilot digest to 15–20 targets at the **£49/mo founding rate** — first
      10 subscribers, locked 12 months — by hand from a normal mailbox (NOT
      Postmark, PLAN §2.13). **Exit: ≥3 verbal yeses.**

### Code tasks (next session)
- [ ] **ONS Postcode Directory load** (Stage 0 item 5, PLAN §2.12) — ~2.6M rows
      from geoportal.statistics.gov.uk, needed for radius filtering. Decide
      interim storage (no Postgres yet — sqlite/parquet until Stage 1). The
      `operating_centre_postcodes` column is now populated and waiting on it.
- [ ] **Stage 1**: repo hardening (Docker Compose, Alembic, SQLAlchemy models with
      PLAN §2.1–2.3 schema fixes), then the **golden-set harness before the
      extractor** — seed fixtures from the verified 131 pilot records plus
      stratified draws from the ~275-release backfill. Backend interface +
      fixture cache per PLAN §1.6. `tests/` and CI exist now, so the harness
      has somewhere to land.
- [ ] Keep `haulier capture --all` running weekly (releases drop off the live
      pages on 1 Jan; capture is cheap, idempotent, and now exits non-zero when
      something needs looking at, so it can go straight into cron). It was 5
      releases behind after just two days, so this is the first thing to run
      when picking the project back up.
- [ ] **Stand up the Cloudflare account** when Stage 1 starts — Workers Paid,
      R2 bucket, D1 database, one Container, two Cron Triggers, Email Routing.
      Order and rationale in `INFRA.md`.

### Standing risks / watch items
- Weekly title-format drift is real (seen once already) — `releases` prints a
  red warning on unparsed titles and `capture` exits non-zero; treat it as an
  alarm, not noise.
- Scotland S13 scarcity (5 releases of 30) still unexplained — check against
  the full backfill during Stage 2/3 calibration.
- The heading frequency table is a raw table, not a map: EoE alone yields ~1,500
  entries, heavily polluted by the appeals boilerplate that the font-outlier
  detector reads as six separate headings. Curating it into `section_heading_map`
  is undone work, and belongs with the Stage 2 segmenter.
- `_TRADE_TOKENS`/`_CORPORATE_TOKENS` in `digest/leads.py` are heuristics for
  entity typing. They are right on all 131 pilot records, but they are word
  lists — revisit against the backfill when the golden set exists.
