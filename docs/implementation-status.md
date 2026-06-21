# Estado de implementación del andamiaje de despliegue

**Actualizado:** 2026-06-21 (EBE + dos nodos implementados, validado E2E con cámara EZVIZ)  
**Alcance:** plano de medios de E-OVRT-VDP; no incluye el plano de control ni reglas de riesgo.

Este documento describe el estado del código, no la arquitectura aspiracional. La decisión de
despliegue vigente está en [topologías DBE/EBE](contexto/topologias-despliegue-dbe-ebe.md).

## Resumen ejecutivo

El plano de medios tiene las cuatro combinaciones de escenario × topología implementadas. El camino
más simple sigue siendo **DBE en un host**; las capacidades EBE y dos nodos están disponibles y
validadas. `fp16` y `oak_d` están declarados pero no implementados: una configuración que los solicite
termina con un error explícito.

| Combinación | Estado | Notas |
|---|---|---|
| DBE + un host | Implementada | `ImageFolderSource` y `VideoFileSource`, transporte en memoria, política determinista. |
| EBE + un host | Implementada | `RtspSource` con timestamps de pared, `bounded_freshness`, `pixel_data` en `VisualUnit`. Validado con cámara EZVIZ (1920×1080). |
| DBE + dos nodos | Implementada | `NetworkTransportAdapter` ZeroMQ REQ/REP, serialización msgpack, heartbeat. CLI `run-producer`/`run-consumer`. |
| EBE + dos nodos | Implementada | Combina fuente viva y transporte de red. Docker: `Dockerfile.node-a` (edge) + `Dockerfile.node-b` (CUDA). |

## Flujo implementado

**Un host (single-host):**
```
BaseSource (ImageFolderSource / VideoFileSource / RtspSource)
         │
         ▼  VisualUnit (+ pixel_data para fuentes vivas)
RateGate → normalize_spatial → NormalizedUnit
              (hilo productor)        │
                              MemoryTransportAdapter (memory)
                                      │
                              forward() → postproceso → sinks
                              (hilo consumidor)    DetectionEvent
```

**Dos nodos (two-node, network):**
```
Nodo A: BaseSource → RateGate → normalize_spatial → MemoryTransportAdapter(buffer)
                                                              │
                                                     NetworkTransportAdapter(REP, ZeroMQ)
                                                              │ LAN
                                                     NetworkTransportAdapter(REQ, ZeroMQ)
                                                              │
Nodo B:                                              forward() → postproceso → sinks
```

1. El productor itera la fuente y aplica `RateGate`.
2. `normalize_spatial()` decodifica imágenes o frames; fuentes vivas (RTSP) usan `pixel_data`
   directamente sin reabrir el stream. Genera `NormalizedUnit` con `ResizeTransform`.
3. El productor ofrece la unidad al canal; al terminar emite `END` mediante `close()`.
4. El consumidor solicita unidades, ejecuta `BaseDetectorAdapter.forward()`, reproyecta cajas al
   espacio original y persiste detecciones, métricas y errores recuperables.

En single-host el consumidor corre en el hilo principal y el productor en `pipeline-producer`. En
two-node, `run_node_a` y `run_node_b` son procesos separados (o contenedores Docker distintos).
El apagado drena el canal hasta `END`; los errores se escriben en `errors.jsonl` sin abortar las
unidades siguientes.

## Capacidades implementadas

### Transporte y rate control

| Pieza | Estado | Comportamiento |
|---|---|---|
| `memory` + `deterministic` | Implementada | Cola FIFO acotada y backpressure bloqueante; `stride` selecciona unidades reproduciblemente. |
| `memory` + `bounded_freshness` | Implementada | Buffer acotado con head-drop del elemento más antiguo y contador `units_dropped`. |
| `RateGate` | Implementada | `stride >= 1`; se aplica antes de normalizar. |
| `ipc` | Eliminado | Caso de uso cubierto por `network` con endpoint `ipc://`. |
| `network` | Implementada | ZeroMQ REQ/REP; Nodo A bind REP, Nodo B connect REQ; serialización msgpack + numpy raw; heartbeat via actividad de requests. |

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
- `topology.mode=single_host` deriva `backend=memory`; `two_node` deriva `network` (implementado).
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

| Ítem | Estado | Notas |
|---|---|---|
| Cámara / RTSP | **Implementado** | `RtspSource`, timestamps de pared, `pixel_data`, reconexión con backoff. |
| Dos nodos | **Implementado** | `NetworkTransportAdapter` ZeroMQ, serialización msgpack, heartbeat, CLI `run-producer`/`run-consumer`. |
| Métricas de staleness | **Implementado** | `max_staleness_observed_ms` y `units_dropped` en `summary.json`. |
| OAK-D Pro PoE | Declarado/deferred | `OakDSource.__iter__` lanza `NotImplementedError`; requiere SDK DepthAI. |
| IPC local | Eliminado | Cubierto por `network` con endpoint `ipc://` (ZeroMQ soporta Unix sockets). |
| FP16 | Declarado/deferred | `PayloadFormat.FP16` existe; conversión y transporte pendientes. |
| Previews de video | Parcial | Implementadas para `ImageFolderSource`; frames de video/RTSP sin renderizado anotado. |
| Preparación tensorial compartida | Pendiente | `prepare_model_input()` disponible pero GDINO/YOLOE aún convierten a PIL internamente. |
| Heartbeat PUSH/PULL dedicado | Pendiente | Actualmente se infiere del patrón de requests; un socket separado daría mayor precisión. |
| Edge sin torch | Pendiente | Nodo A importa torch al resolver `input_spec`; optimizable para imágenes sin GPU. |

## Operación y validación

La suite incluye pruebas de transporte, configuración, normalización, productor/consumidor y
trazabilidad. La última verificación local fue:

```bash
pytest -q                 # 151 pruebas
ruff check src tests
```

La corrida `configs/runs/mock.yaml` usa el catálogo `demo_v2` (CHV demo v2, repo hermano
`../e-ovrt_datasets`). Requiere que el repo hermano esté presente en disco como sibling.
Para validación aislada sin el repo hermano, las pruebas de integración generan imágenes
temporales y ejercitan el flujo completo sin pesos reales (`make test`).
