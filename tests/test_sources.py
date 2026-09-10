"""The traffic-area registry is reference data the whole pipeline keys off."""

from __future__ import annotations

import pytest

from haulier import sources


def test_eight_areas_with_unique_slugs_and_prefixes() -> None:
    assert len(sources.TRAFFIC_AREAS) == 8
    assert len({a.slug for a in sources.TRAFFIC_AREAS}) == 8
    assert len({a.licence_prefix for a in sources.TRAFFIC_AREAS}) == 8


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("the-east-of-england", "the-east-of-england"),
        ("OF", "the-east-of-england"),
        ("of", "the-east-of-england"),
        ("scotland", "scotland"),
        ("West Midlands", "the-west-midlands"),
        ("  wales  ", "wales"),
    ],
)
def test_resolve_accepts_slug_prefix_and_name(query: str, expected: str) -> None:
    assert sources.resolve(query).slug == expected


def test_resolve_rejects_unknown() -> None:
    with pytest.raises(KeyError):
        sources.resolve("northern-ireland")
