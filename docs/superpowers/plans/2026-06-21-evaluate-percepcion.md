# eovrt-media evaluate — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agregar el subcomando `eovrt-media evaluate` que evalúa la calidad de percepción de una corrida contra el BENCH v2, produciendo métricas AP@0.5/clase y CR-01 recall de detección, y persiste `eval_perception.json` en el run dir.

**Architecture:** Nuevo módulo `src/eovrt_media/evaluation/` con schemas Pydantic y un runner que importa la lógica de AP@0.5 directamente desde `evaluate_bench.py` del repo hermano (`../e-ovrt_datasets`) usando `importlib.util`. El subcomando `evaluate` se agrega al Typer app existente en `cli.py`. Los tests usan fixtures sintéticos — no requieren el repo hermano.

**Tech Stack:** Python 3.11, Pydantic v2, Typer, Rich, importlib.util (stdlib).

## Global Constraints

- No duplicar lógica de AP@0.5 ni de CR-01: importar desde `evaluate_bench.py` del sibling repo.
- El artefacto se llama `eval_perception.json` (no `eval_results.json`) para dejar lugar al futuro `eval_risk.json` del plano de control.
- Sin dependencias nuevas en `pyproject.toml` — todo lo necesario ya está instalado.
- Tests sin repo hermano: pasar rutas explícitas a fixtures sintéticos en `tmp_path`.
- Seguir el patrón de imports lazy de `cli.py` (imports dentro del cuerpo de la función de comando).
- Cada commit solo con archivos del task correspondiente.

---

## Mapa de archivos

| Archivo | Acción | Responsabilidad |
|---|---|---|
| `src/eovrt_media/evaluation/__init__.py` | Crear | Exporta `run_evaluation`, `EvalPerceptionResults` |
| `src/eovrt_media/evaluation/schemas.py` | Crear | Contratos Pydantic: `ClassResult`, `EvalPerceptionResults` |
| `src/eovrt_media/evaluation/runner.py` | Crear | Orquestación: auto-discover, import evaluate_bench, build result |
| `src/eovrt_media/cli.py` | Modificar | Agregar comando `evaluate` |
| `tests/test_evaluate.py` | Crear | Tests unitarios con fixtures sintéticos |
| `docs/implementation-status.md` | Modificar | Agregar ítem evaluación a la tabla de capacidades |

---

## Task 1: Schemas Pydantic (`evaluation/schemas.py`)

**Files:**
- Create: `src/eovrt_media/evaluation/__init__.py`
- Create: `src/eovrt_media/evaluation/schemas.py`
- Test: `tests/test_evaluate.py`

**Interfaces:**
- Produces:
  - `ClassResult` — resultado per-clase con campos `class_name: str`, `AP50: float | None`, `n_gt: int`, `n_det: int`
  - `EvalPerceptionResults` — resultado completo, serializable a JSON

- [ ] **Step 1: Escribir el test fallido**

```python
# tests/test_evaluate.py
"""Tests para el módulo de evaluación de percepción."""
import json
from pathlib import Path
from eovrt_media.evaluation.schemas import ClassResult, EvalPerceptionResults


def test_class_result_fields():
    r = ClassResult(class_name="person", AP50=0.812, n_gt=10, n_det=11)
    assert r.class_name == "person"
    assert r.AP50 == 0.812
    assert r.n_gt == 10
    assert r.n_det == 11


def test_eval_perception_results_type_literal():
    result = EvalPerceptionResults(
        run_id="run_001",
        benchmark="bench_test",
        iou_threshold=0.5,
        per_class=[ClassResult(class_name="person", AP50=0.8, n_gt=5, n_det=5)],
        cr01_detection_recall=0.7,
        evaluated_at="2026-06-21T22:00:00Z",
    )
    assert result.type == "perception"


def test_eval_perception_results_json_roundtrip():
    result = EvalPerceptionResults(
        run_id="run_001",
        benchmark="bench_test",
        iou_threshold=0.5,
        per_class=[
            ClassResult(class_name="person", AP50=0.812, n_gt=10, n_det=11),
            ClassResult(class_name="helmet", AP50=None, n_gt=0, n_det=3),
        ],
        cr01_detection_recall=None,
        evaluated_at="2026-06-21T22:00:00Z",
    )
    data = json.loads(result.model_dump_json())
    assert data["type"] == "perception"
    assert data["per_class"][0]["class_name"] == "person"
    assert data["per_class"][1]["AP50"] is None
    assert data["cr01_detection_recall"] is None
```

