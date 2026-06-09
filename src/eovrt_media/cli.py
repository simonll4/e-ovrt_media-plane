"""CLI del plano de medios E-OVRT."""

from __future__ import annotations

import json
from pathlib import Path
import typer
from rich.console import Console

app = typer.Typer(
    name="eovrt-media",
    help="E-OVRT-VDP Media Plane — pipeline de inferencia open-vocabulary.",
    add_completion=False,
)
console = Console()


@app.command()
def run(
    config: Path = typer.Option(
        ...,
        "--config",
        "-c",
        help="Ruta al archivo YAML de configuración de corrida.",
        exists=True,
        readable=True,
    ),
) -> None:
    """Ejecutar un pipeline DBE con la configuración indicada."""
    from eovrt_media.config import load_run_config
    from eovrt_media.runtime.pipeline import run_pipeline

    console.print("\n[bold cyan]E-OVRT Media Plane[/bold cyan] v0.1.0")
    console.print(f"[dim]Config:[/dim] {config}\n")

    run_config = load_run_config(config)
    run_pipeline(run_config, console=console)


@app.command(name="validate-config")
def validate_config(
    config: Path = typer.Option(
        ...,
        "--config",
        "-c",
        help="Ruta al archivo YAML de configuración de corrida.",
        exists=True,
        readable=True,
    ),
) -> None:
    """Validar un archivo de configuración sin ejecutarlo."""
    from eovrt_media.config import load_run_config

    try:
        load_run_config(config)
        console.print(f"[green]✓ Configuración válida:[/green] {config}")
    except Exception as e:
        console.print(f"[red]✗ Configuración inválida:[/red] {config}")
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@app.command(name="download-models")
def download_models(
    model: str = typer.Option(
        "all",
        "--model",
        "-m",
        help="Modelo a descargar: grounding_dino, yoloe, o all.",
    ),
) -> None:
    """Descargar los pesos de los modelos OVD soportados."""
    model = model.lower().strip()

    if model in ("grounding_dino", "all"):
        console.print("[cyan]Descargando Grounding DINO tiny desde Hugging Face...[/cyan]")
        try:
            from huggingface_hub import snapshot_download

            snapshot_download(
                repo_id="IDEA-Research/grounding-dino-tiny",
                local_dir="models/grounding-dino/grounding-dino-tiny",
            )
            console.print("[green]✓ Grounding DINO descargado correctamente.[/green]")
        except Exception as e:
            console.print(f"[red]Error descargando Grounding DINO: {e}[/red]")
            if model != "all":
                raise typer.Exit(1)

    if model in ("yoloe", "all"):
        console.print("[cyan]Preparando YOLOE small desde Ultralytics...[/cyan]")
        try:
            from ultralytics import YOLOE

            out_dir = Path("models/yoloe")
            out_dir.mkdir(parents=True, exist_ok=True)

            # Ultralytics descarga automáticamente el checkpoint si no existe localmente.
            _ = YOLOE("yoloe-26s-seg.pt")

            # Si el archivo queda en el CWD, lo movemos a models/yoloe
            src = Path("yoloe-26s-seg.pt")
            dst = out_dir / "yoloe-26s-seg.pt"
            if src.exists() and not dst.exists():
                src.rename(dst)
            elif src.exists() and dst.exists():
                src.unlink()

            console.print("[green]✓ YOLOE preparado correctamente.[/green]")
        except Exception as e:
            console.print(f"[red]Error preparando YOLOE: {e}[/red]")
            raise typer.Exit(1)


@app.command(name="inspect-run")
def inspect_run(
    run_dir: Path = typer.Argument(
        ...,
        help="Directorio de la corrida a inspeccionar.",
        exists=True,
        readable=True,
    ),
) -> None:
    """Inspeccionar los resultados de una corrida anterior."""
    summary_path = run_dir / "summary.json"
    if not summary_path.exists():
        console.print(f"[red]No se encontró summary.json en {run_dir}[/red]")
        raise typer.Exit(1)

    with open(summary_path, encoding="utf-8") as f:
        summary = json.load(f)

    console.print("\n[bold cyan]Run Summary[/bold cyan]")
    console.print(f"  Run ID:           {summary.get('run_id', 'N/A')}")
    console.print(f"  Scenario:         {summary.get('scenario', 'N/A')}")
    console.print(f"  Model Adapter:    {summary.get('model_adapter', 'N/A')}")
    console.print(f"  Source Type:      {summary.get('source_type', 'N/A')}")
    console.print(f"  Units Processed:  {summary.get('units_processed', 'N/A')}")
    console.print(f"  Units Failed:     {summary.get('units_failed', 'N/A')}")
    console.print(f"  Total Detections: {summary.get('total_detections', 'N/A')}")
    console.print(f"  Avg Latency (ms): {summary.get('avg_latency_ms', 'N/A')}")
    console.print(f"  Effective FPS:    {summary.get('fps_effective', 'N/A')}")
    console.print(f"  Started:          {summary.get('started_at', 'N/A')}")
    console.print(f"  Finished:         {summary.get('finished_at', 'N/A')}")
    console.print()


if __name__ == "__main__":
    app()
