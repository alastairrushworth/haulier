"""Download and fingerprint A&D releases.

Mirrors the production layout (spec §5.3[2]): raw/{region}/{release}/{filename},
recording SHA-256, byte size, page count and text-layer presence. Locally this
sits under data/raw/; in production the same keys live in R2.

Capture is idempotent — a release already on disk whose bytes still match what
the Content API advertises is not re-fetched, so the whole corpus can be re-run
cheaply. When the advertised size *has* changed, the release is re-fetched and
the digest it replaced is recorded on the row: that is the only signal we get
that GOV.UK re-issued a document, and spec §5.3[2] supersede handling and the
§7 corrections SLO both depend on noticing it.

Per-release faults are isolated. An unreadable PDF records its probe error and
the run continues; a failed fetch is reported and the previously captured row
carried forward. A manifest that loses releases because one document was
malformed is worse than no manifest at all.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import pdfplumber

from .config import settings
from .govuk import Attachment, ReleaseSource
from .sources import TrafficArea


@dataclass(frozen=True, slots=True)
class PdfProbe:
    page_count: int
    sample_chars: int
    has_text_layer: bool


def probe_pdf(path: Path, sample_pages: int = 3) -> PdfProbe:
    """Check whether a PDF carries an extractable text layer.

    Ground truth for the OCR-fallback alarm in spec §5.3[2]. The Content API's
    `accessible` flag is an earlier but weaker signal; this is the real test.
    """
    with pdfplumber.open(path) as pdf:
        page_count = len(pdf.pages)
        sample = pdf.pages[: min(sample_pages, page_count)]
        chars = sum(len(page.extract_text() or "") for page in sample)
    return PdfProbe(page_count=page_count, sample_chars=chars, has_text_layer=chars > 200)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class CapturedRelease:
    region_slug: str
    release_no: str | None
    published_on: date | None
    title: str
    url: str
    path: str
    sha256: str
    byte_size: int
    page_count: int | None
    has_text_layer: bool | None
    accessible_flag: bool | None
    parsed_title: bool
    probe_error: str | None = None
    """Why the text-layer probe could not run. `has_text_layer` is None when set."""
    superseded_sha256: str | None = None
    """The digest this fetch replaced — non-None means the source re-issued."""

    def as_manifest_row(self) -> dict[str, Any]:
        row = asdict(self)
        row["published_on"] = self.published_on.isoformat() if self.published_on else None
        return row

    @classmethod
    def from_manifest_row(cls, row: dict[str, Any]) -> CapturedRelease:
        published = row.get("published_on")
        return cls(
            region_slug=row["region_slug"],
            release_no=row.get("release_no"),
            published_on=date.fromisoformat(published) if published else None,
            title=row["title"],
            url=row["url"],
            path=row["path"],
            sha256=row["sha256"],
            byte_size=row["byte_size"],
            page_count=row.get("page_count"),
            has_text_layer=row.get("has_text_layer"),
            accessible_flag=row.get("accessible_flag"),
            parsed_title=row["parsed_title"],
            probe_error=row.get("probe_error"),
            superseded_sha256=row.get("superseded_sha256"),
        )


@dataclass(frozen=True, slots=True)
class CaptureResult:
    """What one area's capture produced, plus anything that went wrong."""

    releases: list[CapturedRelease]
    failures: list[tuple[str, str]] = field(default_factory=list)
    """(title, error) for releases that could not be fetched at all."""

    def __len__(self) -> int:
        return len(self.releases)


def _target_path(area: TrafficArea, attachment: Attachment) -> Path:
    release = attachment.release_no or "unparsed"
    name = attachment.filename or attachment.url.rsplit("/", 1)[-1] or "release.pdf"
    return settings().raw_dir / area.slug / release / name


def previous_rows(area: TrafficArea) -> dict[str, dict[str, Any]]:
    """The last manifest for an area, keyed by path. Empty if absent or corrupt."""
    path = manifest_path(area)
    if not path.exists():
        return {}
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {row["path"]: row for row in rows if row.get("path")}


