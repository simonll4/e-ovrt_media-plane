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


@app.command(name="run-producer")
def run_producer(
    config: Path = typer.Option(
        ..., "--config", "-c", help="Config YAML (topology=two_node).", exists=True, readable=True
    ),
) -> None:
    """Nodo A: ingesta + normalización + servidor de red ZeroMQ."""
    from eovrt_media.config import load_run_config
    from eovrt_media.runtime.two_node import run_node_a

    console.print("\n[bold cyan]E-OVRT Media Plane — Nodo A (producer)[/bold cyan]")
    run_node_a(load_run_config(config), console=console)


@app.command(name="run-consumer")
def run_consumer(
    config: Path = typer.Option(
        ..., "--config", "-c", help="Config YAML (topology=two_node).", exists=True, readable=True
    ),
) -> None:
    """Nodo B: cliente de red ZeroMQ + inferencia + artefactos."""
    from eovrt_media.config import load_run_config
    from eovrt_media.runtime.two_node import run_node_b

    console.print("\n[bold cyan]E-OVRT Media Plane — Nodo B (consumer)[/bold cyan]")
    run_id = run_node_b(load_run_config(config), console=console)
    console.print(f"[green]✓ Corrida completada:[/green] {run_id}")


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
        run_config = load_run_config(config)
        console.print(f"[green]✓ Configuración válida:[/green] {config}")
        weights_path = run_config.model.weights or run_config.model.local_dir
        if weights_path and not Path(weights_path).exists():
            console.print(
                f"[yellow]⚠ Pesos no encontrados en {weights_path} — "
                f"ejecutar make download-models antes de correr.[/yellow]"
            )
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
    """Descargar los pesos originales de la matriz experimental.

    Misma cobertura que scripts/download_models.sh: deja los pesos bajo
    models/<familia>/original/ según el catálogo configs/models/.
    """
    model = model.lower().strip()

    if model in ("grounding_dino", "all"):
        try:
            from huggingface_hub import snapshot_download

            for variant in ("grounding-dino-tiny", "grounding-dino-base"):
                console.print(f"[cyan]Descargando {variant} desde Hugging Face...[/cyan]")
                snapshot_download(
                    repo_id=f"IDEA-Research/{variant}",
                    local_dir=f"models/grounding-dino/original/{variant}",
                )
            for variant in (
                "mm_grounding_dino_tiny_o365v1_goldg_v3det",
                "mm_grounding_dino_base_all",
                "mm_grounding_dino_large_all",
            ):
                console.print(f"[cyan]Descargando {variant} desde Hugging Face...[/cyan]")
                snapshot_download(
                    repo_id=f"openmmlab-community/{variant}",
                    local_dir=f"models/mm-grounding-dino/original/{variant}",
                )
            console.print("[green]✓ Grounding DINO descargado correctamente.[/green]")
        except Exception as e:
            console.print(f"[red]Error descargando Grounding DINO: {e}[/red]")
            if model != "all":
                raise typer.Exit(1)

    if model in ("yoloe", "all"):
        console.print("[cyan]Preparando YOLOE-26 (s/m/l/x) desde Ultralytics...[/cyan]")
        try:
            from ultralytics.utils.downloads import attempt_download_asset

            out_dir = Path("models/yoloe/original")
            out_dir.mkdir(parents=True, exist_ok=True)

            for name in (
                "yoloe-26s-seg.pt",
                "yoloe-26m-seg.pt",
                "yoloe-26l-seg.pt",
                "yoloe-26x-seg.pt",
            ):
                dst = out_dir / name
                if dst.exists():
                    console.print(f"[dim]ya existe: {dst}[/dim]")
                    continue
                downloaded = Path(attempt_download_asset(name))
                downloaded.rename(dst)
                console.print(f"descargado: {dst}")

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
    console.print(f"  Device:           {summary.get('device', 'N/A')}")
    console.print(f"  Prompt Set:       {summary.get('prompt_set_id', 'N/A')}")
    console.print(f"  Source Type:      {summary.get('source_type', 'N/A')}")
    console.print(f"  Units Processed:  {summary.get('units_processed', 'N/A')}")
    console.print(f"  Units Failed:     {summary.get('units_failed', 'N/A')}")
    console.print(f"  Total Detections: {summary.get('total_detections', 'N/A')}")
    by_label = summary.get("detections_by_label") or {}
    if by_label:
        labels_str = ", ".join(f"{label}: {count}" for label, count in by_label.items())
        console.print(f"  By Label:         {labels_str}")
    console.print(f"  Avg Latency (ms): {summary.get('avg_latency_ms', 'N/A')}")
    console.print(f"  P95 Latency (ms): {summary.get('p95_latency_ms', 'N/A')}")
    console.print(f"  P99 Latency (ms): {summary.get('p99_latency_ms', 'N/A')}")
    console.print(f"  Units Dropped:    {summary.get('units_dropped', 0)}")
    console.print(f"  Effective FPS:    {summary.get('fps_effective', 'N/A')}")
    gpu_peak = summary.get("gpu_memory_peak_mb", 0.0)
    if gpu_peak:
        console.print(f"  GPU Peak (MB):    {gpu_peak}")
    console.print(f"  Started:          {summary.get('started_at', 'N/A')}")
    console.print(f"  Finished:         {summary.get('finished_at', 'N/A')}")

    descriptor = summary.get("run_descriptor")
    if descriptor:
        console.print("\n[bold]Deployment Descriptor[/bold]")
        console.print(f"  Topology:         {descriptor.get('topology', 'N/A')}")
        console.print(f"  Transport:        {descriptor.get('transport', 'N/A')}")
        console.print(f"  Rate Control:     {descriptor.get('rate_control', 'N/A')}")
        console.print(f"  Source Kind:      {descriptor.get('source_kind', 'N/A')}")
        console.print(f"  Code Version:     {descriptor.get('code_version', 'N/A')}")

    provenance_path = run_dir / "run_provenance.json"
    if provenance_path.exists():
        with open(provenance_path, encoding="utf-8") as file:
            provenance = json.load(file)
        fingerprint = provenance.get("source_fingerprint") or "—"
        console.print("\n[bold]Provenance[/bold]")
        console.print(f"  Dataset:          {provenance.get('dataset_id', 'N/A')}")
        console.print(f"  View / split:     {provenance.get('view', 'N/A')} / {provenance.get('split', 'N/A')}")
        console.print(f"  Fingerprint:      {fingerprint[:16]}..." if fingerprint != "—" else "  Fingerprint:      —")
    console.print()