- [ ] **Step 2: Verificar que falla**

```bash
cd /home/simonll4/projects/e-ovrt_media-plane
source .venv/bin/activate
pytest tests/test_evaluate.py -v
```

Esperado: `ImportError` o `ModuleNotFoundError` (módulo no existe aún).

- [ ] **Step 3: Crear `__init__.py` vacío y `schemas.py`**

```python
# src/eovrt_media/evaluation/__init__.py
from eovrt_media.evaluation.schemas import ClassResult as ClassResult
from eovrt_media.evaluation.schemas import EvalPerceptionResults as EvalPerceptionResults
from eovrt_media.evaluation.runner import run_evaluation as run_evaluation

__all__ = ["ClassResult", "EvalPerceptionResults", "run_evaluation"]
```

```python
# src/eovrt_media/evaluation/schemas.py
"""Contratos de evaluación de percepción del plano de medios."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ClassResult(BaseModel):
    """Resultado de evaluación AP@0.5 para una clase."""

    class_name: str
    AP50: float | None
    n_gt: int
    n_det: int


class EvalPerceptionResults(BaseModel):
    """Resultado completo de evaluación de percepción.

    Se persiste como eval_perception.json en el run dir.
    El campo type='perception' distingue este artefacto del futuro
    eval_risk.json del plano de control.
    """

    type: Literal["perception"] = "perception"
    run_id: str
    benchmark: str
    iou_threshold: float
    per_class: list[ClassResult]
    cr01_detection_recall: float | None
    evaluated_at: str
```

**Nota:** el `__init__.py` importa `run_evaluation` desde `runner.py`, que aún no existe. Para evitar error de import durante este step, crear `runner.py` con un stub mínimo:

```python
# src/eovrt_media/evaluation/runner.py  (stub — se implementa en Task 2)
from __future__ import annotations
from pathlib import Path
from eovrt_media.evaluation.schemas import EvalPerceptionResults


def run_evaluation(
    run_dir: Path,
    bench_coco: Path | None = None,
    person_gt: Path | None = None,
    iou_threshold: float = 0.5,
) -> EvalPerceptionResults:
    raise NotImplementedError
```

- [ ] **Step 4: Verificar que los tests pasan**

```bash
pytest tests/test_evaluate.py::test_class_result_fields \
       tests/test_evaluate.py::test_eval_perception_results_type_literal \
       tests/test_evaluate.py::test_eval_perception_results_json_roundtrip -v
```

Esperado: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/eovrt_media/evaluation/ tests/test_evaluate.py
git commit -m "feat: schemas Pydantic para evaluación de percepción (ClassResult, EvalPerceptionResults)"
```

---

## Task 2: Runner (`evaluation/runner.py`)

**Files:**
- Modify: `src/eovrt_media/evaluation/runner.py` (reemplazar stub de Task 1)
- Test: `tests/test_evaluate.py` (agregar tests de runner)

**Interfaces:**
- Consumes:
  - `ClassResult`, `EvalPerceptionResults` de `schemas.py`
  - `load_detections(paths: list[Path]) -> dict[str, list[dict]]` de `evaluate_bench.py`
  - `load_bench_coco(path: Path) -> tuple[dict, dict, dict]` de `evaluate_bench.py`
  - `load_person_gt(path: Path) -> list[dict]` de `evaluate_bench.py`
  - `evaluate_class(class_name, detections_by_img, images_by_filename, gt_by_image_id, cat_by_id, iou_threshold) -> dict` de `evaluate_bench.py`
  - `evaluate_cr01(person_gt_records, detections_by_filename, images_by_filename, iou_threshold) -> dict` de `evaluate_bench.py`
- Produces:
  - `run_evaluation(run_dir, bench_coco, person_gt, iou_threshold) -> EvalPerceptionResults`

- [ ] **Step 1: Escribir fixtures sintéticos y tests del runner**

Agregar al final de `tests/test_evaluate.py`:

```python
import json
import textwrap
from datetime import datetime, timezone


