"""Command-line interface: `patchpilot analyze | migrate | docs | sandbox | doctor | serve`."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from patchpilot.analyzer.analyzer import analyze as run_analysis
from patchpilot.llm.factory import DEFAULT_MODEL_SPEC, make_provider
from patchpilot.llm.provider import LLMError, load_api_key
from patchpilot.migration.orchestrator import MigrationConfig, Orchestrator
from patchpilot.models import RunStatus
from patchpilot.profiles import get_profile
from patchpilot.reporting.report import STATUS_TEXT, to_json, to_markdown
from patchpilot.retrieval.retriever import Retriever
from patchpilot.validation.runner import (
    DockerValidator,
    build_images,
    docker_available,
    image_exists,
)

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="PatchPilot: test-validated AI code migrations.",
)
sandbox_app = typer.Typer(no_args_is_help=True, help="Manage the Docker sandbox images.")
app.add_typer(sandbox_app, name="sandbox")
console = Console()

Profile = Annotated[str, typer.Option("--profile", "-p", help="Migration profile.")]
SANDBOX_DIR = Path(__file__).resolve().parents[2] / "sandbox"


@app.command()
def analyze(
    repo: Annotated[
        Path, typer.Argument(exists=True, file_okay=False, help="Repository to analyze.")
    ],
    profile: Profile = "pydantic-v2",
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON.")] = False,
) -> None:
    """Find migration-sensitive code (no LLM, no changes)."""
    report = run_analysis(repo, get_profile(profile))
    if as_json:
        typer.echo(report.model_dump_json(indent=2))
        return
    py = [f for f in report.files if not f.is_test]
    console.print(
        f"[bold]{len(py)}[/] source files scanned · [bold]{len(report.files_to_migrate())}[/] need migration · "
        f"models: {', '.join(report.model_classes) or '(none)'}"
    )
    table = Table("Confidence", "Location", "Rule", "Message", show_lines=False)
    for f in report.findings:
        color = {"high": "red", "medium": "yellow", "low": "dim"}[f.confidence.value]
        table.add_row(f"[{color}]{f.confidence.value}[/]", f"{f.file}:{f.line}", f.rule, f.message)
    console.print(table)


@app.command()
def migrate(
    repo: Annotated[
        Path, typer.Argument(exists=True, file_okay=False, help="Repository to migrate.")
    ],
    profile: Profile = "pydantic-v2",
    model: Annotated[str, typer.Option(help="provider:model")] = DEFAULT_MODEL_SPEC,
    max_repairs: Annotated[int, typer.Option(min=0, max=5)] = 2,
    no_retrieval: Annotated[
        bool, typer.Option("--no-retrieval", help="Ablation: no documentation.")
    ] = False,
    apply: Annotated[
        bool,
        typer.Option("--apply", help="Write the result back to REPO, only if validation passed."),
    ] = False,
    report_path: Annotated[
        Path | None, typer.Option("--report", help="Write a Markdown report.")
    ] = None,
    json_path: Annotated[
        Path | None, typer.Option("--json", help="Write the full JSON report.")
    ] = None,
    cache_dir: Annotated[Path | None, typer.Option(help="Cache LLM responses here.")] = None,
    rpm: Annotated[
        float, typer.Option(help="Max LLM requests per minute (free-tier friendly).")
    ] = 8.0,
) -> None:
    """Migrate a repository in an isolated workspace, validate with its tests, and report."""
    prof = get_profile(profile)
    if not image_exists(prof.target_image):
        console.print(
            f"[red]Sandbox image {prof.target_image} not found.[/] Run: patchpilot sandbox build"
        )
        raise typer.Exit(2)
    try:
        provider = make_provider(model, cache_dir, rpm)
    except LLMError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(2) from exc
    orch = Orchestrator(
        prof,
        provider,
        DockerValidator(prof.target_image, prof.pytest_args),
        MigrationConfig(
            retrieval=not no_retrieval, max_repairs=max_repairs, apply_to_original=apply
        ),
        on_step=lambda state, detail: console.print(f"[cyan]{state:<10}[/] {detail}"),
    )
    report = orch.run(repo)
    md = to_markdown(report)
    if report_path:
        report_path.write_text(md, encoding="utf-8")
    if json_path:
        json_path.write_text(to_json(report), encoding="utf-8")
    console.print()
    console.print(f"[bold]{STATUS_TEXT[report.status]}[/] {report.message}")
    console.print(f"Changed files: {', '.join(report.changed_files) or '(none)'}")
    if report.applied_to_original:
        console.print("[green]Applied to the original repository.[/]")
    elif apply:
        console.print("[yellow]Not applied: validation did not pass.[/]")
    if not report_path:
        console.print(md)
    ok = report.status in (RunStatus.SUCCESS, RunStatus.NOTHING_TO_DO, RunStatus.UNVERIFIED)
    raise typer.Exit(0 if ok else 1)


@app.command()
def docs(
    query: Annotated[str, typer.Argument(help="Search the migration guide (BM25).")],
    profile: Profile = "pydantic-v2",
    k: int = 3,
) -> None:
    """Search the profile's migration documentation."""
    retriever = Retriever.from_directory(get_profile(profile).guides_dir)
    for hit in retriever.search(query, k):
        console.print(f"[bold]{hit.chunk.heading}[/] [dim]({hit.score}, {hit.chunk.id})[/]")
        console.print(hit.chunk.text[:600] + ("…" if len(hit.chunk.text) > 600 else ""))
        console.print()


@sandbox_app.command("build")
def sandbox_build() -> None:
    """Build the sandbox images (source and target library versions)."""
    for tag in build_images(SANDBOX_DIR):
        console.print(f"built {tag}")


@app.command()
def doctor(profile: Profile = "pydantic-v2") -> None:
    """Check Docker, sandbox images, and the API key (the key itself is never printed)."""
    prof = get_profile(profile)
    checks = {
        "docker daemon": docker_available(),
        f"image {prof.target_image}": image_exists(prof.target_image),
        f"image {prof.source_image}": image_exists(prof.source_image),
        "GEMINI_API_KEY set": load_api_key() is not None,
    }
    for name, ok in checks.items():
        console.print(f"{'[green]ok[/]  ' if ok else '[red]missing[/]'} {name}")
    raise typer.Exit(0 if all(checks.values()) else 1)


@app.command()
def serve(
    host: str = "127.0.0.1",
    port: int = 8765,
) -> None:
    """Run the HTTP API (local only by default)."""
    import uvicorn

    uvicorn.run("patchpilot.api.app:app", host=host, port=port)
