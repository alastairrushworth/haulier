"""Capture idempotency, supersede detection, and fault isolation.

Two behaviours the module docstring promised but the code did not have: a
release whose bytes changed at source was never re-fetched (the check was
existence, not digest), and one unreadable PDF aborted the whole run before
`write_manifest` ever ran — losing the manifest for that region and skipping
every region after it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from haulier import capture as capture_mod
from haulier.capture import CapturedRelease, capture_area, manifest_path
from haulier.govuk import Attachment
from haulier.sources import LEAD_AREA, TrafficArea

PDF_A = b"%PDF-1.4 first version padding to a stable size\n"
PDF_B = b"%PDF-1.4 SECOND version, different bytes and length\n"


@dataclass(frozen=True)
class FakeResponse:
    content: bytes


class FakeClient:
    """A `govuk.ReleaseSource` that serves fixed bytes and counts fetches."""

    def __init__(self, attachments: list[Attachment], body: bytes) -> None:
        self._attachments = attachments
        self.body = body
        self.fetches: list[str] = []

    def attachments(self, area: TrafficArea) -> list[Attachment]:
        return self._attachments

    def get(self, url: str) -> FakeResponse:
        self.fetches.append(url)
        return FakeResponse(self.body)


def _attachment(size: int) -> Attachment:
    return Attachment(
        region_slug=LEAD_AREA.slug,
        title="AD - 5599 05 August 2026",
        url="https://assets.example/AD_5599.pdf",
        filename="AD_5599.pdf",
        content_type="application/pdf",
        file_size=size,
        release_no="5599",
        published_on=None,
        doc_type="AD",
    )


@pytest.fixture
def no_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    ok = capture_mod.PdfProbe(page_count=3, sample_chars=900, has_text_layer=True)
    monkeypatch.setattr(capture_mod, "probe_pdf", lambda path, **kw: ok)


def test_unchanged_release_is_not_refetched(data_dir: Path, no_probe: None) -> None:
    client = FakeClient([_attachment(len(PDF_A))], PDF_A)
    first = capture_area(LEAD_AREA, client)
    second = capture_area(LEAD_AREA, client)
    assert len(client.fetches) == 1
    assert first.releases[0].sha256 == second.releases[0].sha256
    assert second.releases[0].superseded_sha256 is None


def test_reissued_release_is_refetched_and_flagged(data_dir: Path, no_probe: None) -> None:
    client = FakeClient([_attachment(len(PDF_A))], PDF_A)
    first = capture_area(LEAD_AREA, client)

    reissued = FakeClient([_attachment(len(PDF_B))], PDF_B)
    second = capture_area(LEAD_AREA, reissued)

    assert reissued.fetches, "advertised size changed but nothing was re-fetched"
    assert second.releases[0].sha256 != first.releases[0].sha256
    assert second.releases[0].superseded_sha256 == first.releases[0].sha256


def test_refresh_forces_a_refetch(data_dir: Path, no_probe: None) -> None:
    client = FakeClient([_attachment(len(PDF_A))], PDF_A)
    capture_area(LEAD_AREA, client)
    capture_area(LEAD_AREA, client, refresh=True)
    assert len(client.fetches) == 2


def test_unreadable_pdf_does_not_sink_the_run(data_dir: Path) -> None:
    """A probe failure is recorded on the row; the manifest is still written."""
    client = FakeClient([_attachment(len(PDF_A))], PDF_A)  # not a real PDF
    result = capture_area(LEAD_AREA, client)

    assert len(result.releases) == 1
    row = result.releases[0]
    assert row.has_text_layer is None
    assert row.probe_error
    assert row.sha256  # the bytes are still fingerprinted
    assert manifest_path(LEAD_AREA).exists()


def test_manifest_survives_a_fetch_failure(data_dir: Path, no_probe: None) -> None:
    """Whatever was captured before the failure is still recorded."""

    class Failing(FakeClient):
        def get(self, url: str) -> FakeResponse:
            raise OSError("connection reset")

    good = FakeClient([_attachment(len(PDF_A))], PDF_A)
    capture_area(LEAD_AREA, good)

    changed = _attachment(len(PDF_B))  # size differs → wants a re-fetch, which fails
    failing = Failing([changed], PDF_B)
    result = capture_area(LEAD_AREA, failing)

    assert result.failures, "a fetch failure should be reported, not raised"
    rows = json.loads(manifest_path(LEAD_AREA).read_text(encoding="utf-8"))
    assert len(rows) == 1, "the previously captured release must not be dropped"
    assert rows[0]["sha256"]


def test_captured_release_round_trips_through_the_manifest(data_dir: Path, no_probe: None) -> None:
    client = FakeClient([_attachment(len(PDF_A))], PDF_A)
    row = capture_area(LEAD_AREA, client).releases[0]
    stored = json.loads(manifest_path(LEAD_AREA).read_text(encoding="utf-8"))[0]
    assert CapturedRelease.from_manifest_row(stored) == row