def _collect_summaries(paths: list[Path]) -> list[dict]:
    """Resuelve directorios de corrida (o un directorio raíz) a sus summary.json."""
    summaries = []
    for path in paths:
        if (path / "summary.json").exists():
            run_dirs = [path]
        elif path.is_dir():
            run_dirs = sorted(p for p in path.iterdir() if (p / "summary.json").exists())
        else:
            run_dirs = []

        for run_dir in run_dirs:
            with open(run_dir / "summary.json", encoding="utf-8") as f:
                summaries.append(json.load(f))

    summaries.sort(key=lambda s: s.get("started_at", ""))
    return summaries


@app.command(name="compare-runs")
def compare_runs(
    run_dirs: list[Path] = typer.Argument(
        ...,
        help="Directorios de corridas, o un directorio raíz que las contenga (ej. runs/).",
        exists=True,
        readable=True,
    ),
) -> None:
    """Comparar métricas de varias corridas en una tabla."""
    from rich.table import Table

    summaries = _collect_summaries(run_dirs)
    if not summaries:
        console.print("[red]No se encontró ningún summary.json en los directorios indicados.[/red]")
        raise typer.Exit(1)

    table = Table(title="Comparación de corridas")
    table.add_column("Run ID", overflow="fold")
    table.add_column("Modelo")
    table.add_column("Device")
    table.add_column("Prompts")
    table.add_column("Unidades", justify="right")
    table.add_column("Fallos", justify="right")
    table.add_column("Detecciones", justify="right")
    table.add_column("Avg ms", justify="right")
    table.add_column("P95 ms", justify="right")
    table.add_column("FPS", justify="right")
    table.add_column("VRAM pico MB", justify="right")

    for s in summaries:
        table.add_row(
            str(s.get("run_id", "?")),
            str(s.get("model_adapter") or s.get("model_name") or "?"),
            str(s.get("device", "?")),
            str(s.get("prompt_set_id") or s.get("prompt_version") or "?"),
            str(s.get("units_processed", "?")),
            str(s.get("units_failed", "?")),
            str(s.get("total_detections", "?")),
            str(s.get("avg_latency_ms", "?")),
            str(s.get("p95_latency_ms", "?")),
            str(s.get("fps_effective", "?")),
            str(s.get("gpu_memory_peak_mb", 0.0) or "—"),
        )

    console.print()
    console.print(table)

    # Tabla de detecciones por label (solo si alguna corrida tiene el desglose)
    all_labels: list[str] = []
    for s in summaries:
        for label in (s.get("detections_by_label") or {}):
            if label not in all_labels:
                all_labels.append(label)

    if all_labels:
        label_table = Table(title="Detecciones por label")
        label_table.add_column("Label")
        for s in summaries:
            label_table.add_column(str(s.get("run_id", "?")), justify="right", overflow="fold")
        for label in all_labels:
            row = [label]
            for s in summaries:
                row.append(str((s.get("detections_by_label") or {}).get(label, 0)))
            label_table.add_row(*row)
        console.print()
        console.print(label_table)

    console.print()


