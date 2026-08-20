from __future__ import annotations

import json
import logging
from pathlib import Path

import typer
from rich import print_json
from rich.console import Console

from sdlc_copilot.agents.registry import list_agents
from sdlc_copilot.config import get_settings
from sdlc_copilot.ingestion.loaders import load_path
from sdlc_copilot.logging_config import configure_logging
from sdlc_copilot.models import PipelineRequest, SourceDocument
from sdlc_copilot.services.pipeline import SDLCPipelineService
from sdlc_copilot.telemetry import configure_telemetry

app = typer.Typer(help="AI SDLC Copilot CLI")
console = Console(stderr=True)


@app.callback()
def _main(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="DEBUG logs on stderr"),
) -> None:
    """Configure logging before any subcommand runs."""
    settings = get_settings()
    if verbose:
        configure_logging("DEBUG")
    else:
        configure_logging(settings.sdlc_log_level)
    if settings.otel_enabled:
        configure_telemetry()


@app.command()
def agents() -> None:
    """List available SDLC agents."""
    print_json(data=list_agents())


def _read_multiline_until_end() -> str:
    console.print(
        "[dim]Paste requirements, then a line with exactly .END and press Enter. "
        "(Ctrl+Z then Enter on Windows also ends input in some shells.)[/dim]"
    )
    lines: list[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == ".END":
            break
        lines.append(line)
    return "\n".join(lines).strip()


@app.command("interactive")
def interactive() -> None:
    """Prompt for project, requirements (terminal or file), optional agents/team/constraints; run pipeline."""
    log = logging.getLogger(__name__)
    console.print("\n[bold]AI SDLC Copilot[/bold] — interactive run\n")

    project_name = typer.prompt("Project name", default="Untitled SDLC Project")
    mode = typer.prompt("Input source  [1] Type/paste in terminal  [2] File path", default="1")

    raw_text: str | None = None
    documents: list[SourceDocument] | None = None

    if mode.strip() == "2":
        path_str = typer.prompt("Path to requirements file")
        path = Path(path_str.strip().strip('"'))
        if not path.is_file():
            console.print(f"[red]Not a file:[/red] {path}")
            raise typer.Exit(code=1)
        documents = [
            SourceDocument(
                filename=path.name,
                content_type=None,
                text=load_path(path),
                metadata={"source": str(path)},
            )
        ]
        log.info("Loaded file %s (%s chars)", path, len(documents[0].text))
    else:
        raw_text = _read_multiline_until_end()
        if not raw_text:
            console.print("[red]No text entered.[/red]")
            raise typer.Exit(code=1)
        log.info("Typed input: %s chars", len(raw_text))

    agents_csv = typer.prompt(
        "Comma-separated agent ids (leave empty for default full workflow)",
        default="",
    )
    selected_agents = [x.strip() for x in agents_csv.split(",") if x.strip()] or None

    team_raw = typer.prompt("Optional team JSON (array)", default="[]")
    constraints_raw = typer.prompt("Optional constraints JSON (object)", default="{}")
    try:
        team = json.loads(team_raw) if team_raw.strip() else []
        constraints = json.loads(constraints_raw) if constraints_raw.strip() else {}
    except json.JSONDecodeError as exc:
        console.print(f"[red]Invalid JSON:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    if not isinstance(team, list):
        console.print("[red]team must be a JSON array.[/red]")
        raise typer.Exit(code=1)
    if not isinstance(constraints, dict):
        console.print("[red]constraints must be a JSON object.[/red]")
        raise typer.Exit(code=1)

    request = PipelineRequest(
        project_name=project_name,
        raw_text=raw_text,
        selected_agents=selected_agents,
        team=team,
        constraints=constraints,
    )

    console.print("\n[bold]Running pipeline…[/bold] (see stderr for log lines)\n")
    response = SDLCPipelineService().run(request, documents=documents)

    console.print("[bold green]Done.[/bold green] Response JSON:\n")
    print_json(data=response.model_dump(mode="json"))


@app.command()
def run(
    input_path: Path = typer.Argument(..., exists=True, readable=True),
    project_name: str = "Untitled SDLC Project",
    agents_csv: str | None = typer.Option(None, help="Comma-separated agent ids."),
) -> None:
    """Run the SDLC workflow against a local requirement file."""
    selected_agents = [item.strip() for item in agents_csv.split(",")] if agents_csv else None
    document = SourceDocument(
        filename=input_path.name,
        content_type=None,
        text=load_path(input_path),
        metadata={"source": str(input_path)},
    )
    response = SDLCPipelineService().run(
        PipelineRequest(project_name=project_name, selected_agents=selected_agents),
        documents=[document],
    )
    print_json(data=response.model_dump(mode="json"))


if __name__ == "__main__":
    app()