def _write_synthetic_detections(path: Path) -> None:
    """Escribe un detections.jsonl mínimo con 2 eventos."""
    events = [
        {
            "source": {"source_id": "img001.jpg"},
            "detections": [
                {"prompt_id": "person", "label": "person", "confidence": 0.9,
                 "bbox_xyxy": [10.0, 10.0, 100.0, 200.0]},
                {"prompt_id": "helmet", "label": "helmet", "confidence": 0.85,
                 "bbox_xyxy": [20.0, 10.0, 60.0, 40.0]},
            ],
        },
        {
            "source": {"source_id": "img002.jpg"},
            "detections": [
                {"prompt_id": "person", "label": "person", "confidence": 0.75,
                 "bbox_xyxy": [5.0, 5.0, 80.0, 180.0]},
            ],
        },
    ]
    with open(path, "w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")


def _write_synthetic_bench_coco(path: Path) -> None:
    """Escribe un COCO mínimo con 2 imágenes y anotaciones person/helmet."""
    data = {
        "images": [
            {"id": 1, "file_name": "/data/img001.jpg", "width": 640, "height": 480},
            {"id": 2, "file_name": "/data/img002.jpg", "width": 640, "height": 480},
        ],
        "categories": [
            {"id": 1, "name": "person"},
            {"id": 2, "name": "helmet"},
        ],
        "annotations": [
            {"id": 1, "image_id": 1, "category_id": 1, "bbox": [10, 10, 90, 190]},
            {"id": 2, "image_id": 1, "category_id": 2, "bbox": [20, 10, 40, 30]},
            {"id": 3, "image_id": 2, "category_id": 1, "bbox": [5, 5, 75, 175]},
        ],
    }
    path.write_text(json.dumps(data))


def _write_synthetic_person_gt(path: Path) -> None:
    """Escribe un person_gt.json mínimo con 1 violador CR-01."""
    data = {
        "records": [
            {
                "file_name": "/data/img002.jpg",
                "person_bbox": [5.0, 5.0, 80.0, 180.0],
                "has_helmet": False,
            }
        ]
    }
    path.write_text(json.dumps(data))


def test_run_evaluation_returns_perception_results(tmp_path):
    run_dir = tmp_path / "run_001"
    run_dir.mkdir()
    _write_synthetic_detections(run_dir / "detections.jsonl")
    bench_coco = tmp_path / "bench.json"
    person_gt = tmp_path / "person_gt.json"
    _write_synthetic_bench_coco(bench_coco)
    _write_synthetic_person_gt(person_gt)

    from eovrt_media.evaluation.runner import run_evaluation
    result = run_evaluation(run_dir, bench_coco=bench_coco, person_gt=person_gt)

    assert result.type == "perception"
    assert result.run_id == "run_001"
    assert len(result.per_class) == 2
    class_names = {r.class_name for r in result.per_class}
    assert "person" in class_names
    assert "helmet" in class_names


def test_run_evaluation_writes_json(tmp_path):
    run_dir = tmp_path / "run_002"
    run_dir.mkdir()
    _write_synthetic_detections(run_dir / "detections.jsonl")
    bench_coco = tmp_path / "bench.json"
    person_gt = tmp_path / "person_gt.json"
    _write_synthetic_bench_coco(bench_coco)
    _write_synthetic_person_gt(person_gt)

    from eovrt_media.evaluation.runner import run_evaluation
    run_evaluation(run_dir, bench_coco=bench_coco, person_gt=person_gt)

    out = run_dir / "eval_perception.json"
    assert out.exists()
    data = json.loads(out.read_text())
    assert data["type"] == "perception"
    assert "per_class" in data
    assert "cr01_detection_recall" in data


def test_run_evaluation_missing_detections_raises(tmp_path):
    run_dir = tmp_path / "run_empty"
    run_dir.mkdir()
    bench_coco = tmp_path / "bench.json"
    person_gt = tmp_path / "person_gt.json"
    _write_synthetic_bench_coco(bench_coco)
    _write_synthetic_person_gt(person_gt)

    import pytest
    from eovrt_media.evaluation.runner import run_evaluation
    with pytest.raises(FileNotFoundError, match="detections.jsonl"):
        run_evaluation(run_dir, bench_coco=bench_coco, person_gt=person_gt)


