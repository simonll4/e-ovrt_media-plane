# Documentación del Plano de Medios

Índice de la documentación del repositorio, ordenada por propósito.

## 1. Contexto (entrada del proyecto)

Documentos de referencia que definen el alcance, la estrategia y los contratos esperados del plano de medios. Son la fuente de verdad contra la que se audita la implementación.

- [contexto/context.md](contexto/context.md) — Memoria de desarrollo: contexto, frontera arquitectónica, contratos, roadmap y acuerdos de trabajo.
- [contexto/modelos-candidatos.md](contexto/modelos-candidatos.md) — Matriz experimental candidata de modelos OVD (corridas Y-E* y G-E*).
- [contexto/referencias-modelos.md](contexto/referencias-modelos.md) — Referencias oficiales de pesos, documentación y descarga por familia de modelos.

## 2. Diseño e implementación

- [architecture.md](architecture.md) — Arquitectura del plano de medios: componentes, flujo de ejecución y responsabilidades.
- [contracts.md](contracts.md) — Contratos de datos Pydantic que fluyen por el pipeline.
- [usage.md](usage.md) — Instalación, CLI y uso de las corridas.

## 3. Decisiones (ADRs)

- [decisions/ADR-0001-repo-scope.md](decisions/ADR-0001-repo-scope.md) — Repositorio dedicado al plano de medios.
- [decisions/ADR-0002-dbe-first.md](decisions/ADR-0002-dbe-first.md) — DBE como primer escenario de implementación.
- [decisions/ADR-0003-model-adapters.md](decisions/ADR-0003-model-adapters.md) — Integración de modelos mediante adaptadores.
- [decisions/ADR-0004-config-catalogs.md](decisions/ADR-0004-config-catalogs.md) — Catálogos de configuración (modelos, datasets, prompts) y pesos por linaje.

## 4. Experimentos

Registro ordenado de la fase experimental: estrategias de prompts, modelos y combinaciones probadas, con sus configs, métricas y conclusiones.

- [experimentos/README.md](experimentos/README.md) — Flujo de trabajo experimental, dimensiones a variar, qué registrar y registro de experimentos.
- [experimentos/plantilla.md](experimentos/plantilla.md) — Plantilla de ficha por experimento.
- [../configs/runs/experiments/](../configs/runs/experiments/README.md) — Configs YAML de las corridas experimentales (convención de nombres de la matriz Y-E*/G-E*).

## 5. Relevamientos (auditorías)

Auditorías fechadas del estado de la implementación contra la documentación de contexto.

- [relevamiento/2026-06-10-relevamiento-vs-contexto.md](relevamiento/2026-06-10-relevamiento-vs-contexto.md) — Relevamiento completo del plano de medios vs. `docs/contexto/` (~95% de cumplimiento; faltantes: `run_manifest.json`, p95 en `inspect-run`).
