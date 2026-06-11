# dataset_v1 — Mini-dataset inicial de test del pipeline

**Fecha de creación:** 2026-06-10
**Total de imágenes:** 37
**Propósito:** primer instrumento de evaluación del pipeline OVD para CR-01 y CR-02.

## Origen

| Campo | Valor |
|-------|-------|
| Fuente | MOCS (Monitoring of Construction Sites) |
| Proveedor | Roboflow Universe — `roboflow.com/mocs/mocs-bowib` |
| Split de origen | `test` (nunca usado en training) |
| Licencia | **CC BY 4.0** |
| Anotaciones originales | bounding boxes de `Worker` (persona) en formato COCO |

**Nota sobre las anotaciones MOCS:** el dataset etiqueta solo `Worker` (persona). No hay labels de casco ni chaleco. Las imágenes son de obras reales por lo que los workers pueden o no portar EPP — eso es exactamente lo que el pipeline va a explorar con prompts.

## Criterio de selección

Selección reproducible (seed=42) del split `test` de MOCS, estratificada por densidad de workers anotados:

| Grupo | Workers por imagen | Cantidad seleccionada | Uso previsto |
|-------|-------------------|-----------------------|-------------|
| Bajo  | 1–2               | 10                    | casos fáciles, personas aisladas |
| Medio | 3–5               | 10                    | escenas de densidad típica |
| Alto  | 6–10              | 6                     | oclusión parcial, grupos |
| Muy alto | 11+            | 11                    | escenas densas, stress test |

## Convención de nombres

```
<workers_anotados>w_<número_original>.jpg
```

Ejemplo: `06w_0020503.jpg` = imagen original `0020503_jpg.rf...jpg` con 6 workers anotados.

## Regla de congelamiento

**Este set es inmutable una vez usado en una corrida registrada.** Si se necesita un set diferente, crear `dataset_v2/` con su propio README. No agregar ni quitar imágenes de este directorio sin versionar el cambio.

El manifiesto completo de origen de cada imagen está en `selection_manifest.json`.

## Cómo usarlo en una corrida

Referenciar su entrada del catálogo de datasets en la run config:

```yaml
source:
  ref: dataset_v1    # → configs/datasets/dataset_v1.yaml
```

## Dimensiones y resoluciones

Las imágenes provienen de distintas cámaras de obra; la resolución más frecuente en el dataset original es 1200×900. El pipeline normaliza bounding boxes independientemente de la resolución.

## Implicaciones para los experimentos

- La **detección de personas** (`person`) debería funcionar bien en la mayoría de imágenes del grupo bajo y medio.
- Los grupos alto y muy alto permiten evaluar comportamiento con oclusión y figuras pequeñas.
- La **detección de EPP** (`safety helmet`, `high visibility safety vest`) depende del modelo y los prompts — no hay ground truth para EPP en este set. Las primeras corridas serán cualitativas (revisar previews).
- Para evaluación cuantitativa de EPP se necesitará un dataset con anotaciones de casco/chaleco.
