# ADR-0004 — Catálogos de configuración y organización de pesos

- **Estado**: aceptada
- **Fecha**: 2026-06-11

## Contexto

Tras el Sprint 1 experimental, cada run config duplicaba la definición
completa de modelo, dataset y umbrales (~45 líneas por experimento, donde solo
2-3 valores cambiaban entre corridas). Los pesos convivían sin distinción de
linaje (`models/yoloe/yoloe-26s-seg.pt`), sin lugar previsto para los
checkpoints finetuneados que vendrán, y sin un inventario único de qué
variantes existen. Las configs además apuntaban a rutas de dataset
desactualizadas (`data/samples/dataset_v1` en lugar de
`data/samples/images/dataset_v1`).

## Decisión

1. **Catálogos tipados por referencia** bajo `configs/`:
   - `configs/models/<familia>/<variante>.yaml` — una entrada por peso
     concreto, con `family`, `variant`, `lineage` (`original`|`finetuned`),
     `adapter`, ruta de pesos y umbrales por defecto.
   - `configs/datasets/<nombre>.yaml` — fuentes catalogadas.
   - `configs/prompts/<nombre>.yaml` — prompt sets versionados (ya existía).
2. **Run configs compuestas** en `configs/runs/` (experimentos en
   `configs/runs/experiments/`): referencian catálogos vía `model.ref`,
   `source.ref` y `prompts.ref`, declarando solo los overrides bajo prueba.
   El loader (`config/loader.py`) mezcla catálogo + overrides sobre el dict
   crudo antes de validar con Pydantic; el formato inline completo sigue
   siendo válido.
3. **Pesos por linaje**: `models/<familia>/original/` para pesos del
   proveedor y `models/<familia>/finetuned/<tag>/` para checkpoints propios,
   con entrada de catálogo `<variante>-ft-<tag>.yaml`.

Se descartó un mecanismo genérico de herencia (`extends:` + deep-merge):
más flexible, pero las configs efectivas dejan de leerse de un vistazo y no
produce catálogos navegables como artefacto.

## Consecuencias

- Alta de un peso nuevo = carpeta de pesos + 1 YAML de catálogo; alta de un
  experimento = run config de ~15 líneas con solo las dimensiones bajo prueba.
- La config efectiva resuelta (con provenance `ref`/`family`/`lineage`) queda
  registrada en los artefactos de cada run, preservando reproducibilidad.
- Las configs del Sprint 1 fueron migradas al esquema nuevo conservando sus
  valores efectivos y `run.name`; los runs históricos conservan su copia de
  config original en `runs/<run_id>/`.
