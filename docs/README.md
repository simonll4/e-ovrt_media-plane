# Documentación — e-ovrt_media-plane

Índice de la documentación del repositorio, ordenada por propósito.

---

## 1. Contexto (entrada del proyecto)

Documentos de referencia que definen el alcance, la estrategia y los contratos esperados del plano de medios. Son la fuente de verdad contra la que se audita la implementación.

| Documento | Contenido |
|---|---|
| [contexto/diseno-arquitectonico.md](contexto/diseno-arquitectonico.md) | Diseño arquitectónico completo de E-OVRT-VDP Etapa 3: bloques lógicos, contratos, escenarios DBE/EBE, patrones de riesgo CR-01 a CR-06, métricas, eventos y trazabilidad. |
| [contexto/modelos-candidatos.md](contexto/modelos-candidatos.md) | Matriz experimental candidata de modelos OVD (corridas Y-E* y G-E*) y criterios de comparación. |
| [contexto/referencias-modelos.md](contexto/referencias-modelos.md) | Referencias oficiales de pesos, documentación y descarga por familia de modelos (YOLOE, GDINO, MM-GDINO). |

## 2. Diseño e implementación

| Documento | Contenido |
|---|---|
| [architecture.md](architecture.md) | Arquitectura del plano de medios: componentes, flujo de ejecución y responsabilidades. |
| [contracts.md](contracts.md) | Contratos de datos Pydantic que fluyen por el pipeline (`VisualUnit`, `Detection`, `DetectionEvent`, etc.). |
| [usage.md](usage.md) | Instalación, CLI, descarga de modelos y ejemplos de corridas. |

## 3. Decisiones (ADRs)

| Documento | Contenido |
|---|---|
| [decisions/ADR-0001-repo-scope.md](decisions/ADR-0001-repo-scope.md) | Repositorio dedicado al plano de medios. |
| [decisions/ADR-0002-dbe-first.md](decisions/ADR-0002-dbe-first.md) | DBE como primer escenario de implementación. |
| [decisions/ADR-0003-model-adapters.md](decisions/ADR-0003-model-adapters.md) | Integración de modelos mediante adaptadores. |
| [decisions/ADR-0004-config-catalogs.md](decisions/ADR-0004-config-catalogs.md) | Catálogos de configuración (modelos, datasets, prompts) y pesos por linaje. |

## 4. Experimentos

Registro ordenado de la fase experimental: modelos, prompts y combinaciones probadas, con configs, métricas y conclusiones.

| Documento | Contenido |
|---|---|
| [experimentos/README.md](experimentos/README.md) | Flujo de trabajo, dimensiones a variar, qué registrar y registro completo de corridas por sprint. |
| [experimentos/sintesis-sprint-1.md](experimentos/sintesis-sprint-1.md) | Síntesis Sprint 1: validación del pipeline, diagnóstico EPP, YOLOE-26s vs GDINO-base. |
| [experimentos/b2-sprint2-bench-v2.md](experimentos/b2-sprint2-bench-v2.md) | Sprint 2: evaluación cuantitativa BENCH v2 (196 imgs, 5 modelos, AP@50 y CR-01 recall). |
| [experimentos/plantilla.md](experimentos/plantilla.md) | Plantilla de ficha por experimento individual. |
| [../configs/runs/experiments/](../configs/runs/experiments/) | Configs YAML de todas las corridas experimentales. |

## 5. Relevamientos

| Documento | Contenido |
|---|---|
| [relevamiento/2026-06-10-relevamiento-vs-contexto.md](relevamiento/2026-06-10-relevamiento-vs-contexto.md) | Auditoría del plano de medios vs. documentos de contexto (~95 % de cumplimiento). |
| [relevamiento/2026-06-11-datasets-video-construccion.md](relevamiento/2026-06-11-datasets-video-construccion.md) | Relevamiento de fuentes de video de construcción para CR-01/CR-02 (DEMO y evaluación pipeline). |
