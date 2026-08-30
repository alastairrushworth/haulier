"""Event identity — PLAN §2.9 (content-addressed ids) and §2.2 (legitimate duplicates).

The collision this guards against is not hypothetical: East of England 5599
carries two DPDGROUP variations on licence OF0217601, differing only in which
operating centre changed. Under a key built from
release|section|licence|event_type|operator|notes they hash identically, and
the second — a 50-vehicle expansion — is indistinguishable from the first.
"""

from __future__ import annotations

import copy
from typing import Any

from haulier.digest.leads import build_lead


def test_ids_are_stable_across_runs(record: dict[str, Any], release: dict[str, Any]) -> None:
    assert build_lead(record, release).event_id == build_lead(record, release).event_id


def test_ids_are_stable_under_key_reordering(
    record: dict[str, Any], release: dict[str, Any]
) -> None:
    reordered = dict(reversed(list(record.items())))
    assert build_lead(reordered, release).event_id == build_lead(record, release).event_id


def test_same_licence_two_operating_centre_variations_differ(release: dict[str, Any]) -> None:
    """PLAN §2.2's collision case, reduced to its essentials."""
    base: dict[str, Any] = {
        "section": "2.3",
        "event_type": "VARIATION_GRANTED",
        "licence_number": "OF0217601",
        "operator_name": "DPDGROUP UK LTD",
        "operating_centres": [],
        "notes": None,
        "variation_changes": [
            {"kind": "increase_at_existing", "address": "MILTON KEYNES, MK5 8HL"}
        ],
    }
    other = copy.deepcopy(base)
    other["variation_changes"] = [
        {"kind": "increase_at_existing", "address": "CHELMSFORD, CM2 5AN"}
    ]
    assert build_lead(base, release).event_id != build_lead(other, release).event_id


def test_differing_authorisation_alone_changes_the_id(release: dict[str, Any]) -> None:
    base: dict[str, Any] = {
        "section": "2.3",
        "event_type": "VARIATION_GRANTED",
        "licence_number": "OF0217601",
        "operator_name": "DPDGROUP UK LTD",
        "new_licence_authorisation": ["12 Heavy goods vehicle(s)"],
    }
    other = copy.deepcopy(base)
    other["new_licence_authorisation"] = ["1142 Heavy goods vehicle(s)"]
    assert build_lead(base, release).event_id != build_lead(other, release).event_id


def test_pilot_release_has_no_colliding_ids(pilot: dict[str, Any]) -> None:
    leads = [build_lead(r, pilot) for r in pilot["records"]]
    assert len({lead.event_id for lead in leads}) == len(leads)


def test_committed_sample_has_no_colliding_ids(sample: dict[str, Any]) -> None:
    """Carries the two-variations-on-one-licence case that collided for real."""
    leads = [build_lead(r, sample) for r in sample["records"]]
    assert len({lead.event_id for lead in leads}) == len(leads)
