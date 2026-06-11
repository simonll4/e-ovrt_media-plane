# Experimentos del Plano de Medios

Esta sección documenta de forma ordenada la fase experimental: qué estrategias y combinaciones de modelo/prompts/umbrales se prueban, con qué configuración, y qué resultados y conclusiones dejó cada prueba.

La referencia conceptual es [contexto/modelos-candidatos.md](../contexto/modelos-candidatos.md): la matriz de corridas candidatas (Y-E*, G-E*), los criterios mínimos de comparación y los criterios de descarte temprano.

## Síntesis por sprint

| Sprint | Período | Documento | Resumen |
|--------|---------|-----------|---------|
| Sprint 1 | 2026-06-10 | [sintesis-sprint-1.md](sintesis-sprint-1.md) | Validación del pipeline, diagnóstico EPP, comparación YOLOE-26s vs GDINO-base. **Trade-off central documentado: velocidad/VRAM vs cobertura EPP.** |

## Flujo de trabajo de un experimento

```text
1. Definir hipótesis/objetivo (qué se quiere comparar o validar).
2. Crear la config YAML en configs/runs/experiments/ (una config por corrida, sin ramas de código).
3. Ejecutar:  eovrt-media run --config configs/runs/experiments/<config>.yaml
4. Inspeccionar: eovrt-media inspect-run runs/<run_id>  (+ summary.json y previews/)
5. Comparar contra corridas previas: eovrt-media compare-runs runs/
6. Registrar el experimento: copiar plantilla.md a <id>-<slug>.md y completarlo.
7. Agregar una fila al registro de abajo con el veredicto.
```

Reglas heredadas de la documentación de contexto:

- Las corridas se definen **solo por configuración**: el código del pipeline no debe conocer los identificadores `Y-E1`, `G-E1`, etc.
- Toda corrida debe ser reproducible desde su `effective_config.yaml`.
- El descarte de una variante no es un fallo: es un resultado experimental y se documenta igual.
- No inventar nombres de checkpoints: verificar contra [contexto/referencias-modelos.md](../contexto/referencias-modelos.md).

## Dimensiones experimentales

Cada experimento varía una o más de estas dimensiones (registrarlas siempre en la ficha):

| Dimensión | Dónde se configura |
|-----------|--------------------|
| Modelo / checkpoint | `model.name`, `model.model_id` / `model.weights` |
| Resolución de entrada | `model.image_size` |
| Device (cpu/cuda) | `model.device` |
| Umbrales del modelo | `model.confidence_threshold` / `box_threshold` / `text_threshold` / `iou_threshold` |
| Prompt set (versión) | `prompts.file` (ej. `configs/prompts/cr01_cr02_v1.yaml`) |
| Combinación de prompts | `prompts.active_ids` (subconjunto del set) |
| Redacción de prompts | nuevo archivo versionado en `configs/prompts/` (no editar versiones ya usadas) |
| Postproceso | `postprocess.min_confidence`, `min_box_area_px` |
| Fuente / muestreo | `source.*`, `sampling.*` (every_n, target_fps, max_units) |

**Estrategias de prompts**: cada estrategia de redacción o combinación de prompts se materializa como un nuevo prompt set versionado (`cr01_cr02_v2.yaml`, `cr01_cr02_v2_es.yaml`, etc.) o como distintos `active_ids` sobre un set existente. Nunca se modifica un prompt set ya usado en una corrida registrada: se crea una versión nueva.

## Qué registrar por experimento

Mínimo (de `modelos-candidatos.md` § criterios de comparación):

- modelo, model_id/checkpoint, resolución, device;
- prompt set + prompts activos;
- unidades procesadas, detecciones totales, unidades fallidas;
- latencia promedio, latencia p95, FPS efectivo;
- VRAM máxima observada si está disponible;
- errores recuperables.

Cualitativo (especialmente para objetos pequeños como casco/chaleco):

- casco detectado / no detectado;
- chaleco detectado / no detectado;
- falsos positivos frecuentes;
- detecciones inestables entre frames;
- sensibilidad a resolución y a redacción de prompts.

## Registro de experimentos

| ID | Fecha | Ficha | Modelo | Prompt set (active_ids) | Run ID | Veredicto |
|----|-------|-------|--------|-------------------------|--------|-----------|
| Y-E1 | 2026-06-10 | [y-e1-yoloe-26s-640.md](y-e1-yoloe-26s-640.md) | YOLOE-26s @ 640 / cuda | cr01_cr02_v1: person, safety helmet, vest | run_20260610_043437_y_e1_yoloe_26s_640 | Pipeline OK. Person: 138 dets. EPP: 0 dets → ver P-E1 y G-E1 |
| P-E1a | 2026-06-10 | [p-e1-prompt-variants-yoloe.md](p-e1-prompt-variants-yoloe.md) | YOLOE-26s @ 640 / cuda | cr01_cr02_v2_short: person, helmet, vest | run_20260610_044345_p_e1a_yoloe_short_25 | **Nuevo baseline YOLOE.** Helmet: 71 dets @ 0.25. Vest: 0. Vocabulario corto resuelve EPP casco |
| P-E1b | 2026-06-10 | [p-e1-prompt-variants-yoloe.md](p-e1-prompt-variants-yoloe.md) | YOLOE-26s @ 640 / cuda | cr01_cr02_v2_short: person, helmet, vest | run_20260610_044406_p_e1b_yoloe_short_15 | Threshold=0.15: helmet 89, vest 0. No mejora chaleco. P-E1a preferida |
| G-E2 | 2026-06-10 | [g-e2-grounding-dino-base.md](g-e2-grounding-dino-base.md) | GDINO-base / cuda | cr01_cr02_v1: person, safety helmet, high visibility safety vest | run_20260610_045405_g_e2_grounding_dino_b | **Primer chaleco detectado: 28 dets. Helmet: 59. VRAM: 2189 MB. ~1.4 FPS.** Trade-off latencia/EPP documentado |

> Convención de ID: usar los de la matriz (`Y-E1`, `G-E1`, …) cuando el experimento corresponde a una corrida candidata; para experimentos de prompts u otras estrategias usar `P-E1`, `P-E2`, … La ficha se nombra `<id>-<slug>.md` (ej. `y-e1-yoloe-26s-640.md`).

## Fichas individuales

| ID | Ficha | Qué documenta |
|----|-------|---------------|
| Y-E1 | [y-e1-yoloe-26s-640.md](y-e1-yoloe-26s-640.md) | YOLOE-26s baseline. Pipeline OK, EPP=0. Abre diagnóstico de vocabulario. |
| P-E1a/b | [p-e1-prompt-variants-yoloe.md](p-e1-prompt-variants-yoloe.md) | Diagnóstico y corrección de vocabulario en YOLOE. `"helmet"` vs `"safety helmet"`. Vest inviable. |
| G-E2 | [g-e2-grounding-dino-base.md](g-e2-grounding-dino-base.md) | GDINO-base. Primer chaleco detectado (28). Trade-off latencia/VRAM vs cobertura EPP. |
