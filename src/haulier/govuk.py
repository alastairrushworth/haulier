"""GOV.UK Content API client for Applications & Decisions guidance pages.

The guidance pages expose a structured attachment list at /api/content/<path>,
so the watcher never needs to scrape HTML (PLAN.md §1.3). Each attachment
carries url, filename, content_type, file_size, number_of_pages and an
`accessible` flag. The flag reports formal accessibility compliance only — it
is NOT a text-layer signal (PLAN.md §1.3); the pdfplumber probe is the only
ground truth for extractability.

Release number and publication date live in the attachment *title*, not in a
dedicated field, so they are parsed here. A title that will not parse is
recorded as unparsed rather than guessed at (spec §5.3[1]).

Two things learned from unparsed titles in the wild (Aug 2026):
  * PSV "Notices and Proceedings" (NP) documents occasionally appear on the
    goods pages — NP-2465 on Scotland's, NP-3198 on West Midlands'. The page
    does not guarantee the stream; the AD/NP title prefix does.
  * The separator drifts: "AD - 6720" and "AD_6720" both occur (the
    underscore form first seen North East & Wales, 5 Aug 2026).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import httpx

from .config import settings
from .sources import TrafficArea

# Observed across all 8 regions, e.g.
#   "AD - 7167 31 July 2026 (objection deadline 21 August 2026)"
#   "AD_6720 05 August 2026 (objection deadline 26 August 2026)"
#   "NP - 2465 06 April 2026 (objection deadline 27 April 2026)"   <- PSV
_TITLE_RE = re.compile(
    r"""
    (?P<kind>AD|NP) \s* [-‐-―_] \s* (?P<release>\d+)      # "AD - 7167" / "AD_6720"
    \s+ (?P<published>\d{1,2}\s+\w+\s+\d{4})          # "31 July 2026"
    (?: .*? objection \s+ deadline \s+
        (?P<deadline>\d{1,2}\s+\w+\s+\d{4}) )?        # optional deadline
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)


def _parse_uk_date(raw: str) -> date | None:
    for fmt in ("%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    return None


@dataclass(frozen=True, slots=True)
class Attachment:
    """One A&D release as advertised by the Content API."""

    region_slug: str
    title: str
    url: str
    filename: str
    content_type: str
    file_size: int | None = None
    number_of_pages: int | None = None
    attachment_id: str | None = None
    accessible: bool | None = None
    release_no: str | None = None
    published_on: date | None = None
    objection_deadline: date | None = None
    doc_type: str | None = None
    """'AD' (goods) or 'NP' (PSV) from the title prefix; None when unparsed."""

    @property
    def is_goods(self) -> bool:
        """PSV documents stray onto the goods pages; the title prefix is the
        stream membership test, not the page (see module docstring)."""
        return self.doc_type != "NP"

    @property
    def parsed(self) -> bool:
        """False when the title did not yield a release number and date.

        An unparsed title is a format-change signal, not something to paper
        over — the caller should alarm rather than fall back to a guess.
        """
        return self.release_no is not None and self.published_on is not None

    @property
    def is_pdf(self) -> bool:
        return self.content_type == "application/pdf"


def _attachment_from_json(region_slug: str, raw: dict[str, Any]) -> Attachment:
    title = str(raw.get("title", ""))
    match = _TITLE_RE.search(title)
    release_no = published_on = deadline = doc_type = None
    if match:
        doc_type = match.group("kind").upper()
        release_no = match.group("release")
        published_on = _parse_uk_date(match.group("published"))
        if match.group("deadline"):
            deadline = _parse_uk_date(match.group("deadline"))
    return Attachment(
        region_slug=region_slug,
        title=title,
        url=str(raw.get("url", "")),
        filename=str(raw.get("filename", "")),
        content_type=str(raw.get("content_type", "")),
        file_size=raw.get("file_size"),
        number_of_pages=raw.get("number_of_pages"),
        attachment_id=str(raw["id"]) if raw.get("id") is not None else None,
        accessible=raw.get("accessible"),
        release_no=release_no,
        published_on=published_on,
        objection_deadline=deadline,
        doc_type=doc_type,
    )


@dataclass
class GovUkClient:
    """Polite, retrying HTTP client. Identifies honestly per spec §8.2."""

    _client: httpx.Client = field(init=False)

    def __post_init__(self) -> None:
        cfg = settings()
        self._client = httpx.Client(
            headers={"User-Agent": cfg.user_agent, "Accept-Encoding": "gzip, deflate"},
            timeout=cfg.request_timeout_seconds,
            follow_redirects=True,
        )

    def __enter__(self) -> GovUkClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def get(self, url: str) -> httpx.Response:
        cfg = settings()
        last: Exception | None = None
        for attempt in range(cfg.http_retries):
            try:
                response = self._client.get(url)
                if response.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        f"{response.status_code} from {url}",
                        request=response.request,
                        response=response,
                    )
                response.raise_for_status()
                return response
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                last = exc
                if attempt < cfg.http_retries - 1:
                    time.sleep(2**attempt)
        assert last is not None
        raise last

    def attachments(self, area: TrafficArea) -> list[Attachment]:
        """Every attachment currently advertised on a traffic area's page.

        Note this is the *live* list: GOV.UK retains only the current year and
        archives the rest to the National Archives, so this shrinks abruptly
        each January (PLAN.md §1.3).
        """
        payload = self.get(area.content_api_url).json()
        raw = payload.get("details", {}).get("attachments", []) or []
        time.sleep(settings().request_delay_seconds)
        return [_attachment_from_json(area.slug, item) for item in raw]
