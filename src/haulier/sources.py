"""The eight GB traffic areas and their Applications & Decisions publication sources.

Slugs and licence-number prefixes are confirmed empirically against live GOV.UK
data (see PLAN.md §1.5) rather than assumed from spec.md. The prefix mapping was
derived by counting licence numbers across 32 real releases; cross-region
contamination was 3 occurrences in ~2,900, all incidental cross-references.

Out of scope for v1, but deliberately not precluded by the schema:
  * Northern Ireland — separate regime under DfI NI, no A&D publication here.
  * PSV — a parallel set of "notices and proceedings" pages. No P-prefixed
    licence numbers appear in any goods document, so the two streams are
    cleanly separable (spec §14 Q3).
"""

from __future__ import annotations

from dataclasses import dataclass

COLLECTION_URL = (
    "https://www.gov.uk/government/collections/traffic-commissioner-applications-and-decisions"
)
GUIDANCE_BASE = "https://www.gov.uk/guidance/applications-and-decisions-for-"
CONTENT_API_BASE = "https://www.gov.uk/api/content/guidance/applications-and-decisions-for-"


@dataclass(frozen=True, slots=True)
class TrafficArea:
    """One traffic area and its single A&D publication stream."""

    slug: str
    name: str
    licence_prefix: str
    """Two-letter licence-number prefix, e.g. 'OF'. Empirically confirmed."""

    @property
    def guidance_url(self) -> str:
        return f"{GUIDANCE_BASE}{self.slug}"

    @property
    def content_api_url(self) -> str:
        return f"{CONTENT_API_BASE}{self.slug}"


TRAFFIC_AREAS: tuple[TrafficArea, ...] = (
    TrafficArea("the-east-of-england", "East of England", "OF"),
    TrafficArea("london-and-the-south-east-of-england", "London & South East", "OK"),
    TrafficArea("the-north-east-of-england", "North East England", "OB"),
    TrafficArea("the-north-west-of-england", "North West England", "OC"),
    TrafficArea("the-west-midlands", "West Midlands", "OD"),
    TrafficArea("the-west-of-england", "West of England", "OH"),
    TrafficArea("scotland", "Scotland", "OM"),
    TrafficArea("wales", "Wales", "OG"),
)

BY_SLUG: dict[str, TrafficArea] = {a.slug: a for a in TRAFFIC_AREAS}
BY_PREFIX: dict[str, TrafficArea] = {a.licence_prefix: a for a in TRAFFIC_AREAS}

#: Lead region for Phase 0 (PLAN.md §4, decision 5). Measured over the full
#: 2026 corpus at ~156 distinct licences per release — 1.5x the next area —
#: and spanning the Midlands "golden triangle" logistics corridor, the Thames
#: Gateway and the Felixstowe hinterland.
LEAD_AREA = BY_SLUG["the-east-of-england"]


def resolve(name: str) -> TrafficArea:
    """Look up a traffic area by slug, licence prefix, or loose name match."""
    key = name.strip()
    if key in BY_SLUG:
        return BY_SLUG[key]
    if key.upper() in BY_PREFIX:
        return BY_PREFIX[key.upper()]
    folded = key.casefold().replace("_", "-").replace(" ", "-")
    for area in TRAFFIC_AREAS:
        if folded in area.slug or folded == area.name.casefold():
            return area
    raise KeyError(
        f"unknown traffic area {name!r}; expected one of: "
        + ", ".join(a.slug for a in TRAFFIC_AREAS)
    )
