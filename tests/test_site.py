"""The static landing site (spec §4.8) and its dry-run guard.

The guard is the point: a landing page that looks live but has dead Stripe
links is worse than an obviously unfinished one. A build with any placeholder
unresolved must say so loudly and must not be indexable — and "any" includes
the legal placeholders, because three Stripe links used to be enough to drop
the noindex and the "needs a solicitor" caveat while the data controller was
still "[ENTITY NAME]".
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest

from haulier.config import settings
from haulier.site.build import (
    CHECKOUT_PLACEHOLDERS,
    LEGAL_PLACEHOLDERS,
    PLACEHOLDERS,
    PRICING,
    build_site,
)


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Placeholders resolve through `Settings`, which is cached and reads `.env`
    from the working directory. Run each test from an empty directory so a
    developer's own `.env` cannot make a dry-run test see a live build."""
    monkeypatch.chdir(tmp_path)
    settings.cache_clear()
    yield
    settings.cache_clear()


def _resolve_all(monkeypatch: pytest.MonkeyPatch) -> None:
    for placeholder in CHECKOUT_PLACEHOLDERS:
        monkeypatch.setenv(placeholder.env, f"https://buy.stripe.test/{placeholder.key}")
    monkeypatch.setenv("HAULIER_LEGAL_ENTITY", "Example Data Ltd")
    monkeypatch.setenv("HAULIER_LEGAL_PROCESSORS", "Cloudflare (EU) and Stripe (US, SCCs).")
    monkeypatch.setenv("HAULIER_LEGAL_JURISDICTION", "England and Wales.")
    settings.cache_clear()


@pytest.fixture
def built(tmp_path: Path) -> Path:
    build_site(tmp_path / "dist", sample=Path("does-not-exist.html"), today=date(2026, 8, 30))
    return tmp_path / "dist"


def test_builds_every_page(built: Path) -> None:
    for name in ("index.html", "privacy.html", "terms.html", "sample.html", "site.css"):
        assert (built / name).exists(), name


def test_dry_run_is_loud_and_not_indexable(built: Path) -> None:
    index = (built / "index.html").read_text(encoding="utf-8")
    assert "Dry run build" in index
    assert 'content="noindex,nofollow"' in index
    for placeholder in PLACEHOLDERS:
        assert placeholder.env in index, f"{placeholder.env} not named in the banner"


def test_stub_links_go_nowhere_real(built: Path) -> None:
    index = (built / "index.html").read_text(encoding="utf-8")
    assert "stripe.com" not in index
    assert index.count('href="#stub-') == len(CHECKOUT_PLACEHOLDERS)


def test_legal_pages_say_they_are_drafts_while_unresolved(built: Path) -> None:
    privacy = (built / "privacy.html").read_text(encoding="utf-8")
    assert "[ENTITY NAME" in privacy
    assert "<strong>Draft.</strong>" in privacy and "solicitor" in privacy


def test_resolved_build_drops_the_banner_and_indexes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _resolve_all(monkeypatch)
    result = build_site(tmp_path / "live", sample=Path("nope.html"))
    index = (tmp_path / "live" / "index.html").read_text(encoding="utf-8")
    privacy = (tmp_path / "live" / "privacy.html").read_text(encoding="utf-8")

    assert result.unresolved == []
    assert not result.dry_run
    assert "Dry run build" not in index
    assert 'content="index,follow"' in index
    assert "https://buy.stripe.test/checkout_founding" in index
    assert "#stub-" not in index
    assert "Example Data Ltd" in privacy
    assert "[" not in privacy.split("<main")[1].split("</main>")[0], "no bracketed stubs left"
    assert "<strong>Draft.</strong>" not in privacy and "solicitor" not in privacy


