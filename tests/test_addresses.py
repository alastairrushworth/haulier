"""Address parsing — the town and postcode a subscriber actually reads.

Both are customer-visible on every lead card, and the operating-centre postcode
is load-bearing for radius filtering (PLAN §2.12).
"""

from __future__ import annotations

import pytest

from haulier.digest.leads import place_of, postcode_of, town_of


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("UNIT 15, NORWICH ROAD, LENWADE, NORWICH, NR9 5SG", "NR9 5SG"),
        ("2 JAMES FENTON WAY, SHEEPCOTES, CHELMSFORD, CM2 5AN", "CM2 5AN"),
        ("MURDOCH COURT, KNOWL HILL, MILTON KEYNES, MK5 8HL", "MK5 8HL"),
        ("no postcode here at all", None),
    ],
)
def test_postcode_of(address: str, expected: str | None) -> None:
    assert postcode_of(address) == expected


def test_postcode_takes_the_last_one_in_the_address() -> None:
    assert postcode_of("C/O AB1 2CD OFFICE, LENWADE, NORWICH, NR9 5SG") == "NR9 5SG"


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("UNIT 15, NORWICH ROAD, LENWADE, NORWICH, NR9 5SG", "Norwich"),
        ("MURDOCH COURT, KNOWL HILL, MILTON KEYNES, MK5 8HL", "Milton Keynes"),
        # `.title()` breaks on an apostrophe — this rendered as "King'S Lynn".
        ("SCHOOL FARM, SYERS LANE, BEESTON, KING'S LYNN, PE32 2NJ", "King's Lynn"),
        ("HIGH STREET, BURY ST EDMUNDS, IP33 1XX", "Bury St Edmunds"),
        # Town and postcode sharing one comma-separated component.
        ("MILL LANE, LENWADE, NORWICH NR9 5SG", "Norwich"),
        (None, None),
    ],
)
def test_town_of(address: str | None, expected: str | None) -> None:
    assert town_of(address) == expected


def test_place_of_joins_town_and_postcode() -> None:
    assert place_of("SYERS LANE, BEESTON, KING'S LYNN, PE32 2NJ") == "King's Lynn, PE32 2NJ"
    assert place_of(None) is None