@app.command(name="evaluate")
def evaluate(
    run: Path = typer.Option(
        ...,
        "--run",
        help="Directorio de la corrida a evaluar (debe contener detections.jsonl).",
        exists=True,
        readable=True,
    ),
    bench_coco: Path | None = typer.Option(
        None,
        "--bench-coco",
        help="COCO JSON del BENCH. Por defecto: auto-discover desde ../e-ovrt_datasets/.",
    ),
    person_gt: Path | None = typer.Option(
        None,
        "--person-gt",
        help="GT persona-nivel (person_gt.json). Por defecto: auto-discover.",
    ),
    iou_threshold: float = typer.Option(
        0.5,
        "--iou-threshold",
        help="Umbral IoU para matching detección/GT (default: 0.5).",
    ),
) -> None:
    """Evaluar la percepción de una corrida contra el BENCH."""
    from rich.table import Table

    from eovrt_media.evaluation.runner import run_evaluation

    console.print("\n[bold cyan]Evaluación de percepción[/bold cyan]")
    console.print(f"[dim]Corrida:[/dim] {run}")
    try:
        result = run_evaluation(
            run_dir=run,
            bench_coco=bench_coco,
            person_gt=person_gt,
            iou_threshold=iou_threshold,
        )
    except FileNotFoundError as error:
        console.print(f"[red]✗ No se pudo evaluar la corrida:[/red] {error}")
        console.print(
            "[red]Verifique detections.jsonl y las rutas de --bench-coco y --person-gt.[/red]"
        )
        raise typer.Exit(1)

    table = Table(title=f"Percepción — {result.run_id}")
    table.add_column("Clase", style="cyan")
    table.add_column("AP@0.5", justify="right")
    table.add_column("n_gt", justify="right")
    table.add_column("n_det", justify="right")
    for item in result.per_class:
        ap50 = f"{item.AP50:.3f}" if item.AP50 is not None else "—"
        table.add_row(item.class_name, ap50, str(item.n_gt), str(item.n_det))

    console.print()
    console.print(table)
    if result.cr01_detection_recall is None:
        console.print("CR-01 recall: no hay violadores en el GT.")
    else:
        console.print(f"CR-01 recall: {result.cr01_detection_recall:.3f}")
    console.print(f"[green]✓ Resultados guardados:[/green] {run / 'eval_perception.json'}")


if __name__ == "__main__":
    app()