def test_stripe_links_alone_do_not_make_the_build_live(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The regression: with only the checkout URLs set, the old build reported
    itself live-ready, indexed, and dropped the solicitor caveat while the
    privacy notice still named "[ENTITY NAME]" as the data controller."""
    for placeholder in CHECKOUT_PLACEHOLDERS:
        monkeypatch.setenv(placeholder.env, f"https://buy.stripe.test/{placeholder.key}")
    settings.cache_clear()
    result = build_site(tmp_path / "half", sample=Path("nope.html"))
    index = (tmp_path / "half" / "index.html").read_text(encoding="utf-8")
    privacy = (tmp_path / "half" / "privacy.html").read_text(encoding="utf-8")

    assert result.dry_run
    assert {p.key for p in result.unresolved} == {p.key for p in LEGAL_PLACEHOLDERS}
    assert 'content="noindex,nofollow"' in index
    assert "HAULIER_LEGAL_ENTITY" in index, "the banner must name what is missing"
    assert "#stub-" not in index, "the Stripe links themselves are live"
    assert "<strong>Draft.</strong>" in privacy and "solicitor" in privacy


def test_placeholders_resolve_from_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`.env.example` says to copy it to `.env`; the site builder used to read
    `os.environ` directly and ignore the file."""
    for placeholder in PLACEHOLDERS:
        monkeypatch.delenv(placeholder.env, raising=False)
    (tmp_path / ".env").write_text(
        "HAULIER_CHECKOUT_SINGLE_URL=https://buy.stripe.test/from-dotenv\n"
        "HAULIER_LEGAL_ENTITY=Dotenv Data Ltd\n",
        encoding="utf-8",
    )
    settings.cache_clear()
    result = build_site(tmp_path / "dist", sample=Path("nope.html"))
    index = (tmp_path / "dist" / "index.html").read_text(encoding="utf-8")
    privacy = (tmp_path / "dist" / "privacy.html").read_text(encoding="utf-8")

    assert "https://buy.stripe.test/from-dotenv" in index
    assert "Dotenv Data Ltd" in privacy
    assert result.dry_run, "the other placeholders are still unresolved"
    assert "HAULIER_CHECKOUT_SINGLE_URL" not in index
    assert "HAULIER_CHECKOUT_ALL_URL" in index


def test_sample_is_copied_when_present(tmp_path: Path) -> None:
    sample = tmp_path / "digest.html"
    sample.write_text("<p>A CSV of all 131 leads is attached.</p>", encoding="utf-8")
    result = build_site(tmp_path / "dist", sample=sample)
    assert result.sample_source == sample
    assert "131 leads" in (tmp_path / "dist" / "sample.html").read_text(encoding="utf-8")
    # The count on the landing page is read from the sample, never hardcoded.
    assert "131 leads" in (tmp_path / "dist" / "index.html").read_text(encoding="utf-8")


def test_privacy_notice_carries_the_objection_route(built: Path) -> None:
    from haulier.config import settings

    privacy = (built / "privacy.html").read_text(encoding="utf-8")
    assert settings().objection_route in privacy
    assert "legitimate interests" in privacy
    assert "Article 14" in privacy, "Art. 14 applies — the data did not come from the subject"
    assert "Information Commissioner" in privacy


def test_pricing_matches_the_recorded_decision(built: Path) -> None:
    """PLAN §4 decision 6 — £49 founding, £79/£149 list."""
    index = (built / "index.html").read_text(encoding="utf-8")
    assert PRICING["founding_single"] == 49
    assert PRICING["single_region"] == 79
    assert PRICING["all_regions"] == 149
    assert "£49" in index and "£149" in index and "£79" in index


def test_build_is_idempotent(tmp_path: Path) -> None:
    first = build_site(tmp_path / "d", sample=Path("nope.html"), today=date(2026, 8, 30))
    before = (tmp_path / "d" / "index.html").read_text(encoding="utf-8")
    build_site(tmp_path / "d", sample=Path("nope.html"), today=date(2026, 8, 30))
    assert (tmp_path / "d" / "index.html").read_text(encoding="utf-8") == before
    assert first.dry_run
