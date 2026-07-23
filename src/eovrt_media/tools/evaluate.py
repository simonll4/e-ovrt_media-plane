"""Evaluar la percepción de una corrida contra el BENCH.

Uso: `python -m eovrt_media.tools.evaluate --run runs/<run_id> [--bench-coco ...] [--person-gt ...]`
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

console = Console()


def evaluate(
    run: Path,
    bench_coco: Path | None = None,
    person_gt: Path | None = None,
    iou_threshold: float = 0.5,
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
            # Igual que el servicio: sin esto, un run de un solo split se evalúa
            # contra el person_gt de AMBOS splits y el recall CR-01 sale
            # deflactado ~2x en silencio (docs/operacion/64 del repo docs).
            restrict_gt_to_detections=True,
        )
    except FileNotFoundError as error:
        console.print(f"[red]✗ No se pudo evaluar la corrida:[/red] {error}")
        console.print(
            "[red]Verifique detections.jsonl y las rutas de --bench-coco y --person-gt.[/red]"
        )
        raise SystemExit(1)

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


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(prog="eovrt-evaluate")
    parser.add_argument(
        "--run",
        type=Path,
        required=True,
        help="Directorio de la corrida a evaluar (debe contener detections.jsonl).",
    )
    parser.add_argument(
        "--bench-coco",
        type=Path,
        default=None,
        help="COCO JSON del BENCH. Por defecto: auto-discover desde ../e-ovrt_datasets/.",
    )
    parser.add_argument(
        "--person-gt",
        type=Path,
        default=None,
        help="GT persona-nivel (person_gt.json). Por defecto: auto-discover.",
    )
    parser.add_argument(
        "--iou-threshold",
        type=float,
        default=0.5,
        help="Umbral IoU para matching detección/GT (default: 0.5).",
    )
    args = parser.parse_args()
    evaluate(
        run=args.run,
        bench_coco=args.bench_coco,
        person_gt=args.person_gt,
        iou_threshold=args.iou_threshold,
    )


if __name__ == "__main__":
    main()
