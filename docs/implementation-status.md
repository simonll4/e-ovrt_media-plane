# Estado de implementación del andamiaje de despliegue

**Actualizado:** 2026-07-29 (post-Fase 1: sesión de preview en vivo, ledger de descartes,
bus media→control, pre-flight `prepare_run`, catálogos `image_size` de GDINO, prefilter
EN-2 on-device en OAK-D)

**Alcance:** plano de medios de E-OVRT-VDP; no incluye el plano de control ni reglas de riesgo.

Este documento describe el estado del código, no la arquitectura aspiracional. La decisión de
despliegue vigente está en [topologías DBE/EBE](contexto/topologias-despliegue-dbe-ebe.md).

## Fase 1 (Spec A): media-plane como servicio

Desde la Fase 1 el media-plane **ya no es un CLI**: es un **servicio FastAPI (HTTP/WS)** que
carga el modelo una vez al startup (`EOVRT_MODEL_REF`) y mantiene **una única actividad a la
vez** (un run o una sesión de preview — exclusión mutua vía `ActivitySlot`). El CLI
`eovrt-media` (Typer) fue eliminado; los utilitarios ex-subcomandos viven en
`eovrt_media.tools.*` (invocables con `python -m`): `evaluate`, `inspect_runs`, `run_node`
(entrypoint two-node para los contenedores de `infra/twonode/`), `preannotate_video` y
`videogt` (video-gt-lab). `debug_run` y la campaña `two_node_local` fueron **eliminados** el
2026-07-18 (código muerto post-CLI); las utilidades de diagnóstico de runs que siguen vivas
son `debugging/{analyzer,reporter}.py`. El pipeline descrito abajo (productor/consumidor,
transporte, normalización, adaptadores) **no cambió**: el servicio lo envuelve.
`execute_run()` recibe el adapter ya cargado y un run se dispara con `POST /api/runs`.
Contrato completo y endpoints en [usage.md](usage.md); diseño en
[docs/_archive/superpowers/specs/2026-07-01-media-plane-service-design.md](superpowers/specs/2026-07-01-media-plane-service-design.md).

El servicio ya tiene un **cliente real externo**: la **webconsole**
(`../e-ovrt_experimental-setup/webconsole/`, BFF FastAPI + SPA React) dispara y observa
corridas contra esta API (`POST /api/runs` + WS `/api/runs/{id}/stream`), sin acoplarse
al proceso del media-plane.

| Pieza del servicio | Estado | Notas |
|---|---|---|
| API de runs (`POST/GET/DELETE /api/runs`, stop) | Implementada | Un run activo; segundo `POST` → 409; `model` en el body → 422. Acepta `run.name` opcional (expuesto en `RunSummary` en vivo y terminado) y `experiment_id` (trazabilidad hacia los manifiestos del experimental-setup). |
| Carga de modelo al startup + `/api/model`, `/healthz`, `/readyz` | Implementada | Sin recarga in-process; ready-gate 503 hasta que el modelo carga. |
| WebSocket de telemetría (`/api/runs/{id}/stream`) | Implementada | Eventos `detection`/`metric`/`error`/`state`; coalescing de métricas. |
| Detections paginadas + artefactos con Range | Implementada | Anti-traversal; 404 ante paths hostiles o JSONL malformado. |
| Evaluación BENCH por HTTP (`POST`/`GET /api/runs/{id}/evaluate`) | Implementada | Evalúa un run BENCH terminado (AP@0.5 por clase, recall CR-01, mAP50); `GET` relee `eval_perception.json` persistido (404 si no evaluado). |
| Ledger de descartes (`GET /api/runs/{id}/dropped`) | Implementada | Paginado; run sin descartes → 200 vacío. Ver "Artefactos" y "Límites conocidos". |
| Sesión de preview en vivo (`POST/GET/DELETE /api/preview` + WS `/api/preview/stream`) | Implementada | `PreviewManager`: frames anotados en vivo para posicionar cámaras y probar prompts sin generar un run. Exclusión mutua run↔preview vía `ActivitySlot` (un run **o** una preview, nunca ambos → 409). El preview RTSP no acumula backlog (siempre el frame más reciente). |
| Bus media→control (ZeroMQ XPUB, ADR-003) | Implementada | Apagado por default; con `bus.enabled: true`, `BusPublishingArtifactWriter` publica cada `DetectionEvent` **ya persistido** en envelope msgpack `bus.envelope.v1` (topic `media.detection.v1.<run_id>`; cierre con `run.lifecycle.v1`). Nunca bloquea la corrida; el JSONL sigue siendo la fuente de verdad. |
| Catálogos (`/api/catalog/{ingest-plugins,datasets}`) + registro de plugins | Implementada | `image_folder`, `video_file`, `rtsp` y `oak_d` disponibles. |
| Redacción de credenciales RTSP | Implementada | URLs `rtsp://user:pass@…` redactadas en logs y artefactos. |
| Imagen GPU única (Fase 1) + healthchecks | Implementada | `infra/docker/Dockerfile`; split two-node disponible en `infra/twonode/` (Fase 2). |

