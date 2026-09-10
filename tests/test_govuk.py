"""Content API client — title parsing and retry policy.

Title parsing is the format-drift alarm (a title that will not parse must be
reported, never guessed at), so its cases are pinned here: the `AD_6720`
underscore form that appeared live on 5 Aug 2026, and the stray PSV `NP`
documents that decide stream membership by prefix rather than by page.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import httpx
import pytest

from haulier.govuk import GovUkClient, _attachment_from_json


def _att(title: str, **extra: Any) -> Any:
    return _attachment_from_json(
        "the-east-of-england",
        {"title": title, "url": "u", "filename": "f", "content_type": "application/pdf", **extra},
    )


def test_parses_the_hyphen_form() -> None:
    a = _att("AD - 7167 31 July 2026 (objection deadline 21 August 2026)")
    assert (a.doc_type, a.release_no) == ("AD", "7167")
    assert a.published_on == date(2026, 7, 31)
    assert a.objection_deadline == date(2026, 8, 21)
    assert a.parsed and a.is_goods


def test_parses_the_underscore_form() -> None:
    """Seen live 5 Aug 2026 on North East and Wales."""
    a = _att("AD_6720 05 August 2026 (objection deadline 26 August 2026)")
    assert (a.doc_type, a.release_no) == ("AD", "6720")
    assert a.published_on == date(2026, 8, 5)


def test_psv_documents_are_not_goods() -> None:
    a = _att("NP - 2465 06 April 2026 (objection deadline 27 April 2026)")
    assert a.doc_type == "NP"
    assert not a.is_goods


def test_unparsed_title_is_reported_not_guessed() -> None:
    a = _att("Applications and Decisions, some new format")
    assert not a.parsed
    assert a.release_no is None and a.published_on is None
    assert a.is_goods  # no NP prefix, so it stays in the goods stream for triage


def test_missing_deadline_is_none() -> None:
    assert _att("AD - 7167 31 July 2026").objection_deadline is None


def _client_over(handler: Any) -> GovUkClient:
    client = GovUkClient()
    client._client = httpx.Client(transport=httpx.MockTransport(handler))
    return client


def test_client_does_not_retry_a_404() -> None:
    """A 404 is an answer, not a blip — retrying it just costs three backoffs."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(404)

    with _client_over(handler) as client, pytest.raises(httpx.HTTPStatusError):
        client.get("https://www.gov.uk/missing")
    assert calls["n"] == 1


def test_client_retries_a_500(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("haulier.govuk.time.sleep", lambda _s: None)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200 if calls["n"] == 3 else 503)

    with _client_over(handler) as client:
        assert client.get("https://www.gov.uk/flaky").status_code == 200
    assert calls["n"] == 3


def test_client_gives_up_after_the_retry_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("haulier.govuk.time.sleep", lambda _s: None)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503)

    with _client_over(handler) as client, pytest.raises(httpx.HTTPStatusError):
        client.get("https://www.gov.uk/down")
    assert calls["n"] == 3
