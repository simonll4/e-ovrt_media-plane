# Estado de implementación del andamiaje de despliegue

**Actualizado:** 2026-06-24 (FP16, heartbeat dedicado, entrada tensorial y previews desde payload)

**Alcance:** plano de medios de E-OVRT-VDP; no incluye el plano de control ni reglas de riesgo.

Este documento describe el estado del código, no la arquitectura aspiracional. La decisión de
despliegue vigente está en [topologías DBE/EBE](contexto/topologias-despliegue-dbe-ebe.md).

## Resumen ejecutivo

El plano de medios tiene las cuatro combinaciones de escenario × topología implementadas. El camino
más simple sigue siendo **DBE en un host**; las capacidades EBE y dos nodos están disponibles y
validadas. `fp16` está implementado para normalización, wire y transporte de red; la única capacidad
declarada y diferida es `oak_d`.

| Combinación | Estado | Notas |
|---|---|---|
| DBE + un host | Implementada | `ImageFolderSource` y `VideoFileSource`, transporte en memoria, política determinista. |
| EBE + un host | Implementada | `RtspSource` con timestamps de pared, `bounded_freshness`, `pixel_data` en `VisualUnit`. Validado con cámara EZVIZ (1920×1080). |
| DBE + dos nodos | Implementada | `NetworkTransportAdapter` ZeroMQ: REQ/REP para datos y PUSH/PULL dedicado para liveness. CLI `run-producer`/`run-consumer`. |
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
Nodo A: BaseSource → RateGate → normalize_spatial → NetworkTransportAdapter(REP datos)
                                                              │ LAN TCP/5555
Nodo B:                                              NetworkTransportAdapter(REQ datos) → forward()
                                                              │
Nodo A:                                      PULL heartbeat ←──────── PUSH heartbeat : Nodo B
                                                   TCP/5556                 (hilo dedicado)
```

1. El productor itera la fuente y aplica `RateGate`.
2. `normalize_spatial()` decodifica imágenes o frames; fuentes vivas (RTSP) usan `pixel_data`
   directamente sin reabrir el stream. Genera `NormalizedUnit` con `ResizeTransform`.
3. El productor ofrece la unidad al canal; al terminar emite `END` mediante `close()`.
   En dos nodos, si Nodo A ya observó heartbeats de Nodo B y luego expira
   `heartbeat_timeout_ms`, el productor corta la ingesta y cierra el transporte.
4. El consumidor solicita unidades, ejecuta `BaseDetectorAdapter.forward()`, genera previews desde
   el payload normalizado, reproyecta cajas al espacio original y persiste detecciones, métricas y
   errores recuperables.

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
| `network` | Implementada | ZeroMQ REQ/REP para datos y PUSH/PULL para heartbeat; Nodo A bindea REP/PULL y Nodo B conecta REQ/PUSH. Serialización msgpack + numpy raw. |

### Normalización y adaptadores

- `NormalizedUnit` preserva `run_id`, metadata de fuente, dimensiones originales, payload,
  `PayloadFormat`, tamaño objetivo y `ResizeTransform`.
- `uint8_rgb`, `fp32` y `fp16` están implementados. FP16 se normaliza a `[0, 1]`, conserva dtype y
  shape en el wire raw, y usa raw si la configuración pide JPEG (JPEG se reserva para `uint8_rgb`).
- `MockDetectorAdapter`, Grounding DINO y YOLOE exponen `ModelInputSpec` e implementan `forward()`.
- El postproceso usa `ResizeTransform` para devolver las cajas a píxeles originales.

`prepare_model_input()` es el finalizador tensorial común de los dos adaptadores: Grounding DINO
recibe el BCHW como `pixel_values` y YOLOE lo recibe como `source`; `forward()` no crea imágenes PIL.

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
| `previews/<unit_id>.preview.jpg` | Renderizado anotado desde `NormalizedUnit.payload`, disponible para imágenes, vídeo, RTSP y Nodo B sin acceder al path fuente. |

Si no se fija `run.id`, el nombre es
`run_<timestamp>_<scenario>_<model>_<policy>`. Use `eovrt-media inspect-run runs/<run_id>` para
mostrar descriptor, métricas y procedencia.

## Límites conocidos y trabajo encaminado

| Ítem | Estado | Notas |
|---|---|---|
| OAK-D Pro PoE | Declarado/deferred | `OakDSource.__iter__` lanza `NotImplementedError`; requiere SDK y hardware DepthAI. |

## Operación y validación

La suite incluye pruebas de transporte, configuración, normalización, productor/consumidor,
trazabilidad y evaluación de percepción. La última verificación local fue:

```bash
pytest -q                 # 210 pruebas
ruff check src tests
```

La validación Docker registrada el 2026-06-24 construyó Nodo A sin Torch y Nodo B con CUDA, y
completó el stack local con 114 unidades procesadas, 0 fallidas, 193 detecciones y `cuda:0`.
El despliegue distribuido debe permitir TCP/5555 (datos) y TCP/5556 (heartbeat) desde Nodo B hacia
Nodo A.

La corrida `configs/runs/mock.yaml` usa el catálogo `demo_v2` (CHV demo v2, repo hermano
`../e-ovrt_datasets`). Requiere que el repo hermano esté presente en disco como sibling.
Para validación aislada sin el repo hermano, las pruebas de integración generan imágenes
temporales y ejercitan el flujo completo sin pesos reales (`make test`).

Para evaluar una corrida contra el BENCH:

```bash
eovrt-media evaluate --run runs/<run_id>
```

Persiste `runs/<run_id>/eval_perception.json` con AP@0.5 por clase y CR-01 recall.
Los experimentos de evaluación viven en `configs/runs/experiments/bench_v2/`.
