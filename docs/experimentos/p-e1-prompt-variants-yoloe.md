# P-E1 — Variantes de prompts EPP en YOLOE-26s

**Creado:** 2026-06-10 | **Actualizado:** 2026-06-10 | **Estado:** ejecutado
**Configs:**
- P-E1a: `configs/runs/experiments/p_e1a_yoloe_short_prompts_25.yaml`
- P-E1b: `configs/runs/experiments/p_e1b_yoloe_short_prompts_15.yaml`
**Run IDs:**
- P-E1a: `runs/run_20260610_044345_p_e1a_yoloe_short_25`
- P-E1b: `runs/run_20260610_044406_p_e1b_yoloe_short_15`

## Hipótesis / objetivo

Y-E1 produjo 0 detecciones de EPP con las etiquetas `"safety helmet"` y `"high visibility safety vest"`. La hipótesis es que el encoder CLIP de YOLOE-26s responde mejor a etiquetas cortas y genéricas (`"helmet"`, `"vest"`) que a frases compuestas.

**Dimensión variada respecto a Y-E1:** redacción de prompts (nuevo prompt set `cr01_cr02_v2_short`) y, en P-E1b, umbral de confianza bajado a 0.15.

## Diagnóstico previo

Antes de diseñar los configs se corrió un probe manual a `conf=0.01` sobre el dataset completo con cuatro combinaciones de vocabu­lario:

| Variante | helmet-like (≥0.25) | vest-like (≥0.25) | top conf helmet | top conf vest |
|----------|--------------------|--------------------|-----------------|---------------|
| `safety helmet` + `high visibility safety vest` | **0** | **0** | — | — |
| `helmet` + `vest` | **75** | **0** | 0.877 | 0.136 |
| `hard hat` + `safety vest` | 25 | 0 | 0.776 | 0.187 |
| `helmet` + `high visibility vest` | 75 | 0 | 0.877 | 0.145 |

`"helmet"` es claramente la mejor etiqueta EPP para YOLOE. Ninguna variante de chaleco supera 0.25.

## Configuración

| Dimensión | P-E1a | P-E1b |
|-----------|-------|-------|
| Modelo / checkpoint | `yoloe-26s-seg.pt` | `yoloe-26s-seg.pt` |
| Resolución | 640 | 640 |
| Device | `cuda` | `cuda` |
| Prompt set | `cr01_cr02_v2_short` | `cr01_cr02_v2_short` |
| Prompts activos | `person`, `helmet`, `vest` | `person`, `helmet`, `vest` |
| `confidence_threshold` | **0.25** | **0.15** |
| `iou_threshold` | 0.50 | 0.50 |
| `min_box_area_px` | 100 px² | 100 px² |
| Fuente | `dataset_v1` — 37 imágenes | `dataset_v1` — 37 imágenes |

## Resultados cuantitativos

| Métrica | Y-E1 (referencia) | P-E1a (0.25) | P-E1b (0.15) |
|---------|-------------------|--------------|--------------|
| Unidades procesadas | 37 / 37 | 37 / 37 | 37 / 37 |
| Unidades fallidas | 0 | 0 | 0 |
| Detecciones totales | 138 | 209 | 270 |
| — person | 138 | 138 | 181 |
| — helmet | **0** | **71** | **89** |
| — vest | 0 | **0** | **0** |
| Latencia promedio (ms) | 853.4 ¹ | **98.9** | **96.8** |
| Latencia p95 (ms) | 220.6 ¹ | 123.6 | 115.6 |
| FPS efectivo | 1.09 ¹ | 7.41 | 7.51 |
| VRAM pico (MB) | 157.7 | 159 | 159 |
| Errores recuperables | 0 | 0 | 0 |

> ¹ Y-E1 penalizada por warmup de CUDA + descarga de `mobileclip2_b.ts` en la primera inferencia (~28.8 s). Sin warmup, YOLOE-26s @ 640 estabiliza en ~97-100 ms avg (~10 FPS sobre dataset de imágenes estáticas).

## Observaciones cualitativas

- **Helmet:** el cambio de `"safety helmet"` → `"helmet"` resuelve completamente el problema EPP de Y-E1. Con 71 detecciones a 0.25 en 37 imágenes, el casco es detectable. La confianza máxima observada es 0.877.
- **Vest:** persiste en 0 en ambas corridas. Bajar el umbral a 0.15 no produce ninguna detección de `"vest"`. La confianza máxima en el probe fue 0.136, por debajo de cualquier umbral operacionalmente útil.
- **Person @ 0.15:** sube de 138 → 181 (+31%), lo que indica que el umbral 0.15 añade falsos positivos o personas parcialmente visibles que no se querían contar. Para `person` el umbral 0.25 parece más apropiado.
- **Latencia estacionaria:** P-E1a y P-E1b muestran latencias similares (~97 ms avg, ~120 ms p95), confirmando que el warmup de Y-E1 era el culpable de la métrica de latencia alta.

## Análisis

### Vocabulario CLIP en YOLOE-26s

El encoder de texto CLIP de YOLOE-26s tiene un vocabulario entrenado principalmente con etiquetas cortas de COCO y compendios similares. Las frases compuestas como `"high visibility safety vest"` (4 tokens) tienen baja activación porque:
1. Rara vez aparecen literalmente en los pares imagen-texto de CLIP.
2. El modelo pequeño (26s) tiene capacidad embeddings limitada para desambiguar frases largas.

`"helmet"` sí aparece en COCO/OpenImages y el backbone lo reconoce con alta confianza.

### Vest: ¿limitación del modelo o del dataset?

Las imágenes de MOCS son fotos de obras a distancia o media distancia. Los chalecos reflectantes son objetos pequeños con características visuales similares a otras prendas (chaqueta naranja, ropa de trabajo). YOLOE-26s no parece haber aprendido suficientes ejemplos de chalecos reflectantes para separarlo de ropa genérica. El probe a conf=0.01 muestra que las pocas veces que `"vest"` recibe alguna puntuación, es en el rango 0.10-0.14 — consistentemente sub-umbral.

**Hipótesis principal:** la detección de chaleco requiere un modelo más expresivo semánticamente (Grounding DINO) o un modelo YOLO supervisado entrenado explícitamente en EPP. G-E1 validará la primera hipótesis.

## Conclusión y decisión

**P-E1a es el nuevo baseline de YOLOE para CR-01 (person + helmet).** Sustituye a Y-E1 como configuración de referencia:
- `cr01_cr02_v2_short` + `confidence_threshold=0.25`
- 71 helmets detectados, person estable, 0 fallos, ~99 ms avg / ~124 ms p95 / ~7.4 FPS.

**El chaleco (CR-02) no es viable en YOLOE-26s** con los prompts probados. No se descarta que otro vocabulario (p. ej. `"orange vest"`, `"reflective clothing"`) mejore marginalmente, pero los datos del probe indican que la mejora sería insuficiente para uso operacional.

**Próximos pasos:**

1. **G-E1** — Grounding DINO tiny sobre `dataset_v1` con los mismos prompts EPP. GDINO tiene mayor expresividad semántica y debería manejar mejor `"safety helmet"` y `"high visibility safety vest"`.
2. **Y-E2 (opcional)** — YOLOE-26s a 1280px sobre las mismas imágenes, para verificar si la resolución afecta la detección de chaleco (objetos pequeños).
3. **Comparación Y vs G** — `compare-runs` de P-E1a, P-E1b y G-E1 para decidir qué modelo continúa en la matriz experimental.