El resto de este documento describe el **pipeline interno** que el servicio ejecuta, que sigue vigente.

## Resumen ejecutivo

El plano de medios tiene las cuatro combinaciones de escenario × topología implementadas. El camino
más simple sigue siendo **DBE en un host**; las capacidades EBE y dos nodos están disponibles y
validadas. `fp16` está implementado para normalización, wire y transporte de red; `oak_d`
(OAK-D Pro PoE) está implementado desde 2026-07-13 (ver
[contexto/oak-d-integration.md](contexto/oak-d-integration.md)).

| Combinación | Estado | Notas |
|---|---|---|
| DBE + un host | Implementada | `ImageFolderSource` y `VideoFileSource`, transporte en memoria, política determinista. |
| EBE + un host | Implementada | `RtspSource` con timestamps de pared, `bounded_freshness`, `pixel_data` en `VisualUnit`. Validado con cámara EZVIZ (1920×1080). |
| DBE + dos nodos | Implementada | `NetworkTransportAdapter` ZeroMQ: REQ/REP para datos y PUSH/PULL dedicado para liveness (`request_timeout_ms` corta el consumidor si el productor muere). Invocación in-process `run_node_a()`/`run_node_b()`; empaquetado Docker en `infra/twonode/` (Fase 2). |
| EBE + dos nodos | Implementada | Combina fuente viva y transporte de red. Docker: `infra/twonode/Dockerfile.node-a` (edge) + imagen `eovrt/media-plane:latest` reusada para el Nodo B (GPU). |

## Flujo implementado

