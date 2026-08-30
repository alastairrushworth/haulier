# FirstMover

Turns the UK Traffic Commissioners' weekly *Applications & Decisions* (A&D) publications
into a clean, enriched, territory-filtered sales-lead feed for companies that sell to road
hauliers.

When a business applies for a goods vehicle operator licence, it signals — roughly nine
weeks before trucks are on the road — that it is about to buy vehicles, finance, insurance,
fuel cards, telematics and compliance services. That signal is public but buried across
eight regional PDF streams. This reads them, structures them, enriches them with Companies
House data, and delivers a digest plus CSV filtered by territory and event type.

- **`spec.md`** — the product and system specification.
- **`PLAN.md`** — build plan, verified Phase 0 findings, and corrections to the spec.

## Status

Stage 0 (recon, corpus capture, pilot digest). Not yet a running pipeline.

The full 2026 corpus is captured — **270 releases across all eight regions**. The
pilot digest (East of England release 5599, 5 Aug 2026, 131 leads) renders from
`data/pilot/records.json`; the extraction reconciles 1:1 against every licence
number in the source PDF but still needs a human verification pass before it is
sent to prospects (PLAN.md Stage 0 exit).

## Quickstart

```bash
uv sync
uv run haulier areas                 # the eight traffic areas and their sources
uv run haulier releases              # releases live on the lead region's page
uv run haulier capture               # download + fingerprint the lead region
uv run haulier capture --all         # all eight areas (~270 PDFs)
uv run haulier capture --all --refresh  # re-download and compare digests (re-issue check)
uv run haulier status                # what has been captured locally
uv run haulier dump --all            # extract + cache per-page text (idempotent)
uv run haulier headings --all        # heading frequency table → section_heading_map seed
uv run haulier licences --all        # licence-number harvest → regex + prefix-map validation
uv run haulier render-digest         # render digest HTML + CSV from data/pilot/records.json
uv run haulier render-digest --redact  # public-sample variant, people redacted to initials
```

`capture` exits non-zero if anything needs a human: an unparsed title (format drift), a
release re-issued at source, an unreadable PDF, a missing text layer, or a failed fetch.
It is safe to run from cron and safe to re-run — unchanged releases are not re-fetched.

Captured documents land in `data/` and are gitignored — they are public data under the Open
Government Licence and fully reproducible from GOV.UK, so the canonical copy belongs in
object storage rather than the repo.

## Development

```bash
uv sync
uv run ruff check src tests && uv run ruff format --check src tests
uv run mypy src tests            # strict
uv run pytest -q
```

Copy `.env.example` to `.env` to override anything in `src/haulier/config.py` — notably
`HAULIER_OBJECTION_EMAIL` and `HAULIER_PRIVACY_NOTICE_URL`, which the digest footer needs
(PLAN.md §2.11).

No test touches the network. Tests that read the captured corpus skip when `data/` is
absent, so CI runs green on a fresh clone; the regressions they cover are also pinned
against `tests/fixtures/release_sample.json`, a synthetic release carrying every awkward
shape found in the real corpus with invented names.

## What has been established

Measured against live GOV.UK data rather than assumed (details in `PLAN.md` §1):

Distinct licence numbers per release, measured over the full 2026 corpus (270
releases, ~34 per region, as at 30 Aug 2026; home-prefix share is ≥99.6%
everywhere). Re-measure with `haulier licences --all`:

| Traffic area | Licences/release | Prefix |
|---|---:|---|
| East of England *(lead)* | 156.0 | `OF` |
| North East England | 105.6 | `OB` |
| West of England | 99.7 | `OH` |
| West Midlands | 90.5 | `OD` |
| North West England | 89.7 | `OC` |
| London & South East | 80.1 | `OK` |
| Scotland | 43.2 | `OM` |
| Wales | 36.2 | `OG` |

- Publication is **weekly** per region on region-specific weekdays, not fortnightly.
- Releases are PDFs, discoverable through the GOV.UK Content API — no HTML scraping.
- Documents have a **two-level structure**, identical across all eight regions: numbered
  top-level sections ("Section 1 – Applications Received" … "Section 6 – Operating Centre
  Reviews"), with **statutory markers** (`S13` new application, `S17` variation,
  `S26`/`S27`/`S28` disciplinary, `Sch.3` transport-manager repute) nested inside the
  decision sections. New applications carry no statutory marker — they live in Section 1.
- Stream membership comes from the **`AD`/`NP` title prefix, not the page** — PSV documents
  occasionally stray onto the goods pages. Title separators drift (`AD - 6720` / `AD_6720`).
- Only the current year stays on the live pages; earlier years move to the National Archives.

## Attribution

Contains public sector information licensed under the
[Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/).
