# Documentación del media plane

Este directorio separa la documentación operativa del media plane de su contexto y
trazabilidad de diseño. El estado vigente siempre prevalece sobre los documentos
históricos.

## Documentación operativa

| Documento | Contenido |
|---|---|
| [implementation-status.md](implementation-status.md) | **Fuente de verdad operativa**: capacidades implementadas, interfaces declaradas, límites y próximos pasos. |
| [architecture.md](architecture.md) | Arquitectura productor/consumidor, responsabilidades y frontera del repositorio. |
| [contracts.md](contracts.md) | Contratos de datos, transporte, artefactos y versiones de esquema. |
| [usage.md](usage.md) | Instalación, ejecución (single-host y dos nodos), resultados e inspección de corridas. |
| [deployment/two-node-docker.md](deployment/two-node-docker.md) | Despliegue Docker Compose para topología Nodo A (edge) + Nodo B (GPU). |

La referencia para la sintaxis de YAML es [../configs/README.md](../configs/README.md).

## Decisiones de arquitectura (ADRs)

| ADR | Decisión |
|---|---|
| [ADR-0001](decisions/ADR-0001-repo-scope.md) | Alcance del repositorio media plane |
| [ADR-0002](decisions/ADR-0002-dbe-first.md) | DBE primero (Dataset-Based Evaluation) |
| [ADR-0003](decisions/ADR-0003-model-adapters.md) | Adaptadores de modelo como plugin |
| [ADR-0004](decisions/ADR-0004-config-catalogs.md) | Config catalogs con resolución de refs |
| [ADR-0005](decisions/ADR-0005-ebe-via-rtsp.md) | EBE vía RtspSource (sin LiveSource intermedia) |

## Contexto y justificaciones

| Documento | Contenido |
|---|---|
| [contexto/diseno-arquitectonico.md](contexto/diseno-arquitectonico.md) | Diseño arquitectónico ampliado (capítulo de tesis §17.3). |
| [contexto/topologias-despliegue-dbe-ebe.md](contexto/topologias-despliegue-dbe-ebe.md) | Matriz de topologías DBE/EBE × single-host/two-node. |
| [contexto/justificacion-lenguaje-python.md](contexto/justificacion-lenguaje-python.md) | Justificación de la elección de Python. |
| [contexto/justificacion_fuentes_externas_plano_medios.md](contexto/justificacion_fuentes_externas_plano_medios.md) | Justificación de fuentes externas al plano de medios. |
| [contexto/modelos-candidatos.md](contexto/modelos-candidatos.md) | Matriz de candidatos OVD evaluados. |
| [contexto/referencias-modelos.md](contexto/referencias-modelos.md) | Referencias de checkpoints y documentación de modelos. |

## Histórico

| Ubicación | Contenido |
|---|---|
| [_archive/superpowers/](\_archive/superpowers/) | Planes y especificaciones de diseño ya implementados (andamiaje, EBE, dos nodos, RTSP, smoke). |
