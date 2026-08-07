"""Stage 0 recon CLI.

Every pipeline stage is a subcommand and a cron entry — no queue, no workers,
no orchestrator (PLAN.md §3). These recon commands become the production
watcher and fetcher rather than being thrown away.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from . import sources
from .capture import capture_area, manifest_path, probe_pdf
from .config import settings
from .govuk import GovUkClient

app = typer.Typer(
    name="haulier",
    help="HGV operator-licence lead alerts from Traffic Commissioner A&D publications.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


def _areas(region: list[str] | None, all_regions: bool) -> list[sources.TrafficArea]:
    if all_regions:
        return list(sources.TRAFFIC_AREAS)
    if region:
        return [sources.resolve(name) for name in region]
    return [sources.LEAD_AREA]


@app.command()
def areas() -> None:
    """List the eight traffic areas and their publication sources."""
    table = Table(title="GB traffic areas — goods vehicle A&D", header_style="bold")
    table.add_column("Slug")
    table.add_column("Name")
    table.add_column("Prefix", justify="center")
    table.add_column("Guidance URL", overflow="fold")
    for area in sources.TRAFFIC_AREAS:
        marker = " [bold green](lead)[/]" if area.slug == sources.LEAD_AREA.slug else ""
        table.add_row(area.slug, area.name + marker, area.licence_prefix, area.guidance_url)
    console.print(table)


@app.command()
def releases(
    region: str = typer.Argument(sources.LEAD_AREA.slug, help="Slug, prefix or name."),
    limit: int = typer.Option(10, help="Show only the most recent N releases."),
) -> None:
    """List releases currently advertised for a traffic area (no download)."""
    area = sources.resolve(region)
    with GovUkClient() as client:
        found = [a for a in client.attachments(area) if a.is_pdf]

    table = Table(title=f"{area.name} — {len(found)} releases live", header_style="bold")
    table.add_column("Release")
    table.add_column("Published")
    table.add_column("Pages", justify="right")
    table.add_column("Accessible", justify="center")
    table.add_column("Title", overflow="fold")
    for item in found[-limit:]:
        flag = "-" if item.accessible is None else ("yes" if item.accessible else "[red]NO[/]")
        table.add_row(
            item.release_no or "[red]?[/]",
            item.published_on.isoformat() if item.published_on else "[red]?[/]",
            str(item.number_of_pages or "-"),
            flag,
            item.title,
        )
    console.print(table)

    unparsed = [a for a in found if not a.parsed]
    if unparsed:
        console.print(
            f"[bold red]{len(unparsed)} title(s) did not parse[/] — "
            "format-change signal, investigate before trusting this source."
        )


@app.command()
def capture(
    region: list[str] = typer.Option(None, "--region", "-r", help="Repeatable."),
    all_regions: bool = typer.Option(False, "--all", help="Capture all eight areas."),
    limit: int = typer.Option(None, help="Most recent N releases per area (default: all)."),
    no_probe: bool = typer.Option(False, "--no-probe", help="Skip the text-layer probe."),
) -> None:
    """Download A&D releases, fingerprint them, and probe for a text layer.

    Defaults to the lead area. GOV.UK keeps only the current year on the live
    pages, so anything not captured before January must be recovered from the
    National Archives instead.
    """
    targets = _areas(region, all_regions)
    grand_total = 0
    with GovUkClient() as client:
        for area in targets:
            console.print(f"[bold]{area.name}[/] ({area.licence_prefix}) …")
            captured = capture_area(area, client, limit=limit, probe=not no_probe)
            grand_total += len(captured)

            no_text = [c for c in captured if c.has_text_layer is False]
            unparsed = [c for c in captured if not c.parsed_title]
            pages = sum(c.page_count or 0 for c in captured)
            size_mb = sum(c.byte_size for c in captured) / 1e6
            console.print(
                f"  {len(captured)} releases, {pages} pages, {size_mb:.1f} MB "
                f"→ {manifest_path(area)}"
            )
            if no_text:
                console.print(
                    f"  [bold red]{len(no_text)} without a text layer[/] "
                    "— OCR fallback required (spec §5.3[2])"
                )
            if unparsed:
                console.print(f"  [bold red]{len(unparsed)} unparsed title(s)[/]")
    console.print(f"[bold green]Captured {grand_total} releases.[/]")


@app.command()
def status() -> None:
    """Summarise what has been captured locally."""
    table = Table(title="Capture status", header_style="bold")
    table.add_column("Region")
    table.add_column("Releases", justify="right")
    table.add_column("Pages", justify="right")
    table.add_column("MB", justify="right")
    table.add_column("No text layer", justify="right")
    table.add_column("Earliest")
    table.add_column("Latest")

    total = 0
    for area in sources.TRAFFIC_AREAS:
        path = manifest_path(area)
        if not path.exists():
            table.add_row(area.slug, "-", "-", "-", "-", "-", "-")
            continue
        rows = json.loads(path.read_text(encoding="utf-8"))
        total += len(rows)
        dates = sorted(r["published_on"] for r in rows if r["published_on"])
        no_text = sum(1 for r in rows if r["has_text_layer"] is False)
        table.add_row(
            area.slug,
            str(len(rows)),
            str(sum(r["page_count"] or 0 for r in rows)),
            f"{sum(r['byte_size'] for r in rows) / 1e6:.1f}",
            f"[red]{no_text}[/]" if no_text else "0",
            dates[0] if dates else "-",
            dates[-1] if dates else "-",
        )
    console.print(table)
    console.print(f"Data dir: {settings().data_dir.resolve()}  •  {total} releases captured")


@app.command()
def probe(path: Path = typer.Argument(..., help="Path to a PDF.")) -> None:
    """Probe a single PDF for page count and text-layer presence."""
    result = probe_pdf(path)
    console.print(
        f"pages={result.page_count}  sample_chars={result.sample_chars}  "
        f"has_text_layer={'yes' if result.has_text_layer else '[bold red]NO[/]'}"
    )


if __name__ == "__main__":
    app()
