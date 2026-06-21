# Documentación del media plane

Este directorio separa la documentación operativa del media plane de su contexto y
trazabilidad de diseño. El estado vigente siempre prevalece sobre los documentos
históricos.

| Documento | Contenido |
|---|---|
| [implementation-status.md](implementation-status.md) | Fuente de verdad operativa: capacidades implementadas, interfaces declaradas, límites y próximos pasos. |
| [architecture.md](architecture.md) | Arquitectura productor/consumidor, responsabilidades y frontera del repositorio. |
| [contracts.md](contracts.md) | Contratos de datos, transporte, artefactos y versiones de esquema. |
| [usage.md](usage.md) | Instalación, ejecución, resultados e inspección de corridas. |
| [contexto/topologias-despliegue-dbe-ebe.md](contexto/topologias-despliegue-dbe-ebe.md) | Decisiones de despliegue DBE/EBE y matriz de disponibilidad. |
| [decisions/](decisions/) | ADRs vigentes sobre alcance, DBE, adaptadores y catálogos. |

La referencia para la sintaxis de YAML es [../configs/README.md](../configs/README.md).

## Contexto y trazabilidad histórica

Estos documentos se conservan para entender decisiones y planes anteriores; pueden
describir capacidades que aún no existen o una arquitectura anterior al refactor
productor/consumidor. Para el estado implementado, consultar primero
`implementation-status.md`.

| Ubicación | Contenido |
|---|---|
| [contexto/](contexto/) | Diseño arquitectónico ampliado, justificaciones y referencias de modelos. |
| [superpowers/](superpowers/) | Kickoff, especificación y planes que guiaron el andamiaje de despliegue. |
