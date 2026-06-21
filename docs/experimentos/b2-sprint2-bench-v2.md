# Sprint 2 — Evaluación cuantitativa BENCH v2

**Período:** 2026-06-18  
**Estado:** completado  
**Datasets:** construction_site_safety v27, val+test (196 imgs total)  
**Prompt set:** `cr01_cr02_bench_v2` — `person / helmet / vest / bare head`  
**Evaluación:** `datasets/scripts/bench/evaluate_bench.py`, IoU ≥ 0.5

## Objetivo

Obtener métricas cuantitativas baseline de detección zero-shot sobre el BENCH v2 para los 5 modelos candidatos. Comparar AP@50 por clase y recall CR-01 (E1: detección directa de `bare_head`). Identificar candidatos para fases posteriores.

## Configuración común

| Dimensión | Valor |
|---|---|
| Dataset BENCH | construction_site_safety v27, val (114) + test (82) = 196 imgs |
| Prompt set | `cr01_cr02_bench_v2` |
| Prompts activos | `person`, `helmet`, `vest`, `bare_head` |
| IoU threshold evaluación | 0.5 |
| Device | cuda |
| Escenario | DBE (zero-shot, pesos originales) |

> **Nota metodológica:** el BENCH COCO contiene todas las anotaciones de las 196 imágenes. Las evaluaciones por split usan el GT completo como denominador, por lo que las métricas por split no son comparables entre sí. La tabla principal usa val+test combinados (evaluación correcta sobre las 196 imágenes completas).

## Resultados BENCH completo (val+test, 196 imgs)

| Modelo | mAP@50 | AP person | AP helmet | AP vest | AP bare_head | CR-01 recall E1 |
|---|---|---|---|---|---|---|
| GDINO-tiny | **0.441** | 0.703 | **0.794** | 0.245 | 0.023 | 0.414 |
| GDINO-base | 0.416 | 0.623 | 0.582 | **0.439** | 0.019 | **0.523** |
| MM-GDINO-tiny | 0.006 | 0.024 | 0.000 | 0.000 | 0.000 | 0.000 |
| MM-GDINO-base | 0.337 | 0.559 | 0.428 | 0.360 | 0.001 | 0.027 |
| YOLOE-26l | 0.358 | 0.714 | 0.629 | 0.091 | 0.000 | 0.000 |

GT ref: 340 personas, 189 helmets, 102 vests, 110 bare_heads, 111 violadoras CR-01.

## Rendimiento computacional

| Modelo | FPS (test) | FPS (val) | VRAM MB | Avg lat ms |
|---|---|---|---|---|
| GDINO-tiny | 1.42 | 2.06 | 1486 | ~560 |
| GDINO-base | 1.89 | 1.89 | 1722 | ~450 |
| MM-GDINO-tiny | 1.73 | 2.31 | 1486 | ~470 |
| MM-GDINO-base | 1.42 | 1.72 | 1722 | ~600 |
| YOLOE-26l | 9.00 | 14.30 | 318 | ~78 |

## Diagnóstico: MM-GDINO-tiny — bboxes degeneradas

MM-GDINO-tiny produce detecciones con bounding boxes completamente degeneradas: ancho promedio = 61 px, alto promedio = 518 px. Las cajas son franjas verticales casi colapsadas (min width < 1 px). Ejemplo en `000005_jpg.rf.*`:

- GT person: `[0,139,152,534]` (ancho=152, alto=395)
- MM-GDINO-tiny person: `[65,188,80,799]` (ancho=15, alto=611)
- MM-GDINO-tiny helmet: `[116,90,117,544]` (ancho=1, alto=454)

La causa probable es un bug en el adaptador `mmgdino_adapter.py` que invierte o colapsa la coordenada x2 durante la post-procesión de los resultados de OpenMMLab. MM-GDINO-base no exhibe este comportamiento.

**Veredicto: MM-GDINO-tiny DESCARTADO** para Sprint 2 y fases posteriores. No investigar en este sprint; registrar para diagnóstico futuro.

## Observaciones por modelo

