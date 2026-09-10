"""Shared fixtures. The pilot release is the canonical realistic input.

Tests that need real-world shape load `data/pilot/records.json` when it is
present and skip otherwise, so the suite still runs on a fresh clone where
`data/` is gitignored. Everything load-bearing has a synthetic fixture too.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PILOT_RECORDS = REPO_ROOT / "data" / "pilot" / "records.json"
SAMPLE_RECORDS = Path(__file__).parent / "fixtures" / "release_sample.json"


@pytest.fixture(scope="session")
def pilot() -> dict[str, Any]:
    """The 131-record East of England 5599 release, or skip."""
    if not PILOT_RECORDS.exists():
        pytest.skip("pilot corpus not captured (data/ is gitignored)")
    payload: dict[str, Any] = json.loads(PILOT_RECORDS.read_text(encoding="utf-8"))
    return payload


@pytest.fixture(scope="session")
def sample() -> dict[str, Any]:
    """A synthetic release carrying every awkward shape the real corpus has.

    Committed, unlike the pilot, so CI exercises the redaction and event-id
    regressions on realistic structure without publishing anyone's data.
    """
    payload: dict[str, Any] = json.loads(SAMPLE_RECORDS.read_text(encoding="utf-8"))
    return payload


@pytest.fixture
def release() -> dict[str, Any]:
    """A minimal synthetic release header."""
    return {
        "region_slug": "the-east-of-england",
        "region_name": "East of England",
        "release_no": "5599",
        "published_on": "2026-08-05",
        "objection_deadline": "2026-08-26",
    }


@pytest.fixture
def record() -> dict[str, Any]:
    """A minimal synthetic new-application record."""
    return {
        "section": "1.1",
        "event_type": "NEW_APPLICATION",
        "licence_number": "OF2093363",
        "licence_type": "R",
        "operator_name": "EXAMPLE HAULAGE LTD",
        "people_role": "directors",
        "people": ["JANE ALEXANDRA DOE"],
        "correspondence_address": "UNIT 1, MILL LANE, LENWADE, NORWICH, NR9 5SG",
        "operating_centres": [
            {
                "address": "UNIT 1, MILL LANE, LENWADE, NORWICH, NR9 5SG",
                "authorisation": "3 vehicle(s)",
            }
        ],
        "transport_managers": [],
        "notes": None,
    }


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Point HAULIER_DATA_DIR at a temp tree, around the settings cache."""
    from haulier.config import settings

    monkeypatch.setenv("HAULIER_DATA_DIR", str(tmp_path))
    settings.cache_clear()
    yield tmp_path
    settings.cache_clear()
