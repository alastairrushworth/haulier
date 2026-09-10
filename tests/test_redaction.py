"""Redaction for the public sample — PLAN §2.11.

The public sample digest goes on an open URL, so it must not carry an
identifiable individual. Redacting only the `people` and `transport_managers`
lists is not enough: East of England 5599 leaks nine full names back through
free text and operator names, because

  * transport-manager public inquiries name the individual in `notes`;
  * a sole trader's or partnership's `operator_name` *is* a personal name; and
  * their `correspondence_address` is, very often, a home address.

A fourth, found in the September review: "JOHN SMITH T/A SMITH HAULAGE" is a
sole trader whose legal name precedes a trading-as marker. The entity check
returned unknown for the shape, the operator name was left alone, and the
leak test could not see it because it only swept names already flagged.
`Lead.personal_names` is now the single statement of what must not appear.
"""

from __future__ import annotations

import json
from typing import Any

from haulier.digest.leads import (
    build_lead,
    is_sole_trader_or_partnership,
    legal_name,
    redact_lead,
    redact_name,
    redact_operator_name,
)
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


def test_trading_as_is_classified_on_the_legal_entity() -> None:
    """The part before T/A is the operator; the part after is what it calls itself."""
    assert legal_name("JOHN SMITH T/A SMITH HAULAGE") == "JOHN SMITH"
    assert legal_name("HU United Limited t/a United Truck Stop") == "HU United Limited"
    assert legal_name("JANE DOE TRADING AS DOE SKIPS") == "JANE DOE"
    assert legal_name("BINDER LTD") == "BINDER LTD"

    assert is_sole_trader_or_partnership({"operator_name": "JOHN SMITH T/A SMITH HAULAGE"}) is True
    assert (
        is_sole_trader_or_partnership(
            {"operator_name": "C A D SERVICES LIMITED T/A FACILITIES BY ADF"}
        )
        is False
    )
    # A trade name before the marker still settles nothing.
    assert is_sole_trader_or_partnership({"operator_name": "SMITH HAULAGE T/A SH"}) is None


def test_partnership_shape_is_flagged_without_a_role() -> None:
    """~130 operator lines in the 2026 corpus read "X & PARTNERS"; the extractor
    does not always supply `people_role` for them. An LLP is a body corporate."""
    assert is_sole_trader_or_partnership({"operator_name": "SMITH & PARTNERS"}) is True
    assert is_sole_trader_or_partnership({"operator_name": "THE MILL PARTNERSHIP"}) is True
    assert is_sole_trader_or_partnership({"operator_name": "X PARTNERS LTD"}) is False
    assert is_sole_trader_or_partnership({"operator_name": "SMITH & JONES LLP"}) is False


def test_trading_as_sole_trader_is_redacted_everywhere(release: dict[str, Any]) -> None:
    record: dict[str, Any] = {
        "section": "1.1",
        "event_type": "NEW_APPLICATION",
        "licence_number": "OF1234568",
        "operator_name": "JOHN SMITH T/A SMITH HAULAGE",
        "people_role": None,
        "people": [],
        "correspondence_address": "1 HOME CLOSE, NORWICH, NR1 1AA",
        "notes": "Application by JOHN SMITH for a restricted licence.",
    }
    lead = build_lead(record, release)
    assert lead.personal_names == ["JOHN SMITH"]

    redacted = redact_lead(lead)
    assert redacted.operator_name == "J. S. T/A S. Haulage"
    assert redacted.notes == "Application by J. S. for a restricted licence."
    assert redacted.correspondence_address == "Norwich, NR1 1AA"
    for text in (
        render_html(release, [lead], redact=True),
        render_csv(release, [lead], redact=True),
    ):
        assert "JOHN SMITH" not in text
        assert "SMITH HAULAGE" not in text


def test_personal_legal_name_is_redacted_whatever_the_flag_says(release: dict[str, Any]) -> None:
    """The safety net: an operator name that reads as a person is redacted even
    if the entity flag was settled some other way."""
    record: dict[str, Any] = {
        "section": "1.1",
        "event_type": "NEW_APPLICATION",
        "licence_number": "OF1234569",
        "operator_name": "DALE SIMON ATKINS",
        "people_role": "directors",  # says company; the name says otherwise
        "people": ["DALE SIMON ATKINS"],
    }
    lead = build_lead(record, release)
    assert lead.sole_trader_or_partnership is False
    assert redact_lead(lead).operator_name == "D. S. A."


def test_redact_operator_name_keeps_structure_and_drops_honorifics() -> None:
    assert redact_operator_name("WYNDHAM & PARTNERS") == "W. & Partners"
    assert redact_operator_name("MR BARRY PINCHING") == "B. P."
    assert redact_operator_name("JOHN SMITH T/A SMITH HAULAGE") == "J. S. T/A S. Haulage"


def test_no_personal_name_survives_the_pilot_sample(pilot: dict[str, Any]) -> None:
    """The whole point: run the real release through and grep for every name."""
    leads = [build_lead(r, pilot) for r in pilot["records"]]
    html = render_html(pilot, leads, redact=True)
    csv_text = render_csv(pilot, leads, redact=True)

    names = {name for lead in leads for name in lead.personal_names}
    assert len(names) > 250, "the pilot carries hundreds of names; the sweep must see them"

    leaked_html = sorted(n for n in names if n.casefold() in html.casefold())
    leaked_csv = sorted(n for n in names if n.casefold() in csv_text.casefold())
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

    names = {name for lead in leads for name in lead.personal_names}
    assert "ROSALIND VERITY THACKERAY" in names, "the T/A sole trader must be in the sweep"
    assert "MARTIN OSWALD FEATHERSTONE" in names, "the plain sole trader must be in the sweep"

    assert [n for n in sorted(names) if n.casefold() in html.casefold()] == []
    assert [n for n in sorted(names) if n.casefold() in csv_text.casefold()] == []
    # And the partnership without a `people_role` still loses its surname.
    assert "PELLINGBROOK" not in csv_text
    assert "P. & Partners" in csv_text


def test_sample_home_address_is_reduced_but_corporate_kept(sample: dict[str, Any]) -> None:
    leads = [build_lead(r, sample) for r in sample["records"]]
    csv_text = render_csv(sample, leads, redact=True)
    assert "ROSE COTTAGE" not in csv_text, "sole trader's home address must go"
    assert "PE32 2NJ" in csv_text, "the town and postcode are the sales signal"
    assert "HANGAR ROAD" in csv_text, "a limited company's address stays"