### GDINO-tiny (E1)
- **Mejor mAP global (0.441)** y mejor AP helmet (0.794). Cobertura de persona aceptable.
- Vest moderado (AP=0.245). bare_head casi nulo (AP=0.023).
- CR-01 recall E1 = 0.414: el 41% de las personas sin casco tienen al menos una detección de `bare_head` dentro de su head_region. Resultado más alto en la estrategia E1.
- FPS bajo (~1.4 test / 2.1 val) — no viable para tiempo real, pero suficiente para análisis offline.

### GDINO-base (E2)
- mAP=0.416, pero **mejor vest (AP=0.439)** y **mejor CR-01 recall E1 (0.523)**.
- Helmet más bajo que GDINO-tiny (0.582 vs 0.794). Persona similar.
- bare_head bajo (AP=0.019) — consistente con todos los modelos.
- FPS similar a GDINO-tiny (~1.9 FPS), VRAM ligeramente mayor (1722 MB).

### MM-GDINO-base (E6)
- Bboxes válidas (a diferencia de MM-GDINO-tiny). mAP=0.337, por debajo de ambas variantes GDINO.
- Vest razonable (AP=0.360). bare_head casi nulo (AP=0.001), CR-01 E1 = 0.027.
- Con la misma VRAM y FPS similar a GDINO-base pero peor mAP: no hay ventaja clara sobre GDINO-base.

### YOLOE-26l (E3)
- **Muy rápido: 9–14 FPS, VRAM 318 MB** — único viable para tiempo real sin hardware especializado.
- Helmet excelente en precisión (96% precision test, AP=0.629). Persona buena (AP=0.714).
- **Vest casi nulo (AP=0.091, recall=5-9%)** — falla sistemáticamente en chaleco.
- **bare_head = 0 detecciones**. YOLOE no responde al prompt "bare head" en ningún split.
- CR-01 recall E1 = 0 por ambas razones: sin bare_head y sin vest (no hay cobertura de EPP).
- El trade-off velocidad/cobertura es severo: si solo se necesita detector de personas + casco (CR-01 con otra estrategia), YOLOE-26l es competitivo. Para EPP completo (vest + bare_head), no es viable zero-shot.

## Conclusiones del Sprint 2

1. **La detección directa de `bare_head` (E1) es un baseline débil** para todos los modelos: AP máximo 0.023 (GDINO-tiny). La estrategia E2 (inferir violación CR-01 desde matching persona-sin-casco) es la dirección correcta.

2. **GDINO-tiny y GDINO-base son los candidatos viables** para fases posteriores. GDINO-tiny lidera en mAP y helmet; GDINO-base lidera en vest y CR-01 E1.

3. **MM-GDINO-tiny descartado** por bug de bboxes. MM-GDINO-base funciona pero no supera a GDINO-base.

4. **YOLOE-26l es el candidato para escenarios de velocidad**, pero requiere una solución alternativa para vest y bare_head (fine-tuning o estrategia E2 basada solo en helmet).

5. **La detección de vest es el cuello de botella del BENCH**: AP máximo 0.439 (GDINO-base). CR-02 no es evaluable en este BENCH (no hay GT de `has_vest=False`).

## Run IDs

| Config | Run ID |
|---|---|
| b2_g_e1_gdino_t_test | run_20260618_033948_b2_g_e1_gdino_t_test |
| b2_g_e1_gdino_t_val | run_20260618_034055_b2_g_e1_gdino_t_val |
| b2_g_e2_gdino_b_test | run_20260618_033315_b2_g_e2_gdino_b_test |
| b2_g_e2_gdino_b_val | run_20260618_033802_b2_g_e2_gdino_b_val |
| b2_g_e5_mmgdino_t_test | run_20260618_034158_b2_g_e5_mmgdino_t_test |
| b2_g_e5_mmgdino_t_val | run_20260618_034253_b2_g_e5_mmgdino_t_val |
| b2_g_e6_mmgdino_b_test | run_20260618_034348_b2_g_e6_mmgdino_b_test |
| b2_g_e6_mmgdino_b_val | run_20260618_034454_b2_g_e6_mmgdino_b_val |
| b2_y_e3_yoloe_26l_test | run_20260618_034606_b2_y_e3_yoloe_26l_test |
| b2_y_e3_yoloe_26l_val | run_20260618_034622_b2_y_e3_yoloe_26l_val |

> Hay duplicados en runs/ por overlap de dos tareas en background. Los IDs listados corresponden a los runs seleccionados (segundo run de cada config, excepto gdino_b donde el primero es completo).
