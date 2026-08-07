"""Render leads to the digest HTML and the §4.4 CSV.

The CSV column list is a stable API — additive changes only. Columns the pilot
cannot fill (Companies House enrichment, deltas needing licence history, VOL
deep links, first_seen_date) are present and empty rather than omitted, so the
pilot CSV already has the production shape.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .leads import HEAT_ORDER, Lead, redact_name

#: Spec §4.4 — do not reorder, do not remove.
CSV_COLUMNS = [
    "event_id", "event_type", "event_date", "publication_region",
    "publication_release", "publication_date", "licence_number",
    "licence_category", "licence_type", "operator_name", "trading_name",
    "correspondence_address", "operating_centres", "vehicles_authorised",
    "trailers_authorised", "vehicles_delta", "trailers_delta",
    "ch_company_number", "ch_company_status", "ch_incorporated_on",
    "ch_directors", "ch_sic_codes", "ch_match_confidence", "vol_url",
    "source_notes", "first_seen_date",
]

HEAT = {
    "NEW_APPLICATION": "★★★", "VARIATION_APPLICATION": "★★★",
    "APPLICATION_GRANTED": "★★★", "VARIATION_GRANTED": "★★★",
    "SURRENDER": "★★", "REVOCATION": "★★",
    "PUBLIC_INQUIRY": "★", "APPLICATION_REFUSED": "★",
    "APPLICATION_WITHDRAWN": "★",
}

GROUP_TITLES = {
    "NEW_APPLICATION": "New applications",
    "VARIATION_APPLICATION": "Variation applications",
    "APPLICATION_GRANTED": "Applications granted",
    "VARIATION_GRANTED": "Variations granted",
    "SURRENDER": "Licences surrendered",
    "REVOCATION": "Licences revoked",
    "PUBLIC_INQUIRY": "Public inquiries",
    "APPLICATION_REFUSED": "Applications refused",
    "APPLICATION_WITHDRAWN": "Applications withdrawn",
}


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(Path(__file__).parent / "templates"),
        autoescape=select_autoescape(["html", "j2"]),
    )


def group_by_heat(leads: list[Lead]) -> list[dict[str, Any]]:
    groups = []
    for event_type in HEAT_ORDER:
        matching = [lead for lead in leads if lead.event_type == event_type]
        if matching:
            groups.append(
                {
                    "title": GROUP_TITLES[event_type],
                    "heat": HEAT.get(event_type, ""),
                    "leads": matching,
                }
            )
    return groups


def subject_line(release: dict[str, Any], leads: list[Lead]) -> str:
    new = sum(1 for lead in leads if lead.event_type == "NEW_APPLICATION")
    expansions = sum(1 for lead in leads if lead.event_type == "VARIATION_APPLICATION")
    return (
        f"[{release['region_name']}] {new} new operators, "
        f"{expansions} expansions — A&D {release['release_no']}"
    )


def _maybe_redact(lead: Lead, redact: bool) -> Lead:
    if not redact:
        return lead
    from dataclasses import replace

    return replace(
        lead,
        people=[redact_name(n) for n in lead.people],
        transport_managers=[redact_name(n) for n in lead.transport_managers],
    )


def render_html(release: dict[str, Any], leads: list[Lead], *, redact: bool = False) -> str:
    leads = [_maybe_redact(lead, redact) for lead in leads]
    def tally(*event_types: str) -> int:
        return sum(1 for lead in leads if lead.event_type in event_types)

    counts = {
        "new operators": tally("NEW_APPLICATION"),
        "expansions": tally("VARIATION_APPLICATION"),
        "granted": tally("APPLICATION_GRANTED", "VARIATION_GRANTED"),
        "surrendered / revoked": tally("SURRENDER", "REVOCATION"),
    }
    return _env().get_template("digest.html.j2").render(
        subject=subject_line(release, leads),
        region_name=release["region_name"],
        release_no=release["release_no"],
        published_on=release["published_on"],
        objection_deadline=release.get("objection_deadline") or "—",
        summary=[(count, caption) for caption, count in counts.items()],
        groups=group_by_heat(leads),
        total=len(leads),
    )


def _blank_if_none(value: int | None) -> int | str:
    return value if value is not None else ""


def render_csv(release: dict[str, Any], leads: list[Lead], *, redact: bool = False) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for lead in leads:
        lead = _maybe_redact(lead, redact)
        notes = [lead.notes] if lead.notes else []
        notes.extend(lead.considerations)
        notes.extend(lead.change_summary)
        if lead.people:
            notes.append(f"{lead.people_role or 'named'}: {', '.join(lead.people)}")
        if lead.transport_managers:
            notes.append(f"transport managers: {', '.join(lead.transport_managers)}")
        writer.writerow(
            {
                "event_id": lead.event_id,
                "event_type": lead.event_type,
                "event_date": lead.event_date,
                "publication_region": release["region_name"],
                "publication_release": release["release_no"],
                "publication_date": release["published_on"],
                "licence_number": lead.licence_number or "",
                "licence_category": "goods",
                "licence_type": lead.licence_type or "",
                "operator_name": lead.operator_name or "",
                "trading_name": "",
                "correspondence_address": lead.correspondence_address or "",
                "operating_centres": " | ".join(
                    f"{c.get('address')} [{c.get('authorisation')}]"
                    for c in lead.operating_centres
                ),
                "vehicles_authorised": _blank_if_none(lead.vehicles_authorised),
                "trailers_authorised": _blank_if_none(lead.trailers_authorised),
                "vehicles_delta": "",
                "trailers_delta": "",
                "ch_company_number": "", "ch_company_status": "",
                "ch_incorporated_on": "", "ch_directors": "",
                "ch_sic_codes": "", "ch_match_confidence": "",
                "vol_url": "",
                "source_notes": "; ".join(notes),
                "first_seen_date": "",
            }
        )
    return buffer.getvalue()
