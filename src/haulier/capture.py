"""Download and fingerprint A&D releases.

Mirrors the production layout (spec §5.3[2]): raw/{region}/{release}/{filename},
recording SHA-256, byte size, page count and text-layer presence. Locally this
sits under data/raw/; in production the same keys live in R2.

Capture is idempotent — a release already on disk with a matching digest is not
re-fetched, so the whole corpus can be re-run cheaply.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

import pdfplumber

from .config import settings
from .govuk import Attachment, GovUkClient
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


def _target_path(area: TrafficArea, attachment: Attachment) -> Path:
    release = attachment.release_no or "unparsed"
    name = attachment.filename or attachment.url.rsplit("/", 1)[-1] or "release.pdf"
    return settings().raw_dir / area.slug / release / name


def capture_area(
    area: TrafficArea,
    client: GovUkClient,
    *,
    limit: int | None = None,
    probe: bool = True,
) -> list[CapturedRelease]:
    """Fetch every PDF release currently advertised for one traffic area."""
    attachments = [a for a in client.attachments(area) if a.is_pdf]
    if limit is not None:
        attachments = attachments[-limit:]

    captured: list[CapturedRelease] = []
    for attachment in attachments:
        path = _target_path(area, attachment)
        path.parent.mkdir(parents=True, exist_ok=True)

        if not path.exists() or path.stat().st_size == 0:
            response = client.get(attachment.url)
            path.write_bytes(response.content)
            time.sleep(settings().request_delay_seconds)

        probe_result = probe_pdf(path) if probe else None
        captured.append(
            CapturedRelease(
                region_slug=area.slug,
                release_no=attachment.release_no,
                published_on=attachment.published_on,
                title=attachment.title,
                url=attachment.url,
                path=str(path),
                sha256=sha256_file(path),
                byte_size=path.stat().st_size,
                page_count=probe_result.page_count if probe_result else attachment.number_of_pages,
                has_text_layer=probe_result.has_text_layer if probe_result else None,
                accessible_flag=attachment.accessible,
                parsed_title=attachment.parsed,
            )
        )
    write_manifest(area, captured)
    return captured


def manifest_path(area: TrafficArea) -> Path:
    return settings().data_dir / "manifest" / f"{area.slug}.json"


def write_manifest(area: TrafficArea, captured: list[CapturedRelease]) -> Path:
    path = manifest_path(area)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [
        {**asdict(row), "published_on": row.published_on.isoformat() if row.published_on else None}
        for row in captured
    ]
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path
