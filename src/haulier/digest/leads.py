"""Normalise extracted records into lead rows for the digest and CSV.

A record is what the extractor saw in one A&D entry; a lead is what a
subscriber receives (spec §4.2). The transforms here are deliberately shallow —
counts are parsed from authorisation strings, postcodes lifted from addresses —
because anything the source doesn't state stays empty rather than inferred.

Deltas: the source states the NEW authorisation ("New licence authorisation
will be 70 trailer(s)"), not the previous one, so `vehicles_delta` needs licence
history and stays empty until the pipeline has state (spec §4.2's "3 → 7" form).
The per-centre change text goes to the card and source_notes instead.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

#: Content-addressed event ids (PLAN.md §2.9): stable across re-runs.
EVENT_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://firstmover.example/events")

#: Heat order for digest sections (spec §4.1/§4.3).
HEAT_ORDER = [
    "NEW_APPLICATION",
    "VARIATION_APPLICATION",
    "APPLICATION_GRANTED",
    "VARIATION_GRANTED",
    "SURRENDER",
    "REVOCATION",
    "PUBLIC_INQUIRY",
    "APPLICATION_REFUSED",
    "APPLICATION_WITHDRAWN",
]

EVENT_LABELS = {
    "NEW_APPLICATION": "New application",
    "VARIATION_APPLICATION": "Variation application",
    "APPLICATION_GRANTED": "Application granted",
    "VARIATION_GRANTED": "Variation granted",
    "SURRENDER": "Licence surrendered",
    "REVOCATION": "Licence revoked",
    "PUBLIC_INQUIRY": "Public inquiry",
    "APPLICATION_REFUSED": "Application refused",
    "APPLICATION_WITHDRAWN": "Application withdrawn",
}

_VEHICLES_RE = re.compile(r"(\d+)\s+(?:Heavy goods |Light goods )?vehicle", re.IGNORECASE)
_TRAILERS_RE = re.compile(r"(\d+)\s+trailer", re.IGNORECASE)
_POSTCODE_RE = re.compile(r"\b([A-Z]{1,2}\d{1,2}[A-Z]?)\s*(\d[A-Z]{2})\b")

_CHANGE_LABELS = {
    "increase_at_existing": "increase at",
    "decrease_at_existing": "decrease at",
    "new_centre": "new centre",
    "removed_centre": "removed centre",
}


def parse_counts(text: str | None) -> tuple[int | None, int | None]:
    """(vehicles, trailers) parsed from an authorisation phrase, summing
    HGV and LGV mentions. None when the phrase names no such count."""
    if not text:
        return None, None
    vehicles = [int(m) for m in _VEHICLES_RE.findall(text)]
    trailers = [int(m) for m in _TRAILERS_RE.findall(text)]
    return (sum(vehicles) if vehicles else None, sum(trailers) if trailers else None)


def postcode_of(address: str | None) -> str | None:
    if not address:
        return None
    matches = _POSTCODE_RE.findall(address.upper())
    return f"{matches[-1][0]} {matches[-1][1]}" if matches else None


def town_of(address: str | None) -> str | None:
    """Second-to-last comma-separated component, skipping the postcode part."""
    if not address:
        return None
    parts = [p.strip() for p in address.split(",") if p.strip()]
    parts = [p for p in parts if not _POSTCODE_RE.fullmatch(p.upper().replace("  ", " "))]
    return parts[-1].title() if parts else None


@dataclass(frozen=True, slots=True)
class Lead:
    event_id: str
    event_type: str
    section: str
    event_date: str
    licence_number: str | None
    licence_type: str | None
    operator_name: str | None
    people_role: str | None
    people: list[str] = field(default_factory=list)
    correspondence_address: str | None = None
    operating_centres: list[dict[str, Any]] = field(default_factory=list)
    vehicles_authorised: int | None = None
    trailers_authorised: int | None = None
    change_summary: list[str] = field(default_factory=list)
    transport_managers: list[str] = field(default_factory=list)
    considerations: list[str] = field(default_factory=list)
    notes: str | None = None

    @property
    def label(self) -> str:
        return EVENT_LABELS.get(self.event_type, self.event_type)

    @property
    def first_centre_place(self) -> str | None:
        for centre in self.operating_centres:
            place = town_of(centre.get("address"))
            code = postcode_of(centre.get("address"))
            if place or code:
                return ", ".join(p for p in (place, code) if p)
        return None

    @property
    def fleet_line(self) -> str | None:
        def plural(count: int, noun: str) -> str:
            return f"{count} {noun}{'s' if count != 1 else ''}"

        parts = []
        if self.vehicles_authorised is not None:
            parts.append(plural(self.vehicles_authorised, "vehicle"))
        if self.trailers_authorised is not None:
            parts.append(plural(self.trailers_authorised, "trailer"))
        return " / ".join(parts) if parts else None


def _change_summary(record: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for change in record.get("variation_changes") or []:
        label = _CHANGE_LABELS.get(change["kind"], change["kind"])
        place = town_of(change.get("address")) or ""
        code = postcode_of(change.get("address")) or ""
        where = ", ".join(p for p in (place, code) if p)
        auth = change.get("new_authorisation")
        lines.append(f"{label} {where}" + (f" → {auth}" if auth else ""))
    for total in record.get("new_licence_authorisation") or []:
        lines.append(f"new licence total: {total}")
    return lines


def build_lead(record: dict[str, Any], release: dict[str, Any]) -> Lead:
    centres = record.get("operating_centres") or []
    vehicles = trailers = None
    if record.get("event_type") in {"NEW_APPLICATION", "APPLICATION_GRANTED"} or centres:
        totals = [parse_counts(c.get("authorisation")) for c in centres]
        vehicle_counts = [v for v, _ in totals if v is not None]
        trailer_counts = [t for _, t in totals if t is not None]
        vehicles = sum(vehicle_counts) if vehicle_counts else None
        trailers = sum(trailer_counts) if trailer_counts else None
    else:
        # Variations: the new licence totals, when the source states them.
        joined = " ".join(record.get("new_licence_authorisation") or [])
        vehicles, trailers = parse_counts(joined)

    content_key = "|".join(
        [
            release["release_no"],
            record.get("section") or "",
            record.get("licence_number") or "",
            record.get("event_type") or "",
            record.get("operator_name") or "",
            record.get("notes") or "",
        ]
    )
    return Lead(
        event_id=str(uuid.uuid5(EVENT_NAMESPACE, content_key)),
        event_type=record["event_type"],
        section=record["section"],
        event_date=record.get("effective_date") or release["published_on"],
        licence_number=record.get("licence_number"),
        licence_type=record.get("licence_type"),
        operator_name=record.get("operator_name"),
        people_role=record.get("people_role"),
        people=record.get("people") or [],
        correspondence_address=record.get("correspondence_address"),
        operating_centres=centres,
        vehicles_authorised=vehicles,
        trailers_authorised=trailers,
        change_summary=_change_summary(record),
        transport_managers=record.get("transport_managers") or [],
        considerations=record.get("considerations") or [],
        notes=record.get("notes"),
    )


def redact_name(name: str) -> str:
    """'JOHN ANDREW KILLETT' → 'J. A. K.' for the public sample (PLAN §2.11)."""
    initials = [part[0].upper() for part in re.split(r"[\s-]+", name) if part and part[0].isalpha()]
    return " ".join(f"{i}." for i in initials) if initials else name
