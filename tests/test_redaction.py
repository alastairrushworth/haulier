"""Redaction for the public sample — PLAN §2.11.

The public sample digest goes on an open URL, so it must not carry an
identifiable individual. Redacting only the `people` and `transport_managers`
lists is not enough: East of England 5599 leaks nine full names back through
free text and operator names, because

  * transport-manager public inquiries name the individual in `notes`;
  * a sole trader's or partnership's `operator_name` *is* a personal name; and
  * their `correspondence_address` is, very often, a home address.
"""

from __future__ import annotations

import json
from typing import Any

from haulier.digest.leads import build_lead, is_sole_trader_or_partnership, redact_name
from haulier.digest.render import render_csv, render_html


def test_redact_name_initialises() -> None:
    assert redact_name("JOHN ANDREW KILLETT") == "J. A. K."
    assert redact_name("MARIE-HELENE MICHON") == "M. H. M."


def test_redact_name_drops_honorifics() -> None:
    assert redact_name("Mr CHRISTOPHER DARBYSHIRE") == "C. D."
    assert redact_name("Dr Jane Doe") == "J. D."


def test_notes_naming_an_individual_are_scrubbed(release: dict[str, Any]) -> None:
    record: dict[str, Any] = {
        "section": "5.3",
        "event_type": "PUBLIC_INQUIRY",
        "licence_number": None,
        "operator_name": None,
        "people_role": None,
        "people": ["GEORGE THOMAS"],
        "notes": "TM Public Inquiry (Case ID: 481642) for GEORGE THOMAS to be held at Leeds.",
    }
    html = render_html(release, [build_lead(record, release)], redact=True)
    assert "GEORGE THOMAS" not in html
    assert "G. T." in html


def test_sole_trader_operator_name_is_scrubbed(release: dict[str, Any]) -> None:
    record: dict[str, Any] = {
        "section": "7.1",
        "event_type": "SURRENDER",
        "licence_number": "OF1234567",
        "operator_name": "DALE SIMON ATKINS",
        "people_role": None,
        "people": [],
        "correspondence_address": "ROSE COTTAGE, MILL LANE, LENWADE, NORWICH, NR9 5SG",
    }
    lead = build_lead(record, release)
    html = render_html(release, [lead], redact=True)
    csv_text = render_csv(release, [lead], redact=True)
    assert "DALE SIMON ATKINS" not in html
    assert "DALE SIMON ATKINS" not in csv_text
    # The home address goes too, but the sales signal — the town — survives.
    assert "ROSE COTTAGE" not in csv_text
    assert "NR9 5SG" in csv_text


def test_limited_company_address_is_kept(release: dict[str, Any], record: dict[str, Any]) -> None:
    """Only non-corporate operators lose their street address."""
    csv_text = render_csv(release, [build_lead(record, release)], redact=True)
    assert "MILL LANE" in csv_text


def test_entity_typing(release: dict[str, Any]) -> None:
    assert is_sole_trader_or_partnership({"people_role": "partners"}) is True
    assert is_sole_trader_or_partnership({"people_role": "directors"}) is False
    assert is_sole_trader_or_partnership({"operator_name": "Benjamin Davey"}) is True
    assert (
        is_sole_trader_or_partnership(
            {"operator_name": "NORTHWEST LEICESTERSHIRE DISTRICT COUNCIL"}
        )
        is False
    )
    assert is_sole_trader_or_partnership({"operator_name": None}) is None


def test_no_personal_name_survives_the_pilot_sample(pilot: dict[str, Any]) -> None:
    """The whole point: run the real release through and grep for every name."""
    leads = [build_lead(r, pilot) for r in pilot["records"]]
    html = render_html(pilot, leads, redact=True)
    csv_text = render_csv(pilot, leads, redact=True)

    names: set[str] = set()
    for rec in pilot["records"]:
        names.update(rec.get("people") or [])
        names.update(rec.get("transport_managers") or [])
        if is_sole_trader_or_partnership(rec) and rec.get("operator_name"):
            names.add(rec["operator_name"])

    leaked_html = sorted(n for n in names if n in html)
    leaked_csv = sorted(n for n in names if n in csv_text)
    assert leaked_html == [], f"names in redacted HTML: {leaked_html}"
    assert leaked_csv == [], f"names in redacted CSV: {leaked_csv}"


def test_unredacted_output_keeps_names(pilot: dict[str, Any]) -> None:
    """Redaction is opt-in; the subscriber digest is unaffected."""
    leads = [build_lead(r, pilot) for r in pilot["records"]]
    assert "JOHN ANDREW KILLETT" in render_html(pilot, leads, redact=False)
    assert json.dumps(pilot["records"][0])  # fixture sanity


def test_no_personal_name_survives_the_committed_sample(sample: dict[str, Any]) -> None:
    """The same sweep as the pilot test, but on a fixture CI can actually see."""
    leads = [build_lead(r, sample) for r in sample["records"]]
    html = render_html(sample, leads, redact=True)
    csv_text = render_csv(sample, leads, redact=True)

    names: set[str] = set()
    for rec in sample["records"]:
        names.update(rec.get("people") or [])
        names.update(rec.get("transport_managers") or [])
        if is_sole_trader_or_partnership(rec) and rec.get("operator_name"):
            names.add(rec["operator_name"])
    assert names, "fixture should carry personal names to redact"

    assert [n for n in sorted(names) if n in html] == []
    assert [n for n in sorted(names) if n in csv_text] == []


def test_sample_home_address_is_reduced_but_corporate_kept(sample: dict[str, Any]) -> None:
    leads = [build_lead(r, sample) for r in sample["records"]]
    csv_text = render_csv(sample, leads, redact=True)
    assert "ROSE COTTAGE" not in csv_text, "sole trader's home address must go"
    assert "PE32 2NJ" in csv_text, "the town and postcode are the sales signal"
    assert "HANGAR ROAD" in csv_text, "a limited company's address stays"
