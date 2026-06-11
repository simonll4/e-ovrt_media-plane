# Y-E1 — YOLOE-26s @ 640, baseline realtime en GPU

**Creado:** 2026-06-10 | **Actualizado:** 2026-06-10 | **Estado:** ejecutado
**Config:** `configs/runs/experiments/y_e1_yoloe_26s_640.yaml`
**Run ID:** `runs/run_20260610_043437_y_e1_yoloe_26s_640`

## Hipótesis / objetivo

Primera corrida con un modelo OVD real sobre el dataset inicial. Objetivo: validar que el pipeline funciona de punta a punta con YOLOE-26s en GPU y obtener una línea de base de detección para los prompts de CR-01 y CR-02 (`person`, `safety helmet`, `high visibility safety vest`).

Primera corrida, sin comparación previa.

## Configuración

| Dimensión | Valor |
|-----------|-------|
| Modelo / checkpoint | `yoloe-26s-seg.pt` |
| Resolución de entrada | 640 |
| Device | `cuda` (RTX 4060 Laptop GPU) |
| `confidence_threshold` | 0.25 |
| `iou_threshold` | 0.50 |
| Prompt set | `cr01_cr02_v1` |
| Prompts activos (`active_ids`) | `person`, `safety helmet`, `high visibility safety vest` |
| `min_confidence` postprocess | 0.25 |
| `min_box_area_px` | 100 px² |
| Fuente / muestreo | `dataset_v1` — 37 imágenes, mode=all |

## Resultados cuantitativos

| Métrica | Valor |
|---------|-------|
| Unidades procesadas | 37 / 37 |
| Unidades fallidas | 0 |
| Detecciones totales | 138 |
| — person | 138 |
| — safety helmet | 0 |
| — high visibility safety vest | 0 |
| Imágenes sin ninguna detección | 3 / 37 |
| Latencia promedio (ms) | 853.4 ← **dominada por warmup** |
| Latencia p95 (ms) | 220.6 |
| Latencia promedio frames 2-37 (ms) | ~67.5 ms inferencia |
| FPS efectivo (corrida completa) | 1.09 ← incluye warmup |
| FPS inferencia estacionaria (estimado) | ~14 FPS |
| VRAM pico | 157.7 MB |
| Errores recuperables | 0 |

> **Nota sobre latencias:** la primera inferencia tomó 28.8 s (descarga y compilación de `mobileclip2_b.ts` + warmup de CUDA). Las inferencias 2-37 promediaron 67.5 ms (~14 FPS). El avg y FPS efectivo de la corrida incluyen ese warmup y no son comparables directamente con corridas posteriores donde el modelo ya está warm. Para comparar modelos hay que excluir la primera unidad o pre-calentar antes de medir.

## Observaciones cualitativas

- **Person:** detectado en 34/37 imágenes. Conteo por imagen correlaciona razonablemente con los workers anotados en MOCS (máximo 13 detecciones en la imagen con 36 workers — subestimación esperable en escenas muy densas).
- **Safety helmet:** **0 detecciones** en todo el dataset.
- **High visibility safety vest:** **0 detecciones** en todo el dataset.
- Las 3 imágenes sin detecciones pertenecen a los grupos de baja densidad (1-2 workers); posiblemente trabajadores en segundo plano, pequeños o con oclusión.
- Previews generadas: 17/37 (las que superaron el umbral de confianza y tuvieron detecciones, dentro del límite `preview_max=20`).

## Análisis del problema EPP

YOLOE no detectó ningún casco ni chaleco. Posibles causas (no excluyentes):

1. **Naturaleza del modelo:** YOLOE-26s usa CLIP como encoder de texto. El mapeo entre los textos `"safety helmet"` y `"high visibility safety vest"` y las características visuales del dataset puede ser débil en el backbone pequeño (26s).
2. **Confianza demasiado alta:** con threshold=0.25, las detecciones de EPP podrían estar por debajo del umbral. Las anotaciones de MOCS no incluyen EPP, así que no podemos saber si los workers los llevan puestos o no.
3. **Resolución:** a 640px, los objetos pequeños (casco, chaleco en segundo plano) pueden quedar por debajo del área mínima de detección.
4. **Prompts:** la redacción exacta puede influir. `"safety helmet"` vs `"hard hat"` vs `"construction helmet"` puede tener diferente activación en CLIP.

## Conclusión y decisión

**La corrida valida el pipeline:** 37/37 imágenes procesadas sin errores, artefactos completos, VRAM mínima (158 MB), inferencia GPU estacionaria ~14 FPS.

**El resultado EPP es el hallazgo clave de esta primera corrida.** YOLOE-26s detecta personas pero no EPP con los prompts actuales y threshold=0.25.

**Próximos pasos sugeridos (en orden):**

1. **P-E1** — Experimentar con variantes de prompts de EPP: `"hard hat"`, `"helmet"`, `"yellow vest"`, `"reflective vest"`, con threshold bajado a 0.10-0.15, para diagnosticar si es un problema de vocabulario o de capacidad del modelo.
2. **G-E1** — Correr Grounding DINO tiny sobre el mismo dataset para comparar: GDINO debería tener mejor expresividad semántica para EPP.
3. **Y-E1b** — Rerun de Y-E1 con `save_previews=true` y `preview_max=37` para inspeccionar visualmente la totalidad de las imágenes con los bounding boxes de `person` marcados.
4. Después de P-E1 y G-E1, comparar `compare-runs` para tener la tabla completa.

> Para el warmup: en experimentos futuros considerar agregar un flag `warmup_frames` o pre-calentar pasando la primera imagen antes del loop medido, para que las latencias sean comparables entre corridas.
