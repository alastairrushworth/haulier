"""Capture idempotency, supersede detection, and fault isolation.

Two behaviours the module docstring promised but the code did not have: a
release whose bytes changed at source was never re-fetched (the check was
existence, not digest), and one unreadable PDF aborted the whole run before
`write_manifest` ever ran — losing the manifest for that region and skipping
every region after it.

Three more from the September review: the manifest was rebuilt from the live
page alone, so it would have emptied on the first run of January; the
supersede record lasted exactly one run; and a re-issue under a new filename
looked like a brand-new release.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
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


def _attachment(
    size: int,
    release_no: str = "5599",
    filename: str = "AD_5599.pdf",
    published_on: date | None = None,
) -> Attachment:
    return Attachment(
        region_slug=LEAD_AREA.slug,
        title=f"AD - {release_no} 05 August 2026",
        url=f"https://assets.example/{filename}",
        filename=filename,
        content_type="application/pdf",
        file_size=size,
        release_no=release_no,
        published_on=published_on,
        doc_type="AD",
    )


def _manifest_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = json.loads(manifest_path(LEAD_AREA).read_text(encoding="utf-8"))
    return rows


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
    assert second.releases[0].superseded_on == date.today()
    assert second.reissued == second.releases, "the re-issue is this run's alarm"


def test_supersede_record_persists_beyond_the_run_that_noticed(
    data_dir: Path, no_probe: None
) -> None:
    """The §7 corrections clock needs the record to survive until acted on.

    Before the fix the not-refetched branch rebuilt the row from scratch, so a
    re-issue was visible for one run and then gone.
    """
    first = capture_area(LEAD_AREA, FakeClient([_attachment(len(PDF_A))], PDF_A))
    second = capture_area(LEAD_AREA, FakeClient([_attachment(len(PDF_B))], PDF_B))
    third = capture_area(LEAD_AREA, FakeClient([_attachment(len(PDF_B))], PDF_B))

    assert third.releases[0].superseded_sha256 == first.releases[0].sha256
    assert third.releases[0].superseded_on == second.releases[0].superseded_on
    assert third.reissued == [], "an old re-issue must not re-alarm on every cron run"
    assert _manifest_rows()[0]["superseded_sha256"] == first.releases[0].sha256


def test_refresh_keeps_an_existing_supersede_record(data_dir: Path, no_probe: None) -> None:
    first = capture_area(LEAD_AREA, FakeClient([_attachment(len(PDF_A))], PDF_A))
    capture_area(LEAD_AREA, FakeClient([_attachment(len(PDF_B))], PDF_B))
    refreshed = capture_area(LEAD_AREA, FakeClient([_attachment(len(PDF_B))], PDF_B), refresh=True)
    assert refreshed.releases[0].superseded_sha256 == first.releases[0].sha256
    assert refreshed.reissued == []


def test_reissue_under_a_new_filename_is_still_a_supersede(data_dir: Path, no_probe: None) -> None:
    """A corrected PDF can arrive under a different filename in the same
    release directory. Keyed by path it looked like a new release and the old
    row silently vanished; keyed by release number it is the supersede it is."""
    first = capture_area(LEAD_AREA, FakeClient([_attachment(len(PDF_A))], PDF_A))
    renamed = _attachment(len(PDF_B), filename="ad_5599_corrected.pdf")
    second = capture_area(LEAD_AREA, FakeClient([renamed], PDF_B))

    assert len(second.releases) == 1, "one release, not an original plus a stranger"
    assert second.releases[0].path.endswith("ad_5599_corrected.pdf")
    assert second.releases[0].superseded_sha256 == first.releases[0].sha256
    assert second.reissued == second.releases


def test_releases_that_age_off_the_live_page_stay_in_the_manifest(
    data_dir: Path, no_probe: None
) -> None:
    """GOV.UK drops the previous year every January. The files are still on
    disk and every analysis command reads the manifest, so the rows must stay."""
    old = _attachment(len(PDF_A), release_no="5569", published_on=date(2026, 1, 7))
    new = _attachment(
        len(PDF_B), release_no="5640", filename="AD_5640.pdf", published_on=date(2027, 1, 6)
    )
    capture_area(LEAD_AREA, FakeClient([old], PDF_A))

    january = capture_area(LEAD_AREA, FakeClient([new], PDF_B))

    by_release = {row.release_no: row for row in january.releases}
    assert set(by_release) == {"5569", "5640"}
    assert by_release["5569"].live is False
    assert by_release["5640"].live is True
    assert [r.release_no for r in january.releases] == ["5569", "5640"], "oldest first"
    assert january.carried == [by_release["5569"]]
    assert [row["release_no"] for row in _manifest_rows()] == ["5569", "5640"]

    # And it round-trips: a later run still sees the archived release.
    later = capture_area(LEAD_AREA, FakeClient([new], PDF_B))
    assert {r.release_no: r.live for r in later.releases} == {"5569": False, "5640": True}


def test_a_carried_row_whose_file_is_gone_is_dropped(data_dir: Path, no_probe: None) -> None:
    """The manifest describes what is on disk. Delete the file, lose the row."""
    result = capture_area(LEAD_AREA, FakeClient([_attachment(len(PDF_A))], PDF_A))
    Path(result.releases[0].path).unlink()
    assert capture_area(LEAD_AREA, FakeClient([], PDF_A)).releases == []


def test_limit_leaves_the_unreached_releases_live(data_dir: Path, no_probe: None) -> None:
    older = _attachment(len(PDF_A), release_no="5598", filename="AD_5598.pdf")
    newer = _attachment(len(PDF_A), release_no="5599")
    capture_area(LEAD_AREA, FakeClient([older, newer], PDF_A))

    client = FakeClient([older, newer], PDF_A)
    limited = capture_area(LEAD_AREA, client, limit=1, refresh=True)
    assert client.fetches == [newer.url], "limit should touch only the newest"
    assert {r.release_no: r.live for r in limited.releases} == {"5598": True, "5599": True}


def test_interrupt_does_not_truncate_the_manifest(data_dir: Path, no_probe: None) -> None:
    """Ctrl-C half-way through a region used to leave a manifest holding only
    the releases reached so far."""
    first = _attachment(len(PDF_A), release_no="5598", filename="AD_5598.pdf")
    second = _attachment(len(PDF_A), release_no="5599")
    capture_area(LEAD_AREA, FakeClient([first, second], PDF_A))

    class Interrupting(FakeClient):
        def get(self, url: str) -> FakeResponse:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        capture_area(LEAD_AREA, Interrupting([first, second], PDF_A), refresh=True)
    assert [row["release_no"] for row in _manifest_rows()] == ["5598", "5599"]


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
