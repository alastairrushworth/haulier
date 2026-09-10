"""Build the static landing site.

Spec §4.8 asks for a one-page landing site carrying the proposition, a sample
issue, Stripe links, the founding offer, an FAQ and legal pages; PLAN §2.11
pulls the privacy notice and a working objection route forward to Stage 0,
because the pilot digest already sends real directors' names to prospects.

Everything that would cost money, need an account, or need a solicitor is a
**placeholder**. A build with any placeholder unresolved is a dry run: it
renders a banner naming what is missing, marks every stub link, and sets
`noindex`. A landing page that looks live but has dead Stripe links — or a
privacy notice whose data controller is "[ENTITY NAME]" — is worse than an
obviously unfinished one, so the dry-run state is loud rather than subtle.

Resolve a placeholder by setting its `HAULIER_*` variable, in the environment
or in `.env` (see `.env.example`); they are read through `config.Settings` like
every other setting. When all of them are set the banner disappears on its
own — there is no separate "production mode" flag to forget to flip.
"""

from __future__ import annotations

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
    setting: str
    """Attribute on `config.Settings`; the env var is HAULIER_<SETTING>."""
    note: str
    stub: str

    @property
    def env(self) -> str:
        return f"HAULIER_{self.setting.upper()}"

    def resolve(self) -> tuple[str, bool]:
        """(value, is_stub). Falls back to the stub when the setting is empty."""
        value = str(getattr(settings(), self.setting) or "").strip()
        return (value, False) if value else (self.stub, True)


CHECKOUT_PLACEHOLDERS: tuple[Placeholder, ...] = (
    Placeholder(
        "checkout_single",
        "checkout_single_url",
        "Stripe Checkout link — single region, list price",
        "#stub-checkout-single-region",
    ),
    Placeholder(
        "checkout_all",
        "checkout_all_url",
        "Stripe Checkout link — all regions",
        "#stub-checkout-all-regions",
    ),
    Placeholder(
        "checkout_founding",
        "checkout_founding_url",
        "Stripe Checkout link — founding rate",
        "#stub-checkout-founding",
    ),
)

#: The privacy notice and terms are not publishable with these blank, and the
#: "still needs a solicitor" caveat they carry while `dry_run` is true must not
#: vanish just because the Stripe links arrived.
LEGAL_PLACEHOLDERS: tuple[Placeholder, ...] = (
    Placeholder(
        "legal_entity",
        "legal_entity",
        "Data controller's legal name — privacy notice and terms",
        "[ENTITY NAME — set HAULIER_LEGAL_ENTITY]",
    ),
    Placeholder(
        "legal_processors",
        "legal_processors",
        "Where personal data is processed — each processor and its location",
        "We use Cloudflare for hosting and storage, and Stripe for payments. "
        "[Confirm and list each processor and its location — set HAULIER_LEGAL_PROCESSORS.]",
    ),
    Placeholder(
        "legal_jurisdiction",
        "legal_jurisdiction",
        "Governing law for the terms",
        "These terms are governed by the law of England and Wales. "
        "[Confirm — set HAULIER_LEGAL_JURISDICTION.]",
    ),
)

PLACEHOLDERS: tuple[Placeholder, ...] = CHECKOUT_PLACEHOLDERS + LEGAL_PLACEHOLDERS

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

    legal = {
        "entity": values["legal_entity"],
        "address": settings().legal_address.strip(),  # optional, so not a placeholder
        "processors": values["legal_processors"],
        "jurisdiction": values["legal_jurisdiction"],
    }
    context: dict[str, Any] = {
        "product": "FirstMover",
        "links": values,
        "stub": stub_flags,
        "unresolved": unresolved,
        "dry_run": bool(unresolved),
        "pricing": PRICING,
        "legal": legal,
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
