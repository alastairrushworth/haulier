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

Stage 0 (recon and corpus capture). Not yet a running pipeline.

## Quickstart

```bash
uv sync
uv run haulier areas                 # the eight traffic areas and their sources
uv run haulier releases              # releases live on the lead region's page
uv run haulier capture               # download + fingerprint the lead region
uv run haulier capture --all         # all eight areas (~250 PDFs)
uv run haulier status                # what has been captured locally
```

Captured documents land in `data/` and are gitignored — they are public data under the Open
Government Licence and fully reproducible from GOV.UK, so the canonical copy belongs in
object storage rather than the repo.

## What has been established

Measured against live GOV.UK data rather than assumed (details in `PLAN.md` §1):

| Traffic area | Licences/release | Prefix |
|---|---:|---|
| East of England *(lead)* | 167.2 | `OF` |
| North East England | 112.0 | `OB` |
| West of England | 94.5 | `OH` |
| West Midlands | 89.5 | `OD` |
| North West England | 88.0 | `OC` |
| London & South East | 81.5 | `OK` |
| Scotland | 48.2 | `OM` |
| Wales | 32.2 | `OG` |

- Publication is **weekly** per region on region-specific weekdays, not fortnightly.
- Releases are PDFs, discoverable through the GOV.UK Content API — no HTML scraping.
- Documents are structured around **statutory section references** (`S13` new application,
  `S17` variation, `S26`/`S27`/`S28` disciplinary), identically across all eight regions.
- Only the current year stays on the live pages; earlier years move to the National Archives.

## Attribution

Contains public sector information licensed under the
[Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/).
