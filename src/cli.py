"""CLI — Command-line interface for Agent Crawler Data.

Provides commands to run crawl jobs, list templates, and check status.
"""

from __future__ import annotations

import asyncio
import json
import sys

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import print as rprint

from src.models.request import (
    CrawlRequest,
    ConstraintsConfig,
    DataSpec,
    DataType,
    OutputConfig,
    OutputFormat,
    OutputDestination,
    ScopeConfig,
    CrawlMode,
    TargetInfo,
)

console = Console()


@click.group()
@click.version_option(version="1.0.0", prog_name="Agent Crawler Data")
def cli():
    """🕷️  Agent Crawler Data — Intelligent web data crawling platform."""
    pass


@cli.command()
@click.argument("url")
@click.option("--data-type", "-t", type=click.Choice([e.value for e in DataType]), default="custom")
@click.option("--fields", "-f", multiple=True, help="Required fields (repeat for multiple)")
@click.option("--format", "-o", "output_format", type=click.Choice([e.value for e in OutputFormat]), default="json")
@click.option("--max-pages", "-p", default=10, type=int)
@click.option("--max-records", "-r", default=1000, type=int)
@click.option("--mode", "-m", type=click.Choice([e.value for e in CrawlMode]), default="full")
@click.option("--destination", "-d", type=click.Choice([e.value for e in OutputDestination]), default="local_file")
@click.option("--rate-limit", default=2.0, type=float, help="Requests per second")
@click.option("--proxy/--no-proxy", default=False, help="Enable proxy rotation")
def crawl(url, data_type, fields, output_format, max_pages, max_records, mode, destination, rate_limit, proxy):
    """🚀 Start a crawl job for the given URL."""
    request = CrawlRequest(
        target=TargetInfo(url=url),
        data_spec=DataSpec(data_type=DataType(data_type), required_fields=list(fields)),
        scope=ScopeConfig(mode=CrawlMode(mode), max_pages=max_pages, max_records=max_records),
        output=OutputConfig(format=OutputFormat(output_format), destination=OutputDestination(destination)),
        constraints=ConstraintsConfig(rate_limit_rps=rate_limit, proxy_required=proxy),
    )

    console.print(Panel(
        f"[bold cyan]Target:[/] {url}\n"
        f"[bold cyan]Data Type:[/] {data_type}\n"
        f"[bold cyan]Fields:[/] {', '.join(fields) or 'auto-detect'}\n"
        f"[bold cyan]Format:[/] {output_format}\n"
        f"[bold cyan]Max Pages:[/] {max_pages}",
        title="🕷️  Crawl Job",
        border_style="cyan",
    ))

    # Run async crawl
    from src.orchestrator import CrawlOrchestrator
    orchestrator = CrawlOrchestrator()
    result = asyncio.run(orchestrator.crawl(request))

    # Display results
    _display_result(result)


@cli.command()
def templates():
    """📋 List all available scraper templates."""
    from src.templates.registry import TemplateRegistry
    from src.utils.config import get_settings

    registry = TemplateRegistry()
    registry.auto_register(get_settings().templates_config_dir)

    table = Table(title="📋 Registered Templates", border_style="cyan")
    table.add_column("ID", style="bold")
    table.add_column("Name")
    table.add_column("Web Type", style="green")
    table.add_column("Tools")
    table.add_column("Config", justify="center")

    for t in registry.list_all():
        table.add_row(
            t["template_id"],
            t["template_name"],
            t["web_type"],
            ", ".join(t["tool_stack"]),
            "✅" if t["has_config"] else "❌",
        )

    console.print(table)


@cli.command()
@click.argument("json_file", type=click.Path(exists=True))
def crawl_from_file(json_file):
    """📂 Run crawl from a JSON request file."""
    with open(json_file) as f:
        data = json.load(f)

    request = CrawlRequest(**data)

    from src.orchestrator import CrawlOrchestrator
    orchestrator = CrawlOrchestrator()
    result = asyncio.run(orchestrator.crawl(request))
    _display_result(result)


def _display_result(result):
    """Display crawl result in a formatted table."""
    status_colors = {"success": "green", "partial": "yellow", "failed": "red", "running": "blue"}
    color = status_colors.get(result.status.value, "white")

    console.print(f"\n[bold {color}]Status: {result.status.value.upper()}[/]")

    table = Table(border_style="dim")
    table.add_column("Metric", style="bold")
    table.add_column("Value")

    table.add_row("Phase Used", result.phase_used.value if result.phase_used else "N/A")
    table.add_row("Template", result.template_id or "N/A")
    table.add_row("Attempts", str(result.attempts))
    table.add_row("Raw Records", str(len(result.raw_records)))
    table.add_row("Clean Records", str(len(result.clean_records)))
    table.add_row("Rejected", str(len(result.rejected_records)))
    if result.quality:
        table.add_row("Quality Score", f"{result.quality.overall_score:.1f}% ({result.quality.grade.value})")
    table.add_row("Duration", f"{result.duration_seconds:.1f}s")
    table.add_row("Output", result.output_path or "N/A")

    console.print(table)

    if result.errors:
        console.print(f"\n[red]Errors: {'; '.join(result.errors)}[/]")


if __name__ == "__main__":
    cli()
