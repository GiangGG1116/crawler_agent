"""CLI — Command-line interface for Agent Crawler Data.

Provides commands to run crawl jobs via the API Gateway.
v2.0: Supports async job submission with live progress polling.
"""

from __future__ import annotations

import asyncio
import json
import sys

import click
import httpx
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

console = Console()

DEFAULT_GATEWAY_URL = "http://localhost:8000"


def _get_gateway_url() -> str:
    import os

    return os.environ.get("GATEWAY_URL", DEFAULT_GATEWAY_URL)


@click.group()
@click.version_option(version="1.0.0")
def main():
    """🕷️ Agent Crawler — Intelligent Web Data Crawling CLI"""
    pass


@main.command()
@click.argument("url")
@click.option("--data-type", "-d", default="articles", help="Type of data to extract")
@click.option("--fields", "-f", multiple=True, help="Required fields (repeatable)")
@click.option("--max-pages", "-p", default=10, help="Maximum pages to crawl")
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--api-key", "-k", envvar="CRAWLER_API_KEY", default=None, help="API key")
@click.option(
    "--wait/--no-wait", default=True, help="Wait for completion with progress bar"
)
def crawl(
    url: str,
    data_type: str,
    fields: tuple,
    max_pages: int,
    output_format: str,
    api_key: str | None,
    wait: bool,
):
    """Submit a crawl job for a URL."""
    asyncio.run(
        _run_crawl(
            url, data_type, list(fields), max_pages, output_format, api_key, wait
        )
    )


async def _run_crawl(
    url: str,
    data_type: str,
    fields: list[str],
    max_pages: int,
    output_format: str,
    api_key: str | None,
    wait: bool,
):
    gateway = _get_gateway_url()
    headers = {}
    if api_key:
        headers["X-API-Key"] = api_key

    payload = {
        "target": {"url": url},
        "data_spec": {"data_type": data_type, "required_fields": fields},
        "scope": {"max_pages": max_pages},
        "output": {"format": output_format},
    }

    async with httpx.AsyncClient(timeout=30) as client:
        # Submit job
        console.print(f"\n[bold cyan]🕷️  Submitting crawl job for:[/] {url}")
        try:
            resp = await client.post(
                f"{gateway}/api/v1/crawl", json=payload, headers=headers
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            console.print(
                f"[red]Error:[/] {e.response.status_code} — {e.response.text}"
            )
            sys.exit(1)
        except httpx.ConnectError:
            console.print(f"[red]Error:[/] Cannot connect to gateway at {gateway}")
            sys.exit(1)

        data = resp.json()
        job_id = data["job_id"]
        console.print(f"[green]✓ Job submitted:[/] {job_id}\n")

        if not wait:
            console.print(f"Use [bold]crawler status {job_id}[/] to check progress.")
            return

        # Poll for completion with progress bar
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Crawling...", total=100)

            while True:
                await asyncio.sleep(2)
                try:
                    status_resp = await client.get(
                        f"{gateway}/api/v1/crawl/{job_id}/status"
                    )
                    status_data = status_resp.json()
                except Exception:
                    continue

                job_status = status_data.get("status", "unknown")
                phase = status_data.get("phase", "")
                pct = float(status_data.get("progress", 0)) * 100

                progress.update(task, completed=pct, description=f"[cyan]{phase}[/]")

                if job_status in ("completed", "failed"):
                    progress.update(task, completed=100)
                    break

        # Show result
        if job_status == "completed":
            result_resp = await client.get(f"{gateway}/api/v1/crawl/{job_id}/result")
            result = result_resp.json()
            _print_result(result)
        else:
            console.print(
                f"\n[red]❌ Job failed:[/] {status_data.get('error', 'Unknown error')}"
            )


@main.command()
@click.argument("job_id")
def status(job_id: str):
    """Check the status of a crawl job."""
    asyncio.run(_check_status(job_id))


async def _check_status(job_id: str):
    gateway = _get_gateway_url()
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{gateway}/api/v1/crawl/{job_id}/status")
        if resp.status_code == 404:
            console.print(f"[red]Job {job_id} not found[/]")
            return
        data = resp.json()
        console.print_json(json.dumps(data, indent=2))


@main.command()
@click.argument("job_id")
def result(job_id: str):
    """Get the result of a completed crawl job."""
    asyncio.run(_get_result(job_id))


async def _get_result(job_id: str):
    gateway = _get_gateway_url()
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{gateway}/api/v1/crawl/{job_id}/result")
        if resp.status_code == 404:
            console.print(f"[red]Job {job_id} not found[/]")
            return
        data = resp.json()
        _print_result(data)


def _print_result(result: dict):
    """Pretty-print a crawl result."""
    status = result.get("status", "unknown")
    color = (
        "green" if status == "success" else "yellow" if status == "partial" else "red"
    )

    table = Table(title="Crawl Result", show_header=False)
    table.add_column("Key", style="bold")
    table.add_column("Value")

    table.add_row("Status", f"[{color}]{status}[/]")
    table.add_row("Phase", result.get("phase_used", "N/A"))
    table.add_row("Raw Records", str(len(result.get("raw_records", []))))
    table.add_row("Clean Records", str(len(result.get("clean_records", []))))
    table.add_row("Duration", f"{result.get('duration_seconds', 0):.1f}s")

    quality = result.get("quality")
    if quality:
        table.add_row("Quality Score", f"{quality.get('overall_score', 0):.1f}%")
        table.add_row("Quality Grade", quality.get("grade", "N/A"))

    if result.get("output_path"):
        table.add_row("Output Path", result["output_path"])

    if result.get("errors"):
        table.add_row("Errors", "\n".join(result["errors"]))

    console.print(table)


if __name__ == "__main__":
    main()
