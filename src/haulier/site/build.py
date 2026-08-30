"""Build the static landing site.

Spec §4.8 asks for a one-page landing site carrying the proposition, a sample
issue, Stripe links, the founding offer, an FAQ and legal pages; PLAN §2.11
pulls the privacy notice and a working objection route forward to Stage 0,
because the pilot digest already sends real directors' names to prospects.

Everything that would cost money or need an account is a **placeholder**. A
build with any placeholder unresolved is a dry run: it renders a banner naming
what is missing, marks every stub link, and sets `noindex`. A landing page that
looks live but has dead Stripe links is worse than an obviously unfinished one,
so the dry-run state is loud rather than subtle.

Resolve a placeholder by setting its environment variable (see `.env.example`).
When all of them are set the banner disappears on its own — there is no
separate "production mode" flag to forget to flip.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..config import settings

TEMPLATES = Path(__file__).parent / "templates"

#: The public sample issue. Spec §4.8 wants real data at least two weeks old,
#: and PLAN §2.11 wants people reduced to initials on an open URL.
DEFAULT_SAMPLE = Path("data/pilot/digest_5599_redacted.html")


@dataclass(frozen=True, slots=True)
class Placeholder:
    key: str
    env: str
    note: str
    stub: str

    def resolve(self) -> tuple[str, bool]:
        """(value, is_stub). Falls back to the stub when the env var is unset."""
        value = os.environ.get(self.env, "").strip()
        return (value, False) if value else (self.stub, True)


PLACEHOLDERS: tuple[Placeholder, ...] = (
    Placeholder(
        "checkout_single",
        "HAULIER_CHECKOUT_SINGLE_URL",
        "Stripe Checkout link — single region, list price",
        "#stub-checkout-single-region",
    ),
    Placeholder(
        "checkout_all",
        "HAULIER_CHECKOUT_ALL_URL",
        "Stripe Checkout link — all regions",
        "#stub-checkout-all-regions",
    ),
    Placeholder(
        "checkout_founding",
        "HAULIER_CHECKOUT_FOUNDING_URL",
        "Stripe Checkout link — founding rate",
        "#stub-checkout-founding",
    ),
)

#: Prices live here rather than in the templates so the site, the digest and
#: PLAN §4 decision 6 cannot drift apart.
PRICING = {
    "single_region": 79,
    "all_regions": 149,
    "founding_single": 49,
    "founding_seats": 10,
    "founding_months": 12,
    "annual_months": 10,
}

LEGAL_STUB = {
    "entity": "[ENTITY NAME — set HAULIER_LEGAL_ENTITY]",
    "address": "",
    "processors": (
        "We use Cloudflare for hosting and storage, and Stripe for payments. "
        "[Confirm and list each processor and its location before going live.]"
    ),
    "jurisdiction": (
        "These terms are governed by the law of England and Wales. "
        "[Confirm — set HAULIER_LEGAL_JURISDICTION.]"
    ),
}


@dataclass(frozen=True, slots=True)
class BuildResult:
    out_dir: Path
    pages: list[Path]
    unresolved: list[Placeholder]
    sample_source: Path | None

    @property
    def dry_run(self) -> bool:
        return bool(self.unresolved)


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(TEMPLATES),
        autoescape=select_autoescape(["html", "j2"]),
    )


def _legal() -> dict[str, str]:
    return {
        key: os.environ.get(f"HAULIER_LEGAL_{key.upper()}", "").strip() or stub
        for key, stub in LEGAL_STUB.items()
    }


def _sample_lead_count(sample: Path | None) -> str:
    """Read the lead count out of the rendered sample rather than hardcoding it."""
    if sample is None or not sample.exists():
        return "131"
    text = sample.read_text(encoding="utf-8")
    marker = "A CSV of all "
    start = text.find(marker)
    if start == -1:
        return "131"
    tail = text[start + len(marker) :]
    digits = tail[: tail.find(" ")]
    return digits if digits.isdigit() else "131"


def build_site(
    out_dir: Path,
    *,
    sample: Path | None = None,
    today: date | None = None,
) -> BuildResult:
    """Render the site into `out_dir`. Idempotent; overwrites what it owns."""
    sample = DEFAULT_SAMPLE if sample is None else sample
    sample_source = sample if sample.exists() else None

    values: dict[str, str] = {}
    unresolved: list[Placeholder] = []
    stub_flags: dict[str, bool] = {}
    for placeholder in PLACEHOLDERS:
        value, is_stub = placeholder.resolve()
        values[placeholder.key] = value
        stub_flags[placeholder.key] = is_stub
        if is_stub:
            unresolved.append(placeholder)

    context: dict[str, Any] = {
        "product": "FirstMover",
        "links": values,
        "stub": stub_flags,
        "unresolved": unresolved,
        "dry_run": bool(unresolved),
        "pricing": PRICING,
        "legal": _legal(),
        "objection_email": settings().objection_route,
        "today": (today or date.today()).strftime("%-d %B %Y"),
        "sample_leads": _sample_lead_count(sample_source),
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    env = _env()
    pages: list[Path] = []
    for name in ("index", "privacy", "terms"):
        path = out_dir / f"{name}.html"
        path.write_text(env.get_template(f"{name}.html.j2").render(**context), encoding="utf-8")
        pages.append(path)

    shutil.copyfile(TEMPLATES / "site.css", out_dir / "site.css")

    sample_out = out_dir / "sample.html"
    if sample_source is not None:
        shutil.copyfile(sample_source, sample_out)
    else:
        sample_out.write_text(
            env.get_template("base.html.j2").render(**{**context, "self_titled": "Sample issue"}),
            encoding="utf-8",
        )
    pages.append(sample_out)

    # Cloudflare Pages reads these. Kept minimal and boring on purpose.
    (out_dir / "_headers").write_text(
        "/*\n"
        "  X-Content-Type-Options: nosniff\n"
        "  X-Frame-Options: DENY\n"
        "  Referrer-Policy: strict-origin-when-cross-origin\n"
        "  Permissions-Policy: geolocation=(), microphone=(), camera=()\n",
        encoding="utf-8",
    )
    return BuildResult(
        out_dir=out_dir, pages=pages, unresolved=unresolved, sample_source=sample_source
    )
