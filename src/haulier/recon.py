"""Corpus analysis over the cached text dumps.

Stage 0 items 3 and 4 (PLAN.md §3): the heading frequency table that seeds
`section_heading_map`, and the licence-number harvest that validates the
`^[OP][A-Z][0-9]{6,7}$` assumption and the prefix→region map against the full
2026 corpus rather than the 32-document sample in PLAN.md §1.5.

Heading detection runs the §2.10 detectors in priority order: statutory
S-marker regex first, font/size outlier second. Anything the analysis can't
place is still counted — recon reports what the documents do, it never guesses.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from .sources import TrafficArea

#: PLAN.md §2.10 detector 1 — statutory section marker with the outcome phrase
#: on the same line, e.g. "S13 - Application granted as applied for".
#:
#: `Sch.3` (transport-manager repute under Schedule 3) is a marker too, and the
#: most frequent heading in the whole corpus — 200 occurrences across 29 of the
#: 31 East of England releases. An `S\d` anchor cannot see it, so it was missing
#: from the taxonomy this seeds. `Sch\.?\s?3` matches it without swallowing the
#: Schedule 4 prose paragraph, which carries no separator after the number.
MARKER_RE = re.compile(r"^\s*(S|Sch)\s*\.?\s*(\d{1,3}[A-Z]?)\s*[-–—]\s*(\S.*)$")


def marker_of(line: str) -> str | None:
    """'Sch.3 - …' → 'Sch.3'; 'S13 - …' → 'S13'; prose → None."""
    match = MARKER_RE.match(line)
    if not match:
        return None
    prefix, number = match.group(1), match.group(2)
    return f"Sch.{number}" if prefix == "Sch" else f"S{number}"


#: The spec's licence-number shape, held so far against ~2,900 observations.
LICENCE_RE = re.compile(r"\b([OP][A-Z])(\d{6,7})\b")

#: Deliberately looser sweep. Anything this catches that LICENCE_RE does not
#: is either noise or evidence the spec's regex is wrong — reported, not judged.
NEAR_MISS_RE = re.compile(r"\b[A-Z]{1,2}\d{5,8}\b")

_WORDY = re.compile(r"[A-Za-z]{3}")


def _normalise(text: str) -> str:
    return " ".join(text.split())


def _body_size(pages: list[dict[str, Any]]) -> float | None:
    """Modal line size for one release — the baseline the outlier test needs."""
    sizes = Counter(line["s"] for page in pages for line in page["lines"] if line["s"] is not None)
    return sizes.most_common(1)[0][0] if sizes else None


@dataclass
class HeadingStats:
    releases: int = 0
    markers: Counter[str] = field(default_factory=Counter)
    marker_releases: dict[str, set[str]] = field(default_factory=dict)
    headings: Counter[str] = field(default_factory=Counter)
    heading_releases: dict[str, set[str]] = field(default_factory=dict)


def analyse_headings(dumps: list[dict[str, Any]]) -> HeadingStats:
    stats = HeadingStats(releases=len(dumps))
    for dump in dumps:
        release = dump.get("release_no") or dump["sha256"][:12]
        body = _body_size(dump["pages"])
        for page in dump["pages"]:
            for line in page["lines"]:
                text = _normalise(line["t"])
                if len(text) < 4 or not _WORDY.search(text):
                    continue

                marker = marker_of(text)
                if marker:
                    stats.markers[marker] += 1
                    stats.marker_releases.setdefault(marker, set()).add(release)
                    stats.headings[text] += 1
                    stats.heading_releases.setdefault(text, set()).add(release)
                    continue

                # Font outlier: bigger than body text, or bold at body size.
                # Lines carrying a licence number are record starts, not
                # section headings — useful to the segmenter later, noise here.
                if body is None or line["s"] is None or LICENCE_RE.search(text):
                    continue
                outlier = line["s"] >= body + 0.6 or (line["b"] and line["s"] >= body)
                if outlier and len(text) <= 90:
                    stats.headings[text] += 1
                    stats.heading_releases.setdefault(text, set()).add(release)
    return stats


@dataclass
class LicenceStats:
    releases: int = 0
    occurrences: int = 0
    distinct: Counter[str] = field(default_factory=Counter)
    prefixes: Counter[str] = field(default_factory=Counter)
    per_release_distinct: list[int] = field(default_factory=list)
    near_miss_shapes: Counter[str] = field(default_factory=Counter)
    near_miss_examples: dict[str, str] = field(default_factory=dict)


def analyse_licences(dumps: list[dict[str, Any]]) -> LicenceStats:
    stats = LicenceStats(releases=len(dumps))
    for dump in dumps:
        seen_this_release: set[str] = set()
        for page in dump["pages"]:
            for line in page["lines"]:
                text = line["t"]
                matched_spans: list[tuple[int, int]] = []
                for match in LICENCE_RE.finditer(text):
                    matched_spans.append(match.span())
                    licence = match.group(0)
                    stats.occurrences += 1
                    stats.distinct[licence] += 1
                    seen_this_release.add(licence)
                for near in NEAR_MISS_RE.finditer(text):
                    if any(a <= near.start() and near.end() <= b for a, b in matched_spans):
                        continue
                    token = near.group(0)
                    letters = token.rstrip("0123456789")
                    shape = f"{letters}{'#' * (len(token) - len(letters))}"
                    stats.near_miss_shapes[shape] += 1
                    stats.near_miss_examples.setdefault(shape, token)
        stats.per_release_distinct.append(len(seen_this_release))
    for licence in stats.distinct:
        stats.prefixes[licence[:2]] += 1
    return stats


def home_share(stats: LicenceStats, area: TrafficArea) -> float | None:
    total = sum(stats.prefixes.values())
    if not total:
        return None
    return stats.prefixes.get(area.licence_prefix, 0) / total


def foreign_licences(stats: LicenceStats, area: TrafficArea) -> list[tuple[str, int]]:
    """Distinct licences whose prefix is not the area's own, by occurrence count."""
    return sorted(
        (
            (licence, count)
            for licence, count in stats.distinct.items()
            if licence[:2] != area.licence_prefix
        ),
        key=lambda item: -item[1],
    )


