# BENCH Gate — Optimización de rendimiento (fp16 + warmup + numpy directo)

**Rama:** `feat/ebe-fuente-viva`  
**Fecha:** 2026-06-23  
**Contexto:** Gate obligatorio antes de merge del plan `rendimiento-media-plane` (Tasks 3–6).  
Verificar que fp16 + warmup + numpy directo (GDINO) no introduce regresión de mAP.

---

## GDINO-tiny — fp16 vs fp32

**Config fp16:** `configs/runs/local/gdino_bench_v2_val_fp16.yaml`  
**Config fp32 (baseline):** `configs/runs/experiments/bench_v2/b2_g_e1_gdino_t_val.yaml`  
**Source:** `bench_v2_val` — 114 imgs, construction_site_safety valid  
**Run fp16:** `run_20260623_042556_dbe_grounding_dino_deterministic`  
**Run fp32:** `run_20260623_042725_dbe_grounding_dino_deterministic`

| Clase     | fp32   | fp16   | Δ     |
|-----------|--------|--------|-------|
| person    | 0.362  | 0.362  | 0.000 |
| helmet    | 0.354  | 0.354  | 0.000 |
| vest      | 0.128  | 0.128  | 0.000 |
| bare_head | 0.020  | 0.020  | 0.000 |
| **mAP**   | **0.216** | **0.216** | **0** |

**Conclusión:** Sin regresión. Resultados bit-a-bit idénticos — fp16 no altera el ranking de
detecciones en este dataset. Gate pasado.

> Nota: el baseline Sprint 2 reportado (0.441) corresponde al split **test** (196 imgs), no val.
> Estos resultados son sobre val (114 imgs), dataset distinto.

---

## YOLOE-26s — fp16 vs fp32

**Config fp16:** `configs/runs/local/yoloe_bench_v2_val_fp16.yaml`  
**Config fp32 (baseline):** `configs/runs/local/yoloe_bench_v2_val.yaml`  
**Source:** `bench_v2_val` — 114 imgs  
**Run fp16:** `run_20260623_044808_dbe_yoloe_deterministic`  
**Run fp32:** `run_20260623_044855_dbe_yoloe_deterministic`

| Clase     | fp32   | fp16   | Δ     |
|-----------|--------|--------|-------|
| person    | 0.355  | 0.355  | 0.000 |
| helmet    | 0.266  | 0.266  | 0.000 |
| vest      | 0.182  | 0.182  | 0.000 |
| bare_head | 0.000  | 0.000  | 0.000 |
| **mAP**   | **0.201** | **0.201** | **0** |

114/114 procesadas, 0 fallos.

**Conclusión:** Sin regresión. Gate pasado.

---

## Bugs fp16 corregidos durante la validación

La implementación original de fp16 (Task 5) fallaba en producción. Se corrigieron dos bugs:

### Bug 1 — set_classes en modelo fp16 (commit `35c2967`)

`_ensure_classes` llama `model.set_classes()` que internamente corre el text encoder (`reprta`).
Ultralytics convierte el modelo a fp16 durante el primer `predict(half=True)`. Al cambiar clases
en la siguiente llamada, `set_classes()` falla porque `reprta` está en fp16 pero `tpe` (generado
por el text encoder CPU) llega en fp32.

**Fix:** `model.model.float()` antes de `set_classes()`, `model.model.half()` + `pe.half()` después.

### Bug 2 — process_mask en modelo fp16 (commit `5bdbeec`)

`ultralytics/utils/ops.py:503` hace `protos.float()` explícitamente:

```python
masks = (masks_in @ protos.float().view(c, -1)).view(-1, mh, mw)
```

Con inferencia en fp16, `masks_in` llega en fp16 pero `protos.float()` fuerza fp32 → mismatch.
Solo se manifiesta en imágenes **con detecciones** (las imágenes sin objetos no llaman
`process_mask`): en el BENCH val, 74/114 imágenes fallaban, 40/114 pasaban silenciosamente
con 0 detecciones.

**Fix:** monkey-patch de `ops.process_mask` aplicado en `YOLOEUltralyticsAdapter.load()` cuando
`half_precision=True`. Convierte `masks_in.float()` para que ambos operandos sean fp32 en la
multiplicación de máscaras. La inferencia principal sigue en fp16.
