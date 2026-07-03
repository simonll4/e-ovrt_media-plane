"""Inspeccionar o comparar corridas anteriores.

Uso:
    python -m eovrt_media.tools.inspect_runs inspect runs/<run_id>
    python -m eovrt_media.tools.inspect_runs compare runs/ [runs/otra_corrida ...]
"""

from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console

console = Console()


def inspect_run(run_dir: Path) -> None:
    """Inspeccionar los resultados de una corrida anterior."""
    summary_path = run_dir / "summary.json"
    if not summary_path.exists():
        console.print(f"[red]No se encontró summary.json en {run_dir}[/red]")
        raise SystemExit(1)

    with open(summary_path, encoding="utf-8") as f:
        summary = json.load(f)

    console.print("\n[bold cyan]Run Summary[/bold cyan]")
    console.print(f"  Run ID:           {summary.get('run_id', 'N/A')}")
    console.print(f"  Scenario:         {summary.get('scenario', 'N/A')}")
    console.print(f"  Model:            {summary.get('model_name', 'N/A')}")
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
        console.print(
            f"  View / split:     {provenance.get('view', 'N/A')} / {provenance.get('split', 'N/A')}"
        )
        console.print(
            f"  Fingerprint:      {fingerprint[:16]}..." if fingerprint != "—" else "  Fingerprint:      —"
        )
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


def compare_runs(run_dirs: list[Path]) -> None:
    """Comparar métricas de varias corridas en una tabla."""
    from rich.table import Table

    summaries = _collect_summaries(run_dirs)
    if not summaries:
        console.print("[red]No se encontró ningún summary.json en los directorios indicados.[/red]")
        raise SystemExit(1)

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
            str(s.get("model_name", "?")),
            str(s.get("device", "?")),
            str(s.get("prompt_set_id", "?")),
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
        for label in s.get("detections_by_label") or {}:
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


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(prog="eovrt-inspect-runs")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_inspect = sub.add_parser("inspect", help="Inspeccionar una corrida.")
    p_inspect.add_argument("run_dir", type=Path)
    p_compare = sub.add_parser("compare", help="Comparar métricas de varias corridas.")
    p_compare.add_argument(
        "run_dirs",
        type=Path,
        nargs="+",
        help="Directorios de corridas, o un directorio raíz que las contenga (ej. runs/).",
    )
    args = parser.parse_args()
    if args.cmd == "inspect":
        inspect_run(args.run_dir)
    else:
        compare_runs(args.run_dirs)


if __name__ == "__main__":
    main()
