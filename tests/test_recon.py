"""Heading and licence recon — PLAN §2.10 detectors.

`Sch.3 - Consideration of Transport Managers Repute under Schedule 3` is the
single most frequent heading in the 2026 corpus (200 occurrences across 29 of
31 East of England releases), but a marker regex anchored on `S<digit>` cannot
match it, so it was absent from the taxonomy that seeds the segmenter.
"""

from __future__ import annotations

import pytest

from haulier import recon


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("S13 - Application granted as applied for", "S13"),
        ("  S17 – Variation granted", "S17"),
        ("S26 — Consideration of disciplinary action under Section 26", "S26"),
        ("S9A - Something", "S9A"),
        ("Sch.3 - Consideration of Transport Managers Repute under Schedule 3", "Sch.3"),
        ("Sch 3 - Consideration of Transport Managers Repute", "Sch.3"),
        # Wrapped headings keep the marker.
        ("Sch.3 - Consideration of Transport Managers Repute under Sch", "Sch.3"),
    ],
)
def test_marker_of_recognises_statutory_markers(line: str, expected: str) -> None:
    assert recon.marker_of(line) == expected


@pytest.mark.parametrize(
    "line",
    [
        "Schedule 4 to the Goods Vehicles (Licensing of Operators) Act 1995 allows, in certain",
        "Schedule 3",
        "Section 1 - Applications Received",
        "Office of the Traffic Commissioner",
        "S13",
    ],
)
def test_marker_of_rejects_prose_and_bare_headings(line: str) -> None:
    assert recon.marker_of(line) is None


def _line(text: str, *, size: float = 11.0, bold: bool = True) -> dict[str, object]:
    return {"t": text, "s": size, "b": bold}


def test_analyse_headings_counts_sch3_as_a_marker() -> None:
    dump = {
        "release_no": "5599",
        "sha256": "deadbeef" * 8,
        "pages": [
            {
                "n": 1,
                "lines": [
                    _line("Sch.3 - Consideration of Transport Managers Repute"),
                    _line("S26 - Consideration of disciplinary action"),
                    _line("Schedule 4 to the Goods Vehicles Act 1995 allows", size=9.0, bold=False),
                ],
            }
        ],
    }
    stats = recon.analyse_headings([dump, {**dump, "release_no": "5600"}])
    assert set(stats.markers) == {"Sch.3", "S26"}
    assert stats.markers["Sch.3"] == 2
    assert len(stats.marker_releases["Sch.3"]) == 2


def test_licence_regex_matches_the_spec_shape() -> None:
    assert recon.LICENCE_RE.findall("holder OF2093363 and PB1234567") == [
        ("OF", "2093363"),
        ("PB", "1234567"),
    ]
    assert not recon.LICENCE_RE.search("case 48164")
