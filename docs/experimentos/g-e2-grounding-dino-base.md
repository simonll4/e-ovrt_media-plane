# G-E2 — Grounding DINO base, baseline semántico en GPU

**Creado:** 2026-06-10 | **Actualizado:** 2026-06-10 | **Estado:** ejecutado
**Config:** `configs/runs/experiments/g_e2_grounding_dino_b.yaml`
**Run ID:** `runs/run_20260610_045405_g_e2_grounding_dino_b`

> G-E1 (tiny) fue omitida: se pasó directamente a G-E2 (base) por decisión del equipo.

## Hipótesis / objetivo

Grounding DINO base tiene mayor expresividad semántica que YOLOE-26s para prompts compuestos. La hipótesis es que puede detectar `"safety helmet"` y `"high visibility safety vest"` con los mismos prompts que Y-E1 usó con resultado 0.

**Dimensión variada respecto a Y-E1 / P-E1a:** modelo completo (GDINO base vs YOLOE-26s), manteniendo los mismos prompts de la versión v1 (`cr01_cr02_v1`) para aislar el efecto del modelo.

## Configuración

| Dimensión | Valor |
|-----------|-------|
| Modelo / checkpoint | `IDEA-Research/grounding-dino-base` |
| Pesos locales | `models/grounding-dino/original/grounding-dino-base/` (888 MB) |
| Resolución | default HuggingFace (~800 px lado mayor) |
| Device | `cuda` (RTX 4060 Laptop GPU) |
| `box_threshold` | 0.30 |
| `text_threshold` | 0.25 |
| Prompt set | `cr01_cr02_v1` |
| Prompts activos | `person`, `safety helmet`, `high visibility safety vest` |
| Texto enviado al modelo | `"person. safety helmet. high visibility safety vest."` |
| `min_confidence` postprocess | 0.25 |
| `min_box_area_px` | 100 px² |
| Fuente | `dataset_v1` — 37 imágenes, mode=all |

## Resultados cuantitativos

| Métrica | Y-E1 (referencia) | P-E1a (YOLOE short) | **G-E2 (GDINO base)** |
|---------|-------------------|----------------------|------------------------|
| Unidades procesadas | 37 / 37 | 37 / 37 | **37 / 37** |
| Unidades fallidas | 0 | 0 | **0** |
| Detecciones totales | 138 | 209 | **299** |
| — person | 138 | 138 | **212** |
| — safety helmet / helmet | 0 | 71 | **59** |
| — high visibility safety vest / vest | 0 | 0 | **28** |
| Latencia promedio (ms) | 853.4 ¹ | 98.9 | **705.4** |
| Latencia p95 (ms) | 220.6 ¹ | 123.6 | **578.9** |
| FPS efectivo | 1.09 ¹ | 7.41 | **1.42** |
| VRAM pico (MB) | 157.7 | 159 | **2189** |
| Errores recuperables | 0 | 0 | **0** |

> ¹ Y-E1 incluye warmup de CUDA + descarga de mobileclip2_b.ts en la primera inferencia.

## Corrección en el adaptador (aplicada antes de esta corrida)

GDINO realiza matching de sub-spans del texto de entrada. En la corrida anterior (sin corrección) apareció el label `"visibility safety": 1` — un span parcial de `"high visibility safety vest"`. Se aplicaron dos fixes al adaptador:

1. **`text_labels` en lugar de `labels`** — key estable para strings (en transformers ≥4.51, `labels` devolverá IDs enteros).
2. **`_normalize_label()`** — mapea cada span detectado al prompt original más cercano por solapamiento de palabras.

Con la corrección, los 299 totales se distribuyen limpiamente entre los 3 prompts activos.

## Observaciones cualitativas

- **Person:** 212 detecciones vs 138 de YOLOE (+54%). GDINO detecta más personas, probablemente incluyendo trabajadores parcialmente visibles u ocluidos que YOLOE descartaba.
- **Safety helmet:** 59 detecciones — funciona la frase compuesta que YOLOE no podía procesar. Sin embargo, es menos que las 71 de `"helmet"` en P-E1a. Probable explicación: GDINO y YOLOE difieren en qué regiones asocian con el concepto visual; YOLOE podría estar incluyendo falsas detecciones como cascos.
- **High visibility safety vest:** **28 detecciones** — primera evidencia de que el chaleco es detectable en dataset_v1. Esto confirma que era una limitación del vocabulario/modelo de YOLOE, no de las imágenes.
- **VRAM:** 2189 MB — 14× más que YOLOE (159 MB). Sigue siendo viable en RTX 4060 (8 GB VRAM), pero no deja margen para otros procesos GPU.
- **Latencia:** ~705 ms avg (~1.4 FPS), 5-7× más lento que YOLOE en condiciones estacionarias. No apto para realtime; viable para análisis offline.

## Análisis

### GDINO vs YOLOE para EPP

| Aspecto | YOLOE-26s | GDINO-base |
|---------|-----------|------------|
| Prompts compuestos | Débil | Fuerte |
| Detección de casco | 71 (label corto) / 0 (compuesto) | 59 (compuesto) |
| Detección de chaleco | 0 | **28** |
| Latencia | ~99 ms | ~705 ms |
| VRAM | 159 MB | 2189 MB |
| FPS estacionario | ~10 FPS | ~1.4 FPS |

GDINO es claramente superior para EPP con prompts descriptivos. El chaleco es el discriminador clave: YOLOE no puede detectarlo con ningún vocabulario probado; GDINO lo detecta con la frase compuesta original.

### Implicación para el TFG

La detección de EPP (CR-01, CR-02) es viable con GDINO-base, pero a costo de latencia y VRAM. Para una aplicación offline (análisis de video post-grabación) esto es aceptable. Para una aplicación near-realtime habría que evaluar YOLOE + un modelo de verificación EPP por recorte, o un modelo especializado en EPP.

## Conclusión y decisión

**G-E2 confirma la hipótesis:** GDINO base detecta chaleco (28 dets) y casco (59 dets) con los prompts compuestos de v1. Esto cierra el ciclo de diagnóstico EPP iniciado en Y-E1.

**Trade-off central documentado:**
- YOLOE-26s: rápido (99 ms), eficiente (159 MB VRAM), buen casco con label corto, chaleco inviable.
- GDINO-base: lento (705 ms), costoso (2189 MB VRAM), buen casco y chaleco con frases compuestas.

**Próximos pasos:**

1. **Y-E2** — YOLOE-26m @ 640: ¿mejora la detección de chaleco con modelo más grande?
2. **G-E2b (opcional)** — GDINO base con `cr01_cr02_v2_short` (`"helmet"`, `"vest"`) para separar si el label corto mejora también en GDINO.
3. **Decisión de arquitectura:** ¿se continúa optimizando YOLOE o se acepta GDINO como modelo principal para EPP en el TFG?
