"""Stage 0 recon CLI.

Every pipeline stage is a subcommand and a cron entry — no queue, no workers,
no orchestrator (PLAN.md §3). These recon commands become the production
watcher and fetcher rather than being thrown away.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from . import recon, sources, textdump
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
        pdfs = [a for a in client.attachments(area) if a.is_pdf]
    found = [a for a in pdfs if a.is_goods]
    stray = [a for a in pdfs if not a.is_goods]
    if stray:
        console.print(
            f"[bold yellow]{len(stray)} PSV (NP) document(s) on this goods page, "
            "excluded:[/] " + ", ".join(a.title for a in stray)
        )

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
    refresh: bool = typer.Option(
        False, "--refresh", help="Re-download everything and compare digests."
    ),
) -> None:
    """Download A&D releases, fingerprint them, and probe for a text layer.

    Defaults to the lead area. GOV.UK keeps only the current year on the live
    pages, so anything not captured before January must be recovered from the
    National Archives instead.
    """
    targets = _areas(region, all_regions)
    grand_total = 0
    alarms = 0
    with GovUkClient() as client:
        for area in targets:
            console.print(f"[bold]{area.name}[/] ({area.licence_prefix}) …")
            result = capture_area(area, client, limit=limit, probe=not no_probe, refresh=refresh)
            captured = result.releases
            grand_total += len(captured)

            no_text = [c for c in captured if c.has_text_layer is False]
            unparsed = [c for c in captured if not c.parsed_title]
            probe_failed = [c for c in captured if c.probe_error]
            aged_off = [c for c in captured if not c.live]
            pages = sum(c.page_count or 0 for c in captured)
            size_mb = sum(c.byte_size for c in captured) / 1e6
            console.print(
                f"  {len(captured)} releases, {pages} pages, {size_mb:.1f} MB "
                f"→ {manifest_path(area)}"
            )
            if aged_off:
                console.print(
                    f"  {len(aged_off)} release(s) no longer on the live page — kept "
                    "(GOV.UK archives the previous year each January)"
                )
            if result.reissued:
                # Alarm on what is new this run; the manifest keeps the record.
                alarms += len(result.reissued)
                console.print(
                    f"  [bold yellow]{len(result.reissued)} release(s) re-issued at source[/] "
                    "— corrections may be owed (spec §7): "
                    + ", ".join(c.release_no or "?" for c in result.reissued)
                )
            if no_text:
                alarms += len(no_text)
                console.print(
                    f"  [bold red]{len(no_text)} without a text layer[/] "
                    "— OCR fallback required (spec §5.3[2])"
                )
            if probe_failed:
                alarms += len(probe_failed)
                console.print(f"  [bold red]{len(probe_failed)} unreadable PDF(s)[/]")
                for row in probe_failed:
                    console.print(f"    {row.release_no or '?'}: {row.probe_error}")
            if unparsed:
                alarms += len(unparsed)
                console.print(f"  [bold red]{len(unparsed)} unparsed title(s)[/]")
            if result.failures:
                alarms += len(result.failures)
                console.print(f"  [bold red]{len(result.failures)} fetch failure(s)[/]")
                for title, error in result.failures:
                    console.print(f"    {title}: {error}")
    console.print(f"[bold green]Captured {grand_total} releases.[/]")
    if alarms:
        raise typer.Exit(code=1)


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


def _ensure_dumps(areas: list[sources.TrafficArea], workers: int | None) -> None:
    """Build any missing/stale text dumps before an analysis command runs."""
    jobs = [job for area in areas for job in textdump.stale_jobs(area)]
    if not jobs:
        return
    console.print(f"Extracting text from {len(jobs)} release(s) …")
    for done, (pdf_path, _pages, error) in enumerate(
        textdump.build_dumps(jobs, workers=workers), start=1
    ):
        if error:
            console.print(f"  [bold red]FAILED[/] {pdf_path}: {error}")
        elif done % 25 == 0 or done == len(jobs):
            console.print(f"  {done}/{len(jobs)}")


def _write_recon(name: str, payload: dict[str, Any]) -> Path:
    path = settings().data_dir / "recon" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


@app.command()
def dump(
    region: list[str] = typer.Option(None, "--region", "-r", help="Repeatable."),
    all_regions: bool = typer.Option(False, "--all", help="All eight areas."),
    workers: int = typer.Option(None, "-w", "--workers", help="Parallel extraction workers."),
) -> None:
    """Extract and cache per-page text for captured releases (idempotent)."""
    _ensure_dumps(_areas(region, all_regions), workers)
    console.print("[bold green]Text dumps up to date.[/]")


@app.command()
def headings(
    region: list[str] = typer.Option(None, "--region", "-r", help="Repeatable."),
    all_regions: bool = typer.Option(False, "--all", help="All eight areas."),
    top: int = typer.Option(15, help="Rows to show per region."),
    workers: int = typer.Option(None, "-w", "--workers"),
) -> None:
    """Heading frequency table per region — seeds section_heading_map (Stage 0.3)."""
    targets = _areas(region, all_regions)
    _ensure_dumps(targets, workers)

    combined: dict[str, dict[str, Any]] = {}
    for area in targets:
        stats = recon.analyse_headings(list(textdump.iter_dumps(area)))
        combined[area.slug] = recon.headings_payload(stats)

        table = Table(
            title=f"{area.name} — S-markers across {stats.releases} releases",
            header_style="bold",
        )
        table.add_column("Marker")
        table.add_column("Occurrences", justify="right")
        table.add_column("Releases", justify="right")
        for marker in sorted(stats.markers, key=lambda m: (len(m), m)):
            table.add_row(
                marker, str(stats.markers[marker]), str(len(stats.marker_releases[marker]))
            )
        console.print(table)

        heads = Table(title=f"{area.name} — top headings", header_style="bold")
        heads.add_column("Releases", justify="right")
        heads.add_column("Occurrences", justify="right")
        heads.add_column("Heading", overflow="fold")
        shown = 0
        for text, count in stats.headings.most_common():
            n_releases = len(stats.heading_releases[text])
            if n_releases < 2:
                continue
            heads.add_row(str(n_releases), str(count), text)
            shown += 1
            if shown >= top:
                break
        console.print(heads)

    path = _write_recon("headings", combined)
    console.print(f"Full table → [bold]{path}[/]")


@app.command()
def licences(
    region: list[str] = typer.Option(None, "--region", "-r", help="Repeatable."),
    all_regions: bool = typer.Option(False, "--all", help="All eight areas."),
    workers: int = typer.Option(None, "-w", "--workers"),
) -> None:
    """Licence-number harvest — validates the regex and prefix map (Stage 0.4)."""
    targets = _areas(region, all_regions)
    _ensure_dumps(targets, workers)

    table = Table(title="Licence-number harvest", header_style="bold")
    table.add_column("Region")
    table.add_column("Releases", justify="right")
    table.add_column("Distinct", justify="right")
    table.add_column("Mean/release", justify="right")
    table.add_column("Home prefix %", justify="right")
    table.add_column("Foreign", justify="right")

    combined: dict[str, dict[str, Any]] = {}
    all_near_misses: dict[str, dict[str, Any]] = {}
    for area in targets:
        stats = recon.analyse_licences(list(textdump.iter_dumps(area)))
        payload = recon.licences_payload(stats, area)
        combined[area.slug] = payload

        share = payload["home_prefix_share"]
        table.add_row(
            area.slug,
            str(payload["releases"]),
            str(payload["distinct_total"]),
            str(payload["mean_distinct_per_release"]),
            f"{share * 100:.2f}" if share is not None else "-",
            str(len(payload["foreign"])),
        )
        for row in payload["near_miss_shapes"]:
            entry = all_near_misses.setdefault(
                row["shape"], {"occurrences": 0, "example": row["example"]}
            )
            entry["occurrences"] += row["occurrences"]
    console.print(table)

    if all_near_misses:
        near = Table(
            title="Near-miss shapes (caught by loose sweep, rejected by the spec regex)",
            header_style="bold",
        )
        near.add_column("Shape")
        near.add_column("Occurrences", justify="right")
        near.add_column("Example")
        ranked = sorted(all_near_misses.items(), key=lambda kv: -kv[1]["occurrences"])
        for shape, entry in ranked[:15]:
            near.add_row(shape, str(entry["occurrences"]), entry["example"])
        console.print(near)

    path = _write_recon("licences", combined)
    console.print(f"Full harvest → [bold]{path}[/]")


@app.command()
def render_digest(
    records: Path = typer.Option(Path("data/pilot/records.json"), help="Extracted records JSON."),
    out_dir: Path = typer.Option(Path("data/pilot"), help="Where to write digest.html/.csv."),
    redact: bool = typer.Option(
        False, help="Redact people to initials — required for the public sample (PLAN §2.11)."
    ),
) -> None:
    """Render a digest HTML + CSV from extracted records (the Stage 0 pilot)."""
    from .digest.leads import build_lead
    from .digest.render import render_csv, render_html, subject_line

    release = json.loads(records.read_text(encoding="utf-8"))
    leads = [build_lead(r, release) for r in release["records"]]

    suffix = "_redacted" if redact else ""
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / f"digest_{release['release_no']}{suffix}.html"
    csv_path = out_dir / f"digest_{release['release_no']}{suffix}.csv"
    html_path.write_text(render_html(release, leads, redact=redact), encoding="utf-8")
    csv_path.write_text(render_csv(release, leads, redact=redact), encoding="utf-8")

    console.print(f"Subject: [bold]{subject_line(release, leads)}[/]")
    console.print(f"{len(leads)} leads → {html_path} + {csv_path}")


@app.command()
def build_site(
    out_dir: Path = typer.Option(Path("site/dist"), help="Where to write the built site."),
    sample: Path = typer.Option(None, help="Sample digest HTML (default: the redacted pilot)."),
    serve: bool = typer.Option(False, "--serve", help="Serve the build locally and block."),
    port: int = typer.Option(8000, help="Port for --serve."),
) -> None:
    """Build the static landing site (spec §4.8) — plain HTML, no framework.

    Every service that would cost money or need an account is a placeholder.
    While any are unresolved the build is a dry run: it carries a banner naming
    what is missing, marks each stub link, and sets noindex.
    """
    from .site.build import build_site as run_build

    result = run_build(out_dir, sample=sample)
    console.print(f"{len(result.pages)} pages → [bold]{result.out_dir}[/]")
    if result.sample_source:
        console.print(f"  sample issue ← {result.sample_source}")
    else:
        console.print(
            "  [yellow]no sample digest found[/] — run "
            "[bold]haulier render-digest --redact[/] first"
        )
    if result.unresolved:
        console.print(f"[bold yellow]Dry run — {len(result.unresolved)} placeholder(s):[/]")
        for item in result.unresolved:
            console.print(f"  {item.env}  — {item.note}")
    else:
        console.print("[bold green]All placeholders resolved — this build is live-ready.[/]")

    if serve:
        import functools
        import http.server
        import socketserver

        handler = functools.partial(
            http.server.SimpleHTTPRequestHandler, directory=str(result.out_dir)
        )
        with socketserver.TCPServer(("127.0.0.1", port), handler) as httpd:
            console.print(f"\nServing on [bold]http://127.0.0.1:{port}/[/] — ctrl-c to stop")
            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                console.print("\nstopped")


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
