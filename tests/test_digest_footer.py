"""Digest footer — PLAN §2.11 legal deliverables, pulled forward to Stage 0.

The pilot digest sends real directors' names to prospects, so it must carry
the OGL attribution, a working objection route, and the PECR note telling the
subscriber which leads are individuals rather than corporate subscribers.

The objection address defaults to the contact address that already exists, so
the route works from the first send rather than waiting on a static site. The
privacy-notice URL is genuinely not published yet, so it is rendered only when
configured — a placeholder link that 404s is worse than a line of prose.
"""

from __future__ import annotations

from typing import Any

import pytest

from haulier.config import settings
from haulier.digest.leads import build_lead
from haulier.digest.render import render_html


@pytest.fixture
def digest(release: dict[str, Any], record: dict[str, Any]) -> str:
    return render_html(release, [build_lead(record, release)])


def test_ogl_attribution_is_present(digest: str) -> None:
    assert "Open Government Licence v3.0" in digest


def test_objection_route_is_offered(digest: str) -> None:
    assert settings().objection_email in digest
    assert "object" in digest.lower()


def test_pecr_note_explains_the_sole_trader_flag(digest: str) -> None:
    assert "is_sole_trader_or_partnership" in digest
    assert "PECR" in digest


def test_privacy_notice_link_appears_once_configured(
    monkeypatch: pytest.MonkeyPatch, release: dict[str, Any], record: dict[str, Any]
) -> None:
    monkeypatch.setenv("HAULIER_PRIVACY_NOTICE_URL", "https://example.test/privacy")
    settings.cache_clear()
    try:
        html = render_html(release, [build_lead(record, release)])
        assert 'href="https://example.test/privacy"' in html
    finally:
        settings.cache_clear()


def test_no_placeholder_link_when_unconfigured(digest: str) -> None:
    """Better a line of prose than a link that 404s in a prospect's inbox."""
    assert "example.com" not in digest
    assert "TODO" not in digest
    assert "privacy notice" in digest.lower()
