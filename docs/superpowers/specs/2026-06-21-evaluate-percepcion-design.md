# Spec: `eovrt-media evaluate` — Evaluación de percepción del plano de medios

**Fecha:** 2026-06-21  
**Estado:** Aprobado para implementación  
**Rama destino:** `feat/evaluate-percepcion`

---

## Contexto y motivación

La plataforma E-OVRT-VDP tiene dos planos con responsabilidades distintas:

```
Fuente de video
→ Plano de medios   → detections.jsonl   (evidencia visual)
→ Plano de control  → risk_events.jsonl  (patrones de riesgo confirmados)
→ Alerta asistiva
```

`detections.jsonl` es la interfaz limpia entre ambos planos. Para evaluar la calidad
del plano de medios de forma aislada existe `evaluate_bench.py` en el repo hermano
`e-ovrt_datasets`, pero hoy no hay un comando integrado al CLI del media plane.

Este spec define el subcomando `eovrt-media evaluate`, que cierra el loop evaluativo
de percepción: **corrida → detections.jsonl → métricas de percepción**.

### Frontera explícita de evaluación

Existen dos niveles de evaluación con artefactos separados:

| Nivel | Quién | Artefacto en el run dir | Métricas |
|---|---|---|---|
| **Percepción** | `eovrt-media evaluate` | `eval_perception.json` | AP@0.5/clase, recall de detección |
| **Riesgo** | `eovrt-control evaluate` *(futuro)* | `eval_risk.json` | Precisión/recall de CR-01/CR-02 a nivel de alerta/episodio |

El campo `cr01_detection_recall` en `eval_perception.json` es un **proxy de detección**
(¿el modelo detectó los objetos relevantes para CR-01?), no una evaluación de la regla
de riesgo — eso es responsabilidad del plano de control.

---

## Interfaz de usuario

### Comando

```bash
# Caso normal: auto-discover de bench paths desde el sibling repo
eovrt-media evaluate --run runs/<run_id>

# Override explícito de rutas (CI, layouts no estándar)
eovrt-media evaluate --run runs/<run_id> \
    --bench-coco ../e-ovrt_datasets/datasets/processed/coco/bench/construction_site_safety_bench.json \
    --person-gt  ../e-ovrt_datasets/datasets/processed/coco/bench/person_gt.json

# IoU threshold alternativo
eovrt-media evaluate --run runs/<run_id> --iou-threshold 0.75
```

### Salida en pantalla (Rich table)

```
Run: run_20260621_dbe_yoloe_demo_v2
Benchmark: construction_site_safety bench (196 imgs)
IoU threshold: 0.50

┌────────────┬────────┬───────┬───────┐
│ Class      │ AP@0.5 │  n_gt │ n_det │
├────────────┼────────┼───────┼───────┤
│ person     │  0.812 │   423 │   441 │
│ helmet     │  0.634 │   289 │   312 │
│ vest       │  0.591 │   201 │   198 │
│ bare_head  │  0.488 │    87 │    79 │
├────────────┼────────┼───────┼───────┤
│ CR-01 recall (detección)      │ 0.71 │
└───────────────────────────────┴──────┘

Guardado: runs/run_20260621.../eval_perception.json
```

### Artefacto `eval_perception.json`

```json
{
  "type": "perception",
  "run_id": "run_20260621_dbe_yoloe_demo_v2",
  "benchmark": "construction_site_safety_bench",
  "iou_threshold": 0.5,
  "per_class": [
    {"class": "person",    "AP50": 0.812, "n_gt": 423, "n_det": 441},
    {"class": "helmet",    "AP50": 0.634, "n_gt": 289, "n_det": 312},
    {"class": "vest",      "AP50": 0.591, "n_gt": 201, "n_det": 198},
    {"class": "bare_head", "AP50": 0.488, "n_gt":  87, "n_det":  79}
  ],
  "cr01_detection_recall": 0.71,
  "evaluated_at": "2026-06-21T22:00:00Z"
}
```

---

## Arquitectura interna

### Nuevo módulo `src/eovrt_media/evaluation/`

```
src/eovrt_media/evaluation/
├── __init__.py
├── schemas.py      # ClassResult, EvalPerceptionResults (Pydantic)
└── runner.py       # run_evaluation() — orquestación sin lógica de AP
```

