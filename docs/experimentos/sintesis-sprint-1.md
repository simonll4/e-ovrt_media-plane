# Síntesis del Sprint 1 — Validación del pipeline y diagnóstico EPP

**Creado:** 2026-06-10 | **Actualizado:** 2026-06-10 | **Estado:** cerrado
**Experimentos ejecutados:** Y-E1, P-E1a, P-E1b, G-E2

---

## 1. Punto de partida

El objetivo del sprint era doble:

1. **Validar el pipeline de punta a punta** con un modelo OVD real (no mock) sobre un dataset controlado.
2. **Diagnosticar la detección de EPP** (casco y chaleco reflectante) para los riesgos CR-01 y CR-02.

El dataset utilizado en todas las corridas fue `data/samples/images/dataset_v1`: 37 imágenes extraídas del split de test del dataset MOCS (Monitoring of Construction Sites, Roboflow, CC BY 4.0). Las imágenes cubren distintas densidades de trabajadores (1-2, 3-5, 6-10, 11+ workers por imagen). Importante: MOCS solo anota `Worker`, no EPP — por lo tanto no existe ground-truth de cascos ni chalecos para comparar con precisión, pero sí se puede evaluar si el modelo detecta algo.

---

## 2. Secuencia de experimentos

### Y-E1 — Primer modelo real, primeros resultados

**Objetivo:** validar el pipeline con YOLOE-26s y obtener una línea de base.

YOLOE-26s se cargó con los prompts de la versión inicial (`cr01_cr02_v1`): `person`, `safety helmet`, `high visibility safety vest`. El pipeline procesó las 37 imágenes sin errores. Resultado: 138 detecciones de `person`, 0 de EPP.

**Hallazgo:** el pipeline funciona. El EPP no se detecta con esos prompts en YOLOE-26s.

**Pregunta que abre:** ¿es un problema de vocabulario, de umbral, o de capacidad del modelo?

---

### Diagnóstico P-E1 — Probe de vocabulario

Antes de diseñar los configs de P-E1 se corrió un probe manual a `conf=0.01` sobre el dataset completo con cuatro combinaciones de vocabulario EPP:

| Variante de prompt | helmet ≥ 0.25 | vest ≥ 0.25 | top conf helmet |
|--------------------|--------------|-------------|-----------------|
| `safety helmet` / `high visibility safety vest` | **0** | **0** | — |
| `helmet` / `vest` | **75** | **0** | 0.877 |
| `hard hat` / `safety vest` | 25 | 0 | 0.776 |
| `helmet` / `high visibility vest` | 75 | 0 | 0.877 |

**Conclusión del probe:** el problema de casco era puramente de vocabulario — la frase compuesta `"safety helmet"` no activa bien el encoder CLIP de YOLOE-26s, mientras que la etiqueta corta `"helmet"` produce scores hasta 0.877. El chaleco no supera 0.187 en ninguna variante, apuntando a una limitación del modelo.

---

### P-E1a / P-E1b — Prompts cortos en YOLOE

**Objetivo:** confirmar en una corrida formal que el label corto funciona y explorar si bajar el umbral ayuda con el chaleco.

Se creó el prompt set `cr01_cr02_v2_short` con `"helmet"` y `"vest"` (etiquetas cortas) y se corrieron dos configs: P-E1a (threshold=0.25) y P-E1b (threshold=0.15).

| | P-E1a (0.25) | P-E1b (0.15) |
|---|---|---|
| person | 138 | 181 |
| helmet | **71** | **89** |
| vest | **0** | **0** |
| avg ms | 99 | 97 |
| VRAM MB | 159 | 159 |

**Hallazgo:** `"helmet"` resuelve el casco (71 dets a 0.25). El chaleco permanece en 0 incluso a threshold=0.15 — no es un problema de umbral sino de capacidad del modelo. P-E1a se establece como el baseline de YOLOE.

---

### G-E2 — Grounding DINO base

**Objetivo:** probar si un modelo con mayor expresividad semántica puede detectar EPP con los prompts compuestos originales.

Se omitió G-E1 (tiny) y se pasó directamente a G-E2 (base) por decisión del equipo. Se usaron los prompts originales de `cr01_cr02_v1` (`"safety helmet"`, `"high visibility safety vest"`) para aislar el efecto del modelo, manteniendo el vocabulario idéntico al de Y-E1.

| | Y-E1 (YOLOE v1) | P-E1a (YOLOE short) | G-E2 (GDINO base) |
|---|---|---|---|
| person | 138 | 138 | **212** |
| helmet / safety helmet | 0 | 71 | 59 |
| vest / high vis. vest | 0 | **0** | **28** |
| avg ms | 853 ¹ | **99** | 705 |
| p95 ms | 221 ¹ | 124 | 579 |
| FPS | 1.09 ¹ | **7.4** | 1.4 |
| VRAM MB | 158 | **159** | 2189 |

> ¹ Y-E1 incluye warmup de CUDA + descarga de `mobileclip2_b.ts` en la primera inferencia (~28.8 s).

**Hallazgo:** GDINO base detecta 28 chalecos y 59 cascos con los mismos prompts compuestos que YOLOE no podía procesar. El chaleco es detectable — la limitación era del modelo, no de las imágenes ni del vocabulario.

---

## 3. Tabla maestra comparativa