def _marker_sort_key(marker: str) -> tuple[str, int, str]:
    """Group by statute (S before Sch), then numerically — S9 before S13."""
    digits = "".join(ch for ch in marker if ch.isdigit())
    return ("Sch" if marker.startswith("Sch") else "S", int(digits or 0), marker)


def headings_payload(stats: HeadingStats, min_releases: int = 2) -> dict[str, Any]:
    """JSON-ready summary. Headings seen in a single release are dropped —
    they are overwhelmingly operator names and dates, not section structure."""
    return {
        "releases": stats.releases,
        "markers": {
            marker: {
                "occurrences": stats.markers[marker],
                "releases": len(stats.marker_releases[marker]),
            }
            for marker in sorted(stats.markers, key=_marker_sort_key)
        },
        "headings": [
            {
                "text": text,
                "occurrences": count,
                "releases": len(stats.heading_releases[text]),
            }
            for text, count in stats.headings.most_common()
            if len(stats.heading_releases[text]) >= min_releases or marker_of(text)
        ],
    }


def licences_payload(stats: LicenceStats, area: TrafficArea) -> dict[str, Any]:
    share = home_share(stats, area)
    mean_distinct = (
        sum(stats.per_release_distinct) / len(stats.per_release_distinct)
        if stats.per_release_distinct
        else 0.0
    )
    return {
        "releases": stats.releases,
        "occurrences": stats.occurrences,
        "distinct_total": len(stats.distinct),
        "mean_distinct_per_release": round(mean_distinct, 1),
        "home_prefix": area.licence_prefix,
        "home_prefix_share": round(share, 4) if share is not None else None,
        "prefixes": dict(stats.prefixes.most_common()),
        "foreign": [
            {"licence": licence, "occurrences": count}
            for licence, count in foreign_licences(stats, area)
        ],
        "near_miss_shapes": [
            {
                "shape": shape,
                "occurrences": count,
                "example": stats.near_miss_examples[shape],
            }
            for shape, count in stats.near_miss_shapes.most_common(20)
        ],
    }