def _needs_fetch(path: Path, attachment: Attachment, *, refresh: bool) -> bool:
    """Whether the bytes on disk are still the bytes GOV.UK is advertising.

    The Content API gives `file_size`, which is the only re-issue signal
    available without downloading. It is not a digest, so it cannot catch a
    same-length edit — `--refresh` exists for that.
    """
    if refresh or not path.exists():
        return True
    on_disk = path.stat().st_size
    if on_disk == 0:
        return True
    return attachment.file_size is not None and attachment.file_size != on_disk


def _capture_one(
    area: TrafficArea,
    attachment: Attachment,
    client: ReleaseSource,
    prior: dict[str, Any] | None,
    *,
    probe: bool,
    refresh: bool,
) -> CapturedRelease:
    path = _target_path(area, attachment)
    path.parent.mkdir(parents=True, exist_ok=True)

    superseded: str | None = None
    if _needs_fetch(path, attachment, refresh=refresh):
        response = client.get(attachment.url)
        path.write_bytes(response.content)
        time.sleep(settings().request_delay_seconds)
        digest = sha256_file(path)
        if prior and prior.get("sha256") and prior["sha256"] != digest:
            superseded = str(prior["sha256"])
    else:
        digest = sha256_file(path)

    probe_result: PdfProbe | None = None
    probe_error: str | None = None
    if probe:
        try:
            probe_result = probe_pdf(path)
        except Exception as exc:  # noqa: BLE001 — one bad PDF must not sink the run
            probe_error = f"{type(exc).__name__}: {exc}"

    return CapturedRelease(
        region_slug=area.slug,
        release_no=attachment.release_no,
        published_on=attachment.published_on,
        title=attachment.title,
        url=attachment.url,
        path=str(path),
        sha256=digest,
        byte_size=path.stat().st_size,
        page_count=probe_result.page_count if probe_result else attachment.number_of_pages,
        has_text_layer=probe_result.has_text_layer if probe_result else None,
        accessible_flag=attachment.accessible,
        parsed_title=attachment.parsed,
        probe_error=probe_error,
        superseded_sha256=superseded,
    )


def capture_area(
    area: TrafficArea,
    client: ReleaseSource,
    *,
    limit: int | None = None,
    probe: bool = True,
    refresh: bool = False,
) -> CaptureResult:
    """Fetch every goods PDF release currently advertised for one traffic area.

    Stray PSV (NP-prefixed) documents are excluded — the title prefix, not the
    page, decides stream membership (see govuk.py module docstring).

    A release that cannot be fetched is reported in `failures` and its previous
    manifest row carried forward, so a transient network fault never silently
    shortens the manifest.
    """
    attachments = [a for a in client.attachments(area) if a.is_pdf and a.is_goods]
    if limit is not None:
        attachments = attachments[-limit:]

    prior_rows = previous_rows(area)
    captured: list[CapturedRelease] = []
    failures: list[tuple[str, str]] = []
    try:
        for attachment in attachments:
            prior = prior_rows.get(str(_target_path(area, attachment)))
            try:
                captured.append(
                    _capture_one(area, attachment, client, prior, probe=probe, refresh=refresh)
                )
            except Exception as exc:  # noqa: BLE001 — report and keep going
                failures.append((attachment.title, f"{type(exc).__name__}: {exc}"))
                if prior:
                    captured.append(CapturedRelease.from_manifest_row(prior))
    finally:
        write_manifest(area, captured)
    return CaptureResult(releases=captured, failures=failures)


def manifest_path(area: TrafficArea) -> Path:
    return settings().data_dir / "manifest" / f"{area.slug}.json"


def write_manifest(area: TrafficArea, captured: list[CapturedRelease]) -> Path:
    path = manifest_path(area)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [row.as_manifest_row() for row in captured]
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path
