# Estado de implementación del andamiaje de despliegue

**Actualizado:** 2026-06-21  
**Alcance:** plano de medios de E-OVRT-VDP; no incluye el plano de control ni reglas de riesgo.

Este documento describe el estado del código, no la arquitectura aspiracional. La decisión de
despliegue vigente está en [topologías DBE/EBE](contexto/topologias-despliegue-dbe-ebe.md).

## Resumen ejecutivo

El camino operativo es **DBE en un host**. La ejecución está desacoplada en un productor y un
consumidor, conectados mediante `TransportAdapter` con backend `memory`. El sistema ya registra
configuración efectiva, artefactos versionados, descriptor de despliegue y procedencia de la fuente.

Las capacidades de EBE, IPC y red no se simulan: sus interfaces y validaciones existen, pero una
configuración que las solicite termina con un error explícito antes de ejecutar una corrida.

| Combinación | Estado | Motivo / condición restante |
|---|---|---|
| DBE + un host | Implementada | `ImageFolderSource` y `VideoFileSource`, transporte en memoria y política determinista. |
| EBE + un host | Declarada | Falta una implementación concreta de `LiveSource` para cámara o RTSP. |
| DBE + dos nodos | Declarada | Falta `NetworkTransportAdapter` y su protocolo/serialización. |
| EBE + dos nodos | Declarada | Requiere fuente viva y transporte de red. |

## Flujo implementado

```
BaseSource                         TransportAdapter                    consumidor (main)
ImageFolderSource / VideoFileSource       memory
         │                                    │                                │
         ▼                                    ▼                                ▼
VisualUnit → RateGate → normalize_spatial → NormalizedUnit → forward() → postproceso → sinks
              (productor, hilo)              END                          DetectionEvent
```

1. El productor itera la fuente y aplica `RateGate`.
2. `normalize_spatial()` decodifica imágenes o frames de vídeo, asegura RGB, aplica resize/letterbox
   y genera un `NormalizedUnit` con su `ResizeTransform`.
3. El productor ofrece la unidad al canal y, al terminar, emite `END` mediante `close()`.
4. El consumidor solicita unidades, ejecuta `BaseDetectorAdapter.forward()`, reproyecta cajas al
   espacio original y persiste detecciones, métricas y errores recuperables.

El consumidor corre en el hilo principal y el productor en `pipeline-producer`. El apagado drena el
canal hasta `END`; los errores de normalización o de fuente se escriben en `errors.jsonl` sin abortar
las unidades siguientes.

## Capacidades implementadas

### Transporte y rate control

| Pieza | Estado | Comportamiento |
|---|---|---|
| `memory` + `deterministic` | Implementada | Cola FIFO acotada y backpressure bloqueante; `stride` selecciona unidades reproduciblemente. |
| `memory` + `bounded_freshness` | Implementada | Buffer acotado con head-drop del elemento más antiguo y contador `units_dropped`. |
| `RateGate` | Implementada | `stride >= 1`; se aplica antes de normalizar. |
| `ipc` | Declarada, bloqueada | `IpcTransportAdapter` existe y lanza `NotImplementedError`. |
| `network` | Declarada, bloqueada | `NetworkTransportAdapter` y contratos REQUEST/RESPONSE/HEARTBEAT existen; el backend no. |

### Normalización y adaptadores

- `NormalizedUnit` preserva `run_id`, metadata de fuente, dimensiones originales, payload,
  `PayloadFormat`, tamaño objetivo y `ResizeTransform`.
- `uint8_rgb` y `fp32` están implementados. `fp16` es un valor válido de configuración, pero está
  bloqueado explícitamente hasta implementar el transporte de red.
- `MockDetectorAdapter`, Grounding DINO y YOLOE exponen `ModelInputSpec` e implementan `forward()`.
- El postproceso usa `ResizeTransform` para devolver las cajas a píxeles originales.

`prepare_model_input()` está disponible y probado como finalizador tensorial común. Los adaptadores
de framework aún convierten el payload a PIL y delegan la preparación final a sus procesadores
existentes; conectar ese helper directamente a cada backend es una optimización pendiente, no un
requisito del flujo DBE actual.

### Configuración y gating

Las secciones de despliegue son `rate_control`, `transport` y `topology`.

- `source.type` deriva `source.kind` (`pulleable` o `live`).
- Una fuente pulleable deriva `policy=deterministic`; una viva deriva `bounded_freshness`.
- `topology.mode=single_host` deriva `backend=memory`; `two_node` deriva `network` y queda bloqueado.
- `sampling` fue retirado: cualquier YAML que lo contenga falla con un mensaje de migración.
- `run.max_units` reemplaza `sampling.max_units`; `rate_control.stride` reemplaza `sampling.every_n`.

Los catálogos de datasets incluyen `dataset_id`, `view`, `split`, `vocabulary` y `kind` para
trazabilidad y validación de coherencia de prompts.

### Artefactos y trazabilidad

Cada corrida genera, según la configuración de outputs:

| Artefacto | Contenido |
|---|---|
| `effective_config.yaml` | Configuración resuelta, incluidos los defaults derivados. |
| `detections.jsonl` | `DetectionEvent` por unidad procesada. |
| `metrics.jsonl` | `MetricSample` versión `media.metric.v2`, incluida latencia de normalización. |
| `errors.jsonl` | Errores recuperables por etapa. |
| `summary.json` | `media.summary.v2`, percentiles hasta p99, descartes y `run_descriptor`. |
| `run_provenance.json` | Dataset, vista, split, vocabulario y SHA-256 del listado ordenado de archivos de la fuente. |
| `run_manifest.json` | Fechas, versión de código y archivos producidos. |

Si no se fija `run.id`, el nombre es
`run_<timestamp>_<scenario>_<model>_<policy>`. Use `eovrt-media inspect-run runs/<run_id>` para
mostrar descriptor, métricas y procedencia.

## Límites conocidos y trabajo encaminado

| Pendiente | Costura ya disponible | Siguiente implementación concreta |
|---|---|---|
| Cámara / RTSP | `LiveSource`, `source.kind=live`, `bounded_freshness` | Implementar captura y timestamps de pared. |
| IPC local | `IpcTransportAdapter`, factory y config | Ring buffer en memoria compartida. |
| Dos nodos | `NetworkTransportAdapter`, contratos de red y gating de topología | Serialización de `NormalizedUnit`, REQUEST/RESPONSE/HEARTBEAT y reconexión. |
| FP16 | `PayloadFormat.FP16` y gating | Conversión y transporte de media precisión. |
| Métrica de staleness observada | Campo en `RunContext` y `summary.json` | Medir edad con timestamps de captura de una fuente viva. |
| Previews anotadas | Directorio `previews/` y contrato de detecciones | Conservar una referencia renderizable de origen en `NormalizedUnit` o renderizar desde payload. |
| Preparación tensorial compartida | `prepare_model_input()` | Adaptar GDINO/YOLOE para consumirla directamente cuando se valide paridad por backend. |

## Operación y validación

La suite incluye pruebas de transporte, configuración, normalización, productor/consumidor y
trazabilidad. La última verificación local fue:

```bash
pytest -q                 # 114 pruebas
ruff check src tests
```

La corrida `configs/runs/mock.yaml` requiere que exista la fuente del catálogo `dataset_v1`
(`data/samples/images/dataset_v1`). En un checkout sin esas imágenes, el CLI falla al inicio con
`FileNotFoundError`; esto es una condición de datos, no una degradación silenciosa del pipeline.
Para validación aislada, las pruebas de integración generan imágenes temporales y ejercitan el flujo
completo sin pesos reales.
