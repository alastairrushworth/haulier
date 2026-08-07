"""Per-page text dumps with layout metadata, cached to disk.

Stage 0 items 3 and 4 (PLAN.md §3) both need the full text of every captured
release — headings by font-size outlier, licence numbers by regex. Extraction
is the slow part (~250 PDFs, ~6,000 pages), so it runs once per release and is
cached at data/text/{region}/{release}.json.gz, keyed by the source PDF's
SHA-256. A superseded release whose PDF changed is re-extracted; everything
else is a cache hit, so analysis commands are cheap to re-run.

Each dump stores, per page, the text lines with their median character size
and a bold flag — enough for the §2.10 font-outlier heading detector without
keeping full character-level layout.
"""

from __future__ import annotations

import gzip
import json
import os
from collections.abc import Iterator
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import pdfplumber

from .capture import manifest_path
from .config import settings
from .sources import TrafficArea

SCHEMA_VERSION = 1


def dump_path(region_slug: str, stem: str) -> Path:
    return settings().data_dir / "text" / region_slug / f"{stem}.json.gz"


def _stem(row: dict[str, Any]) -> str:
    return row["release_no"] or f"sha-{row['sha256'][:12]}"


def _extract_lines(page: Any) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    for line in page.extract_text_lines(strip=True, return_chars=True):
        chars = line.get("chars") or []
        sizes = sorted(round(c.get("size", 0.0), 1) for c in chars)
        fonts = [c.get("fontname") or "" for c in chars]
        lines.append(
            {
                "t": line.get("text", ""),
                "s": sizes[len(sizes) // 2] if sizes else None,
                "b": any("bold" in f.lower() for f in fonts),
            }
        )
    return lines


def extract_release(pdf_path: str, out_path: str, meta: dict[str, Any]) -> int:
    """Extract one PDF to its cached dump. Returns the page count.

    Module-level so ProcessPoolExecutor can pickle it. A page that pdfplumber
    chokes on is recorded with an error rather than sinking the whole release.
    """
    pages: list[dict[str, Any]] = []
    with pdfplumber.open(pdf_path) as pdf:
        for index, page in enumerate(pdf.pages, start=1):
            try:
                pages.append({"n": index, "lines": _extract_lines(page)})
            except Exception as exc:  # noqa: BLE001 — per-page fault isolation
                pages.append({"n": index, "lines": [], "error": str(exc)})

    payload = {"version": SCHEMA_VERSION, **meta, "pages": pages}
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(out, "wt", encoding="utf-8") as handle:
        json.dump(payload, handle)
    return len(pages)


def _manifest_rows(area: TrafficArea) -> list[dict[str, Any]]:
    path = manifest_path(area)
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def stale_jobs(area: TrafficArea) -> list[tuple[str, str, dict[str, Any]]]:
    """(pdf_path, out_path, meta) for every release missing a current dump."""
    jobs: list[tuple[str, str, dict[str, Any]]] = []
    for row in _manifest_rows(area):
        if row.get("has_text_layer") is False:
            continue  # needs OCR, not a text dump — surfaced by `status`
        out = dump_path(row["region_slug"], _stem(row))
        if out.exists():
            try:
                with gzip.open(out, "rt", encoding="utf-8") as handle:
                    cached = json.load(handle)
                if (
                    cached.get("sha256") == row["sha256"]
                    and cached.get("version") == SCHEMA_VERSION
                ):
                    continue
            except (OSError, json.JSONDecodeError):
                pass  # unreadable cache — rebuild
        meta = {
            "region_slug": row["region_slug"],
            "release_no": row["release_no"],
            "published_on": row["published_on"],
            "sha256": row["sha256"],
        }
        jobs.append((row["path"], str(out), meta))
    return jobs


def build_dumps(
    jobs: list[tuple[str, str, dict[str, Any]]], workers: int | None = None
) -> Iterator[tuple[str, int | None, str | None]]:
    """Run extraction jobs in parallel; yield (pdf_path, pages, error) as done."""
    workers = workers or max(1, (os.cpu_count() or 4) - 2)
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(extract_release, *job): job[0] for job in jobs}
        for future in as_completed(futures):
            pdf_path = futures[future]
            try:
                yield pdf_path, future.result(), None
            except Exception as exc:  # noqa: BLE001 — report, keep going
                yield pdf_path, None, str(exc)


def iter_dumps(area: TrafficArea) -> Iterator[dict[str, Any]]:
    """Yield the cached dump payload for every release in the area's manifest."""
    for row in _manifest_rows(area):
        path = dump_path(row["region_slug"], _stem(row))
        if not path.exists():
            continue
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            yield json.load(handle)