**Un host (single-host):**
```
BaseSource (ImageFolderSource / VideoFileSource / RtspSource / OakDSource)
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

0. Antes de arrancar el hilo productor, `execute_run` ejecuta el pre-flight
   `adapter.prepare_run(plan)`: el binding de prompts y el autotune CUDA de la primera
   inferencia pagan su costo **antes** de que la fuente empiece a producir (sin esto se
   dropeaban hasta 50 frames por `queue_full` al inicio de una corrida viva). El default de
   `BaseDetectorAdapter` es una inferencia dummy con el plan real.
1. El productor itera la fuente y aplica `RateGate`. Las fuentes vivas (RTSP, OAK-D)
   descartan los primeros `source.warmup_frames` leídos (warm-up de lente, default 0).
2. `normalize_spatial()` decodifica imágenes o frames; fuentes vivas (RTSP, OAK-D) usan `pixel_data`
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
| Bus media→control (`transport/bus.py`) | Implementada | Socket ZeroMQ XPUB aparte del transporte de unidades; HWM finito + `NOBLOCK` (nunca bloquea la corrida). El `seq` monótono del envelope es la señal de pérdida — la detecta el consumidor. |

### Normalización y adaptadores

- `NormalizedUnit` preserva `run_id`, metadata de fuente, dimensiones originales, payload,
  `PayloadFormat`, tamaño objetivo y `ResizeTransform`.
- `uint8_rgb`, `fp32` y `fp16` están implementados. FP16 se normaliza a `[0, 1]`, conserva dtype y
  shape en el wire raw, y usa raw si la configuración pide JPEG (JPEG se reserva para `uint8_rgb`).
- `MockDetectorAdapter`, Grounding DINO y YOLOE exponen `ModelInputSpec` e implementan `forward()`.
- El postproceso usa `ResizeTransform` para devolver las cajas a píxeles originales.

`prepare_model_input()` es el finalizador tensorial común de los dos adaptadores: Grounding DINO
recibe el BCHW como `pixel_values` y YOLOE lo recibe como `source`; `forward()` no crea imágenes PIL.

- `image_size` (opcional en `ModelSection`) ajusta la resolución de letterbox del adapter
  Grounding DINO con `input_spec` y `predict` consistentes. Catálogos
  `configs/models/grounding-dino/gdino-{tiny,base}-560.yaml` (variantes 560 px de los
  existentes: −24% latencia con igual o mejor mAP que 800 px; `gdino-tiny-560` es el modelo
  campeón de la selección S1/S2).
- `prepare_run()` es parte del contrato de `BaseDetectorAdapter`: pre-flight por corrida (ver
  "Flujo implementado"); un adapter solo lo overridea si su binding no pasa por `predict()`.

### Configuración y gating

Las secciones de despliegue son `rate_control`, `transport` y `topology`.

- `source.type` deriva `source.kind` (`pulleable` o `live`).
- Una fuente pulleable deriva `policy=deterministic`; una viva deriva `bounded_freshness`.
- `topology.mode=single_host` deriva `backend=memory`; `two_node` deriva `network` (implementado).
- `sampling` fue retirado: cualquier YAML que lo contenga falla con un mensaje de migración.
- `run.max_units` reemplaza `sampling.max_units`; `rate_control.stride` reemplaza `sampling.every_n`.
- `source.warmup_frames` (`ge=0`, default 0) solo es válido en fuentes vivas; el schema lo
  rechaza en fuentes pulleables.
- `outputs.save_annotated_video` (default `false`) + `video_fps` habilitan la grabación de la
  corrida a `annotated.mp4` (ver "Artefactos"), útil para registrar tomas RTSP/OAK-D a archivo.

Los catálogos de datasets incluyen `dataset_id`, `view`, `split`, `vocabulary` y `kind` para
trazabilidad y validación de coherencia de prompts.

### Artefactos y trazabilidad

Cada corrida genera, según la configuración de outputs:

| Artefacto | Contenido |
|---|---|
| `effective_config.yaml` | Configuración resuelta, incluidos los defaults derivados. |
| `detections.jsonl` | `DetectionEvent` por unidad procesada (con `track_id` opcional por detección). |
| `metrics.jsonl` | `MetricSample` versión `media.metric.v2`, incluida latencia de normalización y la instrumentación G2A por `unit_id` (`capture_monotonic_ns`, `capture_wallclock_ms`, `g2a_ms`). |
| `errors.jsonl` | Errores recuperables por etapa. |
| `summary.json` | `media.summary.v2`, percentiles hasta p99, descartes, `run_descriptor`, `source_clock` y el bloque `g2a` (en two-node sale `not_interpretable`). |
| `dropped_units.jsonl` | Ledger por-frame de descartes con identidad completa y `reason` (`rate_gate` intencional vs `queue_full`/`staleness_timeout`/`channel_closed` por sobrecarga). Lazy: cero descartes = sin archivo. `units_dropped` del summary conserva su semántica (solo sobrecarga). |
| `annotated.mp4` | Video anotado de la corrida (`outputs.save_annotated_video`): ensambla los frames procesados en un .mp4 (mp4v; transcodificación a H.264 si hay `ffmpeg`). |
| `run_provenance.json` | Dataset, vista, split, vocabulario y SHA-256 del listado ordenado de archivos de la fuente. |
| `run_manifest.json` | Fechas, versión de código y archivos producidos. |
| `previews/<unit_id>.preview.jpg` | Renderizado anotado desde `NormalizedUnit.payload`, disponible para imágenes, vídeo, RTSP y Nodo B sin acceder al path fuente. |

Si no se fija `run.id`, el nombre es
`run_<timestamp>_<scenario>_<model>_<policy>`. Use `python -m eovrt_media.tools.inspect_runs inspect runs/<run_id>`
para mostrar descriptor, métricas y procedencia.

## Límites conocidos y trabajo encaminado

| Ítem | Estado | Notas |
|---|---|---|
| OAK-D Pro PoE | Implementada (2026-07-13) | `OakDSource` vía DepthAI v2 (extra `edge`), RGB por IP fija, reconexión, stop cooperativo, watchdog de stream mudo, knobs `resolution`/`fps`/`orientation`. Verificada E2E con hardware real. |
| Prefilter EN-2 on-device (OAK-D) | Implementada (2026-07-15) | Opcional, **default off**: red de personas corriendo en la VPU de la cámara descarta frames sin personas antes de enviarlos al host (`prefilter.enabled` + `model_blob`, fail-fast si falta el blob — `make download-prefilter-blob`). Incluye métrica de latencia captura→host. Verificado E2E real: ~87% de drop on-device. |
| Ledger de descartes en two-node | No instrumentado | `dropped_units.jsonl` es **solo single-host**: en two-node los drops ocurren en Nodo A, sin `run_dir`. `GET /dropped` vacío significa "no instrumentado", no "cero descartes". |

## Operación y validación

La suite incluye pruebas de transporte, configuración, normalización, productor/consumidor,
servicio HTTP/WS (runs, preview, bus, evaluación), ledger de descartes, instrumentación G2A,
trazabilidad y evaluación de percepción. La última verificación local fue:

```bash
pytest -q                 # 646 pruebas (conteo verificado con --collect-only, 2026-07-29)
ruff check src tests
```

La validación Docker registrada el 2026-06-24 construyó Nodo A sin Torch y Nodo B con CUDA, y
completó el stack local con 114 unidades procesadas, 0 fallidas, 193 detecciones y `cuda:0`.
El despliegue distribuido debe permitir TCP/5555 (datos) y TCP/5556 (heartbeat) desde Nodo B hacia
Nodo A.

La corrida `../e-ovrt_experimental-setup/experiments/mock.yaml` usa el catálogo `demo_v2` (CHV demo v2, repo hermano
`../e-ovrt_datasets`). Requiere que el repo hermano esté presente en disco como sibling.
Para validación aislada sin el repo hermano, las pruebas de integración generan imágenes
temporales y ejercitan el flujo completo sin pesos reales (`make test`).

Para evaluar una corrida contra el BENCH (o vía `POST /api/runs/{id}/evaluate` por HTTP):

```bash
python -m eovrt_media.tools.evaluate --run runs/<run_id> [--bench-coco ...] [--person-gt ...]
```

Persiste `runs/<run_id>/eval_perception.json` con AP@0.5 por clase, recall CR-01 y mAP50.
Por default restringe el GT a las imágenes que el run realmente procesó
(`restrict_gt_to_detections=True`, mismo default que el endpoint del servicio) — evita evaluar
contra el denominador de otro split/fuente. El bench de referencia vigente es
`../e-ovrt_datasets/datasets/processed/coco/bench/curated/bench_v3.json` (6.477 imágenes
estratificadas). Los experimentos de evaluación viven en
`../e-ovrt_experimental-setup/experiments/`.
