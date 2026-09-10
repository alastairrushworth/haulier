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

from ..config import settings
from .leads import HEAT_ORDER, Lead, redact_lead

#: Spec §4.4 — do not reorder, do not remove. Additions go on the end only.
#:
#: The last two are additions to §4.4's list (PLAN §2.14):
#:   * `operating_centre_postcodes` — PLAN §2.12 makes operating-centre
#:     postcode load-bearing for radius filtering, and it cannot be filtered on
#:     while it is buried in the address blob.
#:   * `is_sole_trader_or_partnership` — required by spec §4.2 and §8.4
#:     ("prominently in the CSV"), but missing from §4.4's own column list.
#:     Subscribers route these to phone or post rather than cold email, so the
#:     column is PECR-load-bearing rather than cosmetic.
# fmt: off
CSV_COLUMNS = [
    "event_id", "event_type", "event_date", "publication_region",
    "publication_release", "publication_date", "licence_number",
    "licence_category", "licence_type", "operator_name", "trading_name",
    "correspondence_address", "operating_centres", "vehicles_authorised",
    "trailers_authorised", "vehicles_delta", "trailers_delta",
    "ch_company_number", "ch_company_status", "ch_incorporated_on",
    "ch_directors", "ch_sic_codes", "ch_match_confidence", "vol_url",
    "source_notes", "first_seen_date",
    "operating_centre_postcodes", "is_sole_trader_or_partnership",
]
# fmt: on

# fmt: off
HEAT = {
    "NEW_APPLICATION": "★★★", "VARIATION_APPLICATION": "★★★",
    "APPLICATION_GRANTED": "★★★", "VARIATION_GRANTED": "★★★",
    "SURRENDER": "★★", "REVOCATION": "★★",
    "PUBLIC_INQUIRY": "★", "APPLICATION_REFUSED": "★",
    "APPLICATION_WITHDRAWN": "★",
}
# fmt: on

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
    return redact_lead(lead) if redact else lead


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
    return (
        _env()
        .get_template("digest.html.j2")
        .render(
            subject=subject_line(release, leads),
            region_name=release["region_name"],
            release_no=release["release_no"],
            published_on=release["published_on"],
            objection_deadline=release.get("objection_deadline") or "—",
            summary=[(count, caption) for caption, count in counts.items()],
            groups=group_by_heat(leads),
            total=len(leads),
            objection_email=settings().objection_route,
            privacy_notice_url=settings().privacy_notice_url,
        )
    )


def _blank_if_none(value: int | None) -> int | str:
    return value if value is not None else ""


def _yes_no(value: bool | None) -> str:
    """Three-state: an empty cell means the source would not say, which tells
    the subscriber to check rather than asserting a wrong 'no' (spec §8.4)."""
    return "" if value is None else ("yes" if value else "no")


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
                    f"{c.get('address')} [{c.get('authorisation')}]" for c in lead.operating_centres
                ),
                "vehicles_authorised": _blank_if_none(lead.vehicles_authorised),
                "trailers_authorised": _blank_if_none(lead.trailers_authorised),
                "vehicles_delta": "",
                "trailers_delta": "",
                "ch_company_number": "",
                "ch_company_status": "",
                "ch_incorporated_on": "",
                "ch_directors": "",
                "ch_sic_codes": "",
                "ch_match_confidence": "",
                "vol_url": "",
                "source_notes": "; ".join(notes),
                "first_seen_date": "",
                "operating_centre_postcodes": " | ".join(lead.operating_centre_postcodes),
                "is_sole_trader_or_partnership": _yes_no(lead.sole_trader_or_partnership),
            }
        )
    return buffer.getvalue()
