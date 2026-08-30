"""The CSV column contract — spec §4.4, additive changes only.

Two columns spec §4.4's list omits but the product needs:

  * `is_sole_trader_or_partnership` — required by spec §4.2 and §8.4, which
    asks for it "prominently in the CSV so customers can route those to phone
    or post rather than cold email". A PECR-load-bearing field.
  * `operating_centre_postcodes` — PLAN §2.12 promotes operating-centre
    postcode to a first-class field because radius filtering depends on it;
    buried inside the address blob it cannot be filtered on.

Both are appended, never inserted, so existing column positions are stable.
"""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path
from typing import Any

from haulier.digest.leads import build_lead
from haulier.digest.render import CSV_COLUMNS, render_csv

SPEC = Path(__file__).resolve().parents[1] / "spec.md"


def _rows(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


def test_spec_column_order_is_preserved_as_a_prefix() -> None:
    """Spec §4.4's list must still be the first columns, in order."""
    spec = SPEC.read_text(encoding="utf-8")
    match = re.search(r"### 4\.4 CSV contract.*?\n`([^`]+)`", spec, re.S)
    assert match
    spec_columns = [c.strip() for c in match.group(1).split(",")]
    assert CSV_COLUMNS[: len(spec_columns)] == spec_columns


def test_new_columns_are_appended() -> None:
    assert CSV_COLUMNS[-2:] == ["operating_centre_postcodes", "is_sole_trader_or_partnership"]


def test_limited_company_is_not_flagged(release: dict[str, Any], record: dict[str, Any]) -> None:
    row = _rows(render_csv(release, [build_lead(record, release)]))[0]
    assert row["is_sole_trader_or_partnership"] == "no"
    assert row["operating_centre_postcodes"] == "NR9 5SG"


def test_partnership_is_flagged(release: dict[str, Any], record: dict[str, Any]) -> None:
    record = {**record, "people_role": "partners", "operator_name": "HUGH SCOTT & PARTNERS"}
    row = _rows(render_csv(release, [build_lead(record, release)]))[0]
    assert row["is_sole_trader_or_partnership"] == "yes"


def test_unknown_entity_type_is_blank_not_guessed(
    release: dict[str, Any], record: dict[str, Any]
) -> None:
    record = {**record, "people_role": None, "operator_name": "EASTERN PALLET NETWORK"}
    row = _rows(render_csv(release, [build_lead(record, release)]))[0]
    assert row["is_sole_trader_or_partnership"] == ""


def test_multiple_operating_centres_list_every_postcode(
    release: dict[str, Any], record: dict[str, Any]
) -> None:
    record = {
        **record,
        "operating_centres": [
            {"address": "MILL LANE, NORWICH, NR9 5SG", "authorisation": "3 vehicle(s)"},
            {"address": "KNOWL HILL, MILTON KEYNES, MK5 8HL", "authorisation": "2 vehicle(s)"},
            {"address": "SAME PLACE, NORWICH, NR9 5SG", "authorisation": "1 vehicle(s)"},
        ],
    }
    row = _rows(render_csv(release, [build_lead(record, release)]))[0]
    assert row["operating_centre_postcodes"] == "NR9 5SG | MK5 8HL"


def test_pilot_csv_flags_the_known_sole_traders(pilot: dict[str, Any]) -> None:
    leads = [build_lead(r, pilot) for r in pilot["records"]]
    rows = _rows(render_csv(pilot, leads))
    flagged = {r["operator_name"] for r in rows if r["is_sole_trader_or_partnership"] == "yes"}
    assert {"BARRY PINCHING", "DALE SIMON ATKINS", "JOHN ANDREW KILLETT & Partners"} <= flagged
    corporate = {r["operator_name"] for r in rows if r["is_sole_trader_or_partnership"] == "no"}
    assert "NORTHWEST LEICESTERSHIRE DISTRICT COUNCIL" in corporate
    assert "DPDGROUP UK LTD" in corporate


def test_variation_centres_contribute_postcodes(
    release: dict[str, Any], record: dict[str, Any]
) -> None:
    """A variation names the centre being changed in `variation_changes`, not
    `operating_centres` — 51 of the pilot's 131 leads have their only location
    there, and radius filtering would drop every one of them."""
    record = {
        **record,
        "event_type": "VARIATION_GRANTED",
        "operating_centres": [],
        "variation_changes": [
            {
                "kind": "increase_at_existing",
                "address": "2 FENTON WAY, SHEEPCOTES, CHELMSFORD, CM2 5AN",
                "new_authorisation": "50 Heavy goods vehicle(s)",
            }
        ],
    }
    row = _rows(render_csv(release, [build_lead(record, release)]))[0]
    assert row["operating_centre_postcodes"] == "CM2 5AN"


def test_records_with_no_stated_location_stay_empty(
    release: dict[str, Any], record: dict[str, Any]
) -> None:
    """A surrender states no operating centre; an empty cell is the honest answer."""
    record = {**record, "event_type": "SURRENDER", "operating_centres": []}
    row = _rows(render_csv(release, [build_lead(record, release)]))[0]
    assert row["operating_centre_postcodes"] == ""


def test_most_pilot_leads_now_carry_a_postcode(pilot: dict[str, Any]) -> None:
    leads = [build_lead(r, pilot) for r in pilot["records"]]
    rows = _rows(render_csv(pilot, leads))
    located = sum(1 for r in rows if r["operating_centre_postcodes"])
    assert located >= 86, f"only {located}/{len(rows)} leads are locatable"