**`schemas.py`** — contratos del resultado:

```python
class ClassResult(BaseModel):
    class_name: str
    AP50: float | None
    n_gt: int
    n_det: int

class EvalPerceptionResults(BaseModel):
    type: Literal["perception"] = "perception"
    run_id: str
    benchmark: str
    iou_threshold: float
    per_class: list[ClassResult]
    cr01_detection_recall: float | None
    evaluated_at: str
```

**`runner.py`** — función principal:

```python
def run_evaluation(
    run_dir: Path,
    bench_coco: Path | None = None,   # None = auto-discover
    person_gt: Path | None = None,    # None = auto-discover
    iou_threshold: float = 0.5,
) -> EvalPerceptionResults
```

La lógica de AP@0.5 y recall **se importa directamente** desde
`evaluate_bench.py` del repo hermano — no se duplica. El runner importa las
funciones `load_detections`, `load_bench_coco`, `load_person_gt`,
`evaluate_class` y `evaluate_cr01_recall`.

### Auto-discovery de bench paths

```python
DATASETS_SIBLING = Path.cwd().parent / "e-ovrt_datasets"
BENCH_COCO_DEFAULT = DATASETS_SIBLING / "datasets/processed/coco/bench/construction_site_safety_bench.json"
PERSON_GT_DEFAULT  = DATASETS_SIBLING / "datasets/processed/coco/bench/person_gt.json"
```

Si alguno no existe y no se pasó override: `FileNotFoundError` con mensaje
accionable que indica cómo pasar las rutas explícitamente.

### Integración en `cli.py`

Nuevo comando `evaluate` registrado en la app Typer existente:

```python
@app.command()
def evaluate(
    run: Path = typer.Option(..., help="Directorio del run a evaluar"),
    bench_coco: Path | None = typer.Option(None),
    person_gt: Path | None = typer.Option(None),
    iou_threshold: float = typer.Option(0.5),
): ...
```

---

## Manejo de errores

| Condición | Comportamiento |
|---|---|
| `--run` no existe | `typer.BadParameter` antes de importar nada |
| `detections.jsonl` no existe en el run dir | `FileNotFoundError` con ruta |
| Sibling repo no encontrado (auto-discover) | `FileNotFoundError` + instrucción de override |
| `evaluate_bench.py` no importable | `ImportError` con ruta esperada del sibling |
| Run sin detecciones (todas vacías) | Resultado válido con AP50=0.0, advertencia |

---

## Testing

No se requiere el repo hermano en tests. Los fixtures crean:
- Un `detections.jsonl` sintético mínimo (2-3 eventos con detecciones)
- Un `bench_coco` sintético mínimo (3-5 imágenes, GT person/helmet)
- Un `person_gt` sintético mínimo

Tests a implementar:
1. `test_run_evaluation_basic` — resultado tiene estructura `EvalPerceptionResults`
2. `test_eval_perception_json_written` — archivo escrito en run dir con `type=perception`
3. `test_auto_discover_missing_raises` — FileNotFoundError con mensaje accionable
4. `test_cli_evaluate_runs_end_to_end` — CLI con run dir temporal, bench sintético

---

## Archivos a crear / modificar

| Archivo | Acción |
|---|---|
| `src/eovrt_media/evaluation/__init__.py` | Crear |
| `src/eovrt_media/evaluation/schemas.py` | Crear |
| `src/eovrt_media/evaluation/runner.py` | Crear |
| `src/eovrt_media/cli.py` | Modificar — agregar comando `evaluate` |
| `tests/test_evaluate.py` | Crear |
| `docs/implementation-status.md` | Modificar — agregar ítem evaluación |

---

## Fuera de alcance

- Evaluación de riesgo (CR-01/CR-02 a nivel de alerta/episodio) — eso es `eval_risk.json` del plano de control.
- Comparación de evaluaciones entre múltiples runs — puede hacerse con `compare-runs` extendido en el futuro.
- Visualización de curvas PR — fuera de alcance para esta iteración.
- Generación automática del bench COCO si no existe — el repo hermano debe tener los archivos procesados.
