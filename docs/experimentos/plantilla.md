# <ID> — <título corto del experimento>

**Fecha:** YYYY-MM-DD
**Estado:** planificado | ejecutado | descartado
**Config:** `configs/runs/experiments/<archivo>.yaml`
**Run ID:** `runs/<run_id>` (completar tras la corrida)

## Hipótesis / objetivo

Qué se quiere validar o comparar, y contra qué experimento previo (si aplica).

## Configuración

| Dimensión | Valor |
|-----------|-------|
| Modelo / checkpoint | |
| Resolución de entrada | |
| Device | |
| Umbrales | |
| Prompt set | |
| Prompts activos (`active_ids`) | |
| Postproceso | |
| Fuente / muestreo | |

## Resultados cuantitativos

Tomados de `summary.json` / `inspect-run`:

| Métrica | Valor |
|---------|-------|
| Unidades procesadas | |
| Unidades fallidas | |
| Detecciones totales | |
| Latencia promedio (ms) | |
| Latencia p95 (ms) | |
| FPS efectivo | |
| VRAM máxima (MB) | |
| Errores recuperables | |

## Observaciones cualitativas

- Casco: detectado / no detectado / inestable — notas.
- Chaleco: detectado / no detectado / inestable — notas.
- Falsos positivos frecuentes:
- Sensibilidad a prompts / resolución:
- Previews revisadas: sí/no (cuáles).

## Conclusión y decisión

Qué se concluye, si la variante sigue, se ajusta o se descarta (y por qué), y qué experimento sugiere como siguiente paso.