def test_auto_discover_missing_sibling_raises(tmp_path, monkeypatch):
    """Sin sibling repo y sin override explícito → FileNotFoundError accionable."""
    run_dir = tmp_path / "run_003"
    run_dir.mkdir()
    _write_synthetic_detections(run_dir / "detections.jsonl")
    monkeypatch.chdir(tmp_path)  # CWD sin sibling e-ovrt_datasets

    import pytest
    from eovrt_media.evaluation.runner import run_evaluation
    with pytest.raises(FileNotFoundError, match="e-ovrt_datasets"):
        run_evaluation(run_dir)  # sin bench_coco ni person_gt → auto-discover falla
```

- [ ] **Step 2: Verificar que los tests nuevos fallan (el runner aún es stub)**

```bash
pytest tests/test_evaluate.py::test_run_evaluation_returns_perception_results \
       tests/test_evaluate.py::test_run_evaluation_writes_json \
       tests/test_evaluate.py::test_run_evaluation_missing_detections_raises \
       tests/test_evaluate.py::test_auto_discover_missing_sibling_raises -v
```

Esperado: 4 FAILED con `NotImplementedError`.

- [ ] **Step 3: Implementar `runner.py`**

```python
# src/eovrt_media/evaluation/runner.py
"""Runner de evaluación de percepción del plano de medios.

Importa la lógica de AP@0.5 y CR-01 desde evaluate_bench.py del repo
hermano (../e-ovrt_datasets) vía importlib — sin duplicar la lógica.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType

from eovrt_media.evaluation.schemas import ClassResult, EvalPerceptionResults

_SIBLING_SCRIPT = Path("../e-ovrt_datasets/datasets/scripts/bench/evaluate_bench.py")
_BENCH_COCO_DEFAULT = Path(
    "../e-ovrt_datasets/datasets/processed/coco/bench/"
    "construction_site_safety_bench.json"
)
_PERSON_GT_DEFAULT = Path(
    "../e-ovrt_datasets/datasets/processed/coco/bench/person_gt.json"
)


def _load_evaluate_bench() -> ModuleType:
    """Carga evaluate_bench.py del repo hermano como módulo."""
    script = _SIBLING_SCRIPT.resolve()
    if not script.exists():
        raise FileNotFoundError(
            f"No se encontró evaluate_bench.py en {script}. "
            "Asegurate de que el repo hermano e-ovrt_datasets esté presente como "
            "sibling en disco, o pasá --bench-coco y --person-gt explícitamente."
        )
    module_name = "evaluate_bench"
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, script)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules[module_name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _resolve_bench_paths(
    bench_coco: Path | None,
    person_gt: Path | None,
) -> tuple[Path, Path]:
    """Devuelve rutas resueltas; auto-discover si no se pasaron."""
    if bench_coco is None or person_gt is None:
        # Trigger importlib para validar que el sibling existe
        _load_evaluate_bench()

    resolved_coco = (bench_coco or _BENCH_COCO_DEFAULT).resolve()
    resolved_gt = (person_gt or _PERSON_GT_DEFAULT).resolve()

    if not resolved_coco.exists():
        raise FileNotFoundError(
            f"bench-coco no encontrado: {resolved_coco}. "
            "Pasá --bench-coco con la ruta correcta."
        )
    if not resolved_gt.exists():
        raise FileNotFoundError(
            f"person-gt no encontrado: {resolved_gt}. "
            "Pasá --person-gt con la ruta correcta."
        )
    return resolved_coco, resolved_gt


def run_evaluation(
    run_dir: Path,
    bench_coco: Path | None = None,
    person_gt: Path | None = None,
    iou_threshold: float = 0.5,
) -> EvalPerceptionResults:
    """Evalúa la calidad de percepción de una corrida y persiste eval_perception.json.

    Args:
        run_dir: directorio de la corrida (debe contener detections.jsonl).
        bench_coco: COCO JSON del BENCH. None = auto-discover desde sibling repo.
        person_gt: GT persona-nivel. None = auto-discover desde sibling repo.
        iou_threshold: umbral IoU para matching (default 0.5).

    Returns:
        EvalPerceptionResults con métricas de percepción.

    Raises:
        FileNotFoundError: si detections.jsonl, bench_coco o person_gt no existen.
    """
    run_dir = Path(run_dir)
    detections_path = run_dir / "detections.jsonl"
    if not detections_path.exists():
        raise FileNotFoundError(
            f"detections.jsonl no encontrado en {run_dir}. "
            "Asegurate de que la corrida se haya ejecutado correctamente."
        )

    bench_coco_path, person_gt_path = _resolve_bench_paths(bench_coco, person_gt)
    eb = _load_evaluate_bench()

    # Cargar datos
    detections_by_img = eb.load_detections([detections_path])
    images_by_basename, gt_by_image_id, cat_by_id = eb.load_bench_coco(bench_coco_path)
    person_gt_records = eb.load_person_gt(person_gt_path)

    # Evaluar per-clase
    per_class = []
    for class_name in cat_by_id.values():
        raw = eb.evaluate_class(
            class_name,
            detections_by_img,
            images_by_basename,
            gt_by_image_id,
            cat_by_id,
            iou_threshold,
        )
        per_class.append(
            ClassResult(
                class_name=raw["class"],
                AP50=raw.get("AP50"),
                n_gt=raw.get("n_gt", 0),
                n_det=raw.get("n_det", 0),
            )
        )

    # CR-01 recall
    cr01_raw = eb.evaluate_cr01(
        person_gt_records, detections_by_img, images_by_basename, iou_threshold
    )
    cr01_recall = cr01_raw.get("cr01_recall")

    result = EvalPerceptionResults(
        run_id=run_dir.name,
        benchmark=bench_coco_path.stem,
        iou_threshold=iou_threshold,
        per_class=per_class,
        cr01_detection_recall=cr01_recall,
        evaluated_at=datetime.now(timezone.utc).isoformat(),
    )

    # Persistir
    out_path = run_dir / "eval_perception.json"
    out_path.write_text(result.model_dump_json(indent=2))

    return result
```

- [ ] **Step 4: Verificar que todos los tests del runner pasan**

```bash
pytest tests/test_evaluate.py -v
```

Esperado: todos los tests PASSED (incluyendo los de Task 1).

- [ ] **Step 5: Commit**

```bash
git add src/eovrt_media/evaluation/runner.py tests/test_evaluate.py
git commit -m "feat: runner de evaluación de percepción con auto-discover de bench paths"
```

---

## Task 3: Comando CLI `evaluate`

**Files:**
- Modify: `src/eovrt_media/cli.py` (agregar comando `evaluate` antes de `if __name__ == "__main__":`)
- Test: `tests/test_evaluate.py` (agregar test de CLI)

**Interfaces:**
- Consumes: `run_evaluation(run_dir, bench_coco, person_gt, iou_threshold)` de `runner.py`
- Produces: comando `eovrt-media evaluate` con salida Rich + `eval_perception.json`

- [ ] **Step 1: Escribir el test del CLI**

Agregar al final de `tests/test_evaluate.py`:

```python
def test_cli_evaluate_command(tmp_path):
    """El comando CLI evalúa un run sintético y escribe eval_perception.json."""
    from typer.testing import CliRunner
    from eovrt_media.cli import app

    run_dir = tmp_path / "run_cli_test"
    run_dir.mkdir()
    _write_synthetic_detections(run_dir / "detections.jsonl")
    bench_coco = tmp_path / "bench.json"
    person_gt = tmp_path / "person_gt.json"
    _write_synthetic_bench_coco(bench_coco)
    _write_synthetic_person_gt(person_gt)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "evaluate",
            "--run", str(run_dir),
            "--bench-coco", str(bench_coco),
            "--person-gt", str(person_gt),
        ],
    )
    assert result.exit_code == 0, result.output
    assert (run_dir / "eval_perception.json").exists()
    assert "AP" in result.output or "person" in result.output
```

- [ ] **Step 2: Verificar que el test falla**

```bash
pytest tests/test_evaluate.py::test_cli_evaluate_command -v
```

Esperado: FAILED — comando `evaluate` no existe aún.

- [ ] **Step 3: Agregar el comando `evaluate` a `cli.py`**

Insertar antes de `if __name__ == "__main__":` al final de `src/eovrt_media/cli.py`:

```python
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
    """Evaluar la calidad de percepción de una corrida contra el BENCH v2.

    Produce métricas AP@0.5 por clase y recall CR-01 de detección.
    Persiste el resultado en <run>/eval_perception.json.
    """
    from rich.table import Table
    from eovrt_media.evaluation.runner import run_evaluation

    console.print(f"\n[bold cyan]E-OVRT Media Plane — Evaluación de percepción[/bold cyan]")
    console.print(f"[dim]Run:[/dim] {run}\n")

    try:
        result = run_evaluation(
            run_dir=run,
            bench_coco=bench_coco,
            person_gt=person_gt,
            iou_threshold=iou_threshold,
        )
    except FileNotFoundError as e:
        console.print(f"[red]✗ {e}[/red]")
        raise typer.Exit(1)

    # Tabla de resultados
    table = Table(title=f"Percepción — {result.run_id}")
    table.add_column("Clase", style="cyan")
    table.add_column("AP@0.5", justify="right")
    table.add_column("n_gt", justify="right")
    table.add_column("n_det", justify="right")

    for cls in result.per_class:
        ap_str = f"{cls.AP50:.3f}" if cls.AP50 is not None else "—"
        table.add_row(cls.class_name, ap_str, str(cls.n_gt), str(cls.n_det))

    console.print(table)

    if result.cr01_detection_recall is not None:
        console.print(
            f"\n[bold]CR-01 recall (detección):[/bold] {result.cr01_detection_recall:.3f}"
        )
    else:
        console.print("\n[dim]CR-01 recall: sin violadores en el GT[/dim]")

    out_path = run / "eval_perception.json"
    console.print(f"\n[green]✓ Guardado:[/green] {out_path}\n")
```

- [ ] **Step 4: Verificar que todos los tests pasan**

```bash
pytest tests/test_evaluate.py -v
```

Esperado: todos PASSED.

- [ ] **Step 5: Verificar que ruff está limpio**

```bash
ruff check src/eovrt_media/cli.py src/eovrt_media/evaluation/
```

Esperado: `All checks passed!`

- [ ] **Step 6: Smoke test manual del comando**

```bash
eovrt-media evaluate --help
```

Esperado: muestra opciones `--run`, `--bench-coco`, `--person-gt`, `--iou-threshold`.

- [ ] **Step 7: Commit**

```bash
git add src/eovrt_media/cli.py tests/test_evaluate.py
git commit -m "feat: subcomando eovrt-media evaluate — evaluación de percepción con tabla Rich"
```

---

## Task 4: Documentación y verificación final

**Files:**
- Modify: `docs/implementation-status.md`

**Interfaces:** ninguna — solo documentación.

- [ ] **Step 1: Actualizar `docs/implementation-status.md`**

En la tabla "Límites conocidos y trabajo encaminado", agregar la fila:

```markdown
| Evaluación de percepción | **Implementado** | `eovrt-media evaluate --run runs/<id>` — AP@0.5/clase y CR-01 recall de detección. Persiste `eval_perception.json`. |
```

- [ ] **Step 2: Correr la suite completa**

```bash
pytest -q
```

Esperado: todos los tests pasan (los 150 previos + los nuevos de `test_evaluate.py`).

- [ ] **Step 3: Verificar ruff**

```bash
ruff check src tests
```

Esperado: `All checks passed!`

- [ ] **Step 4: Commit final**

```bash
git add docs/implementation-status.md
git commit -m "docs: registrar eovrt-media evaluate en implementation-status"
```

---

## Self-Review

**Cobertura del spec:**
- ✅ Auto-discover de bench paths desde sibling repo
- ✅ Override explícito con `--bench-coco` / `--person-gt`
- ✅ `eval_perception.json` con `type=perception` (frontera explícita)
- ✅ Tabla Rich en pantalla + persist
- ✅ `cr01_detection_recall` como proxy de detección
- ✅ Tests sin repo hermano (fixtures sintéticos en tmp_path)
- ✅ Error accionable cuando sibling no existe
- ✅ Import via `importlib.util` (no duplica lógica de AP)

**Tipos consistentes a lo largo del plan:**
- `run_evaluation(run_dir: Path, bench_coco: Path | None, person_gt: Path | None, iou_threshold: float) -> EvalPerceptionResults` — mismo en Task 2 (implementación) y Task 3 (consumidor CLI).
- `ClassResult.class_name` (no `class`) — alineado con la restricción de que `class` es keyword de Python; el campo `class` devuelto por `evaluate_bench.py` se mapea a `class_name` en el runner (Task 2, Step 3: `raw["class"]` → `class_name=raw["class"]`).

**Sin placeholders:** todos los steps tienen código completo.