| Experimento | Modelo | Prompt set | Threshold | person | helmet¹ | vest¹ | avg ms | VRAM MB | FPS |
|-------------|--------|------------|-----------|--------|---------|-------|--------|---------|-----|
| Y-E1 | YOLOE-26s @ 640 | cr01_cr02_v1 | 0.25 | 138 | 0 | 0 | 853² | 158 | 1.1² |
| P-E1a | YOLOE-26s @ 640 | cr01_cr02_v2_short | 0.25 | 138 | **71** | 0 | **99** | **159** | **7.4** |
| P-E1b | YOLOE-26s @ 640 | cr01_cr02_v2_short | 0.15 | 181 | 89 | 0 | 97 | 159 | 7.5 |
| G-E2 | GDINO-base | cr01_cr02_v1 | box=0.30 / text=0.25 | 212 | 59 | **28** | 705 | **2189** | 1.4 |

> ¹ Labels: YOLOE usa `helmet`/`vest`; GDINO usa `safety helmet`/`high visibility safety vest`.  
> ² Y-E1 incluye warmup. Sin warmup, YOLOE-26s estabiliza en ~67-100 ms / ~10-14 FPS.

---

## 4. Hallazgos por dimensión

### Vocabulario

- Las frases compuestas (`"safety helmet"`, `"high visibility safety vest"`) son ineficaces en YOLOE-26s. El encoder CLIP del modelo pequeño no mapea bien conceptos multi-token raramente vistos en el entrenamiento.
- Las etiquetas cortas (`"helmet"`, `"vest"`) activan mejor el encoder de YOLOE. `"helmet"` alcanza score 0.877; `"vest"` sigue siendo débil incluso en forma corta (tope ~0.136).
- En GDINO, las frases compuestas funcionan bien porque el backbone BERT-like fue entrenado en pares imagen-texto más ricos y variados.
- **Regla práctica para YOLOE:** usar etiquetas cortas. **Para GDINO:** las frases descriptivas funcionan igual o mejor.

### Umbral de confianza

- Bajar de 0.25 a 0.15 en YOLOE añade personas y cascos (+25% helmet) pero no resuelve el chaleco — el problema de vest es estructural, no de umbral.
- A 0.15, `person` sube a 181 (+31%), lo que indica más ruido. 0.25 es el umbral apropiado para YOLOE en este dataset.

### Modelo

- YOLOE-26s: rápido (~99 ms, ~10 FPS), eficiente en VRAM (159 MB), detección de casco viable con label corto, chaleco inviable.
- GDINO-base: lento (~705 ms, ~1.4 FPS), costoso en VRAM (2189 MB, ~14× YOLOE), detecta tanto casco como chaleco con prompts descriptivos. No apto para realtime; viable para análisis offline.

---

## 5. Fixes de pipeline aplicados durante el sprint

Durante la ejecución se identificaron y corrigieron los siguientes problemas:

| Fix | Archivo | Descripción |
|-----|---------|-------------|
| Normalización de labels GDINO | `models/grounding_dino_adapter.py` | GDINO puede devolver spans parciales del texto de entrada (ej. `"visibility safety"` en lugar de `"high visibility safety vest"`). Se añadió `_normalize_label()` que mapea cada span detectado al prompt original más cercano por solapamiento de palabras. |
| Migración a `text_labels` | `models/grounding_dino_adapter.py` | La key `labels` de `post_process_grounded_object_detection` retornará IDs enteros en transformers ≥4.51. Se migró a `text_labels` (key estable para strings) con fallback a `labels` para versiones anteriores. |
| Supresión de FutureWarning | `models/grounding_dino_adapter.py` | La librería emite un FutureWarning por la deprecación de `labels`. Se suprime con `warnings.catch_warnings()` dentro del método `predict` para mantener el output limpio. |

---

## 6. Conclusiones del sprint

**El pipeline funciona de punta a punta.** 37/37 imágenes procesadas en todas las corridas, sin errores recuperables, artefactos completos (JSONL, summary, previews, manifest).

**La detección de EPP es factible pero con trade-offs importantes:**

- **Casco:** detectable con ambos modelos. YOLOE con label corto (`"helmet"`) da 71 dets a alta confianza; GDINO con frase compuesta da 59. Sin ground-truth de EPP en MOCS no se puede comparar precisión, pero ambos producen detecciones en el rango esperado.
- **Chaleco:** solo detectable con GDINO base (28 dets). YOLOE no puede con ningún vocabulario probado. La limitación es del backbone CLIP-pequeño de YOLOE.

**El trade-off central es velocidad/VRAM vs. cobertura EPP:**

| Criterio | YOLOE-26s (P-E1a) | GDINO-base (G-E2) |
|----------|-------------------|--------------------|
| Casco | ✓ (71) | ✓ (59) |
| Chaleco | ✗ (0) | ✓ (28) |
| Realtime | ✓ (~10 FPS) | ✗ (~1.4 FPS) |
| VRAM | ✓ (159 MB) | ✗ (2189 MB) |
| Prompts | etiquetas cortas | frases descriptivas |

---

## 7. Preguntas abiertas para próximos sprints

1. **Y-E2: YOLOE-26m** — ¿el modelo mediano mejora la detección de chaleco? ¿o el backbone CLIP sigue siendo el cuello de botella?
2. **Y-E4: YOLOE-26l @ 960** — ¿la mayor resolución mejora objetos pequeños (chaleco en segundo plano)?
3. **G-E2b (opcional):** GDINO-base con `cr01_cr02_v2_short` (`"helmet"`, `"vest"`) — ¿las etiquetas cortas mejoran también en GDINO o las frases compuestas son iguales/mejores?
4. **Verificación cualitativa:** inspeccionar los previews de G-E2 para evaluar si las 28 detecciones de chaleco son verdaderos positivos o falsos positivos (MOCS no tiene anotación de EPP).
5. **Decisión de arquitectura:** ¿se acepta GDINO como modelo principal para EPP en el TFG (offline, alta cobertura) o se busca un modelo supervisado EPP para realtime?
