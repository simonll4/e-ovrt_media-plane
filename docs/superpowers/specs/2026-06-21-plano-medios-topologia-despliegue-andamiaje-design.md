# Diseño — Andamiaje de despliegue del plano de medios (topologías DBE/EBE)

- **Fecha**: 2026-06-21
- **Repo**: `e-ovrt_media-plane`
- **Documento base**: `docs/contexto/topologias-despliegue-dbe-ebe.md`
- **Estado**: diseño aprobado, pendiente de plan de implementación

## 1. Contexto y objetivo

El documento de topologías define el despliegue del plano de medios sobre dos dimensiones
ortogonales (escenario DBE/EBE × topología un host/dos nodos) y una variable raíz: fuente
**pulleable** (archivos, se puede frenar) vs **viva** (cámara, no se puede frenar). De ahí derivan
las dos políticas de rate control (`deterministic` / `bounded_freshness`), la noción de transporte
como adaptador con tres backends posibles (memoria / IPC / red), el punto de corte para dos nodos
(después de la normalización) y la representación física configurable del payload.

El pipeline actual es **DBE, un host, síncrono**: un loop por unidad
(`read → preprocess → inference → postprocess → write`) sin rate control, sin desacople
productor/consumidor, con la normalización implícita dentro de cada adapter.

Este trabajo **reorganiza el plano de medios para que el código mapee 1:1 con las etapas del
documento** y deja todas las costuras de despliegue listas, implementando de verdad solo el camino
prioritario (un host + DBE), y dejando EBE/dos nodos como **interfaces declaradas pero no
implementadas**.

### Objetivos

1. Cumplir la especificación de despliegue (etapas, políticas, punto de corte, transporte).
2. Que cada run sea **fácil de configurar** (el caso común casi sin config gracias a derivación).
3. Mantener **trazabilidad** completa y reproducible por los ejes del documento.
4. **Alimentar al futuro módulo de métricas** vía artefactos versionados (módulo aún no desarrollado).

### No-objetivos (diferidos, aditivos, sin retrabajo)

- Backend de red (ZeroMQ) y protocolo de dos nodos.
- Backend IPC (shared-memory).
- Fuente viva real (cámara / RTSP).
- `payload_format: fp16` y serialización byte-level sobre el cable.
- Módulo de métricas en sí (solo se fija su contrato de entrada) y el comparador `compare-runs`.
- Reglas de riesgo, alertas, tracking, zonas, plano de control, UI (fuera del alcance del plano).

## 2. Decisiones tomadas (log)

| # | Decisión | Justificación |
|---|---|---|
| D1 | **Altitud = andamiaje conceptual**: código 1:1 con el doc, secciones de config como contratos, implementar de verdad solo un host + DBE + `deterministic`. | Cumplir el doc sin pagar la complejidad de EBE/dos nodos hoy. |
| D2 | **Blanco = arquitectura final en las costuras, backends diferidos.** Costuras reales (desacople productor/consumidor, interfaz `TransportAdapter`, ambas políticas de rate control, normalización como etapa); diferir backend red/IPC, fuente viva, fp16. | Evitar el retrabajo de retrofitear concurrencia. Los backends diferidos son estrictamente aditivos. |
| D3 | **Alcance = media-plane + interfaz con datasets + interfaz cámara/streaming declarada.** | Pedido del usuario. |
| D4 | **Modelo de config derivado de `source.kind`** (pulleable/live); `scenario` DBE/EBE pasa a etiqueta de trazabilidad. | El doc dice que el default de política depende del tipo de fuente, no es global, y que pulleable/viva no coincide exactamente con DBE/EBE. |
| D5 | **Métricas = artefactos versionados** (no sink en vivo). | Desacoplado, encaja con DBE batch, barato de mantener; el módulo futuro los lee offline. |
| D6 | **Transporte un host = cola en memoria cero-copia** (2 hilos, paso por referencia, sin serialización). | Lo más rápido posible dentro de un proceso. |
| D7 | **Transporte dos hosts = ZeroMQ REQ/REP** + heartbeat ZMTP (variante robusta Lazy Pirate / DEALER-ROUTER al implementar). | Barrido profundo de alternativas: a esta escala (1 cámara, ~5 fps, 1.2 MB uint8, LAN gigabit, GPU ~200 ms/frame domina) el transporte no es el cuello; ZMQ da pull model 1:1, framing y heartbeat gratis, y es más seguro ante Nagle que TCP crudo. Nada mejora a ZMQ en este perfil. |

## 3. Arquitectura — componentes y concurrencia

El pipeline pasa de un loop síncrono a **dos roles desacoplados por un canal**, que es la costura
que el documento declara invariante entre topologías.

```
PRODUCTOR (hilo)                          CANAL                 CONSUMIDOR (hilo principal)
─────────────────────────────────        ───────────────       ───────────────────────────
IngestionAdapter  (BaseSource)            FrameChannel          channel.request() → NormalizedUnit
   │ VisualUnit                           (TransportAdapter)         │
   ▼                                       backend=memory            ▼
RateGate (stride, solo deterministic)      disciplina = policy   OVD Inference (adapter.forward)
   │ VisualUnit (gated)                     ├ deterministic:          │ RawDetection[] (espacio modelo)
   ▼                                        │   put bloquea (backpressure)
Normalization → NormalizedUnit             └ bounded_freshness:   Postprocessing (transform⁻¹)
   │                                            head-drop +           │ Detection[]
   └──→ channel.offer(unit) ───────────────►    max_staleness     ───┴─→ DetectionEvent (sink)
```

- **Productor (Nodo A lógico)**: ingesta → `RateGate` (`stride`, solo `deterministic`) → normalización
  → `channel.offer()`. Corre en un hilo aparte.
- **Canal (`FrameChannel`, interfaz `TransportAdapter`)**: backend `memory` implementado;
  `ipc`/`network` declarados. La **disciplina** del `offer` la fija la política de `rate_control`.
- **Consumidor (Nodo B lógico)**: `channel.request()` → inferencia → postproceso → escritura. Corre
  en el hilo principal.

**Claves**:
- Concurrencia mínima real (no falsa): un hilo productor + consumidor en el principal. `torch` libera
  el GIL durante la inferencia → el productor avanza mientras el consumidor infiere, que es lo que
  `bounded_freshness` necesita para que el head-drop tenga sentido.
- **`deterministic` sigue siendo reproducible** pese a los hilos: sin descarte por tiempo (solo
  `stride` determinista + cola bloqueante), el conjunto de frames procesados es idéntico corrida a
  corrida. Propiedad central de DBE/BENCH.
- Apagado: el productor emite centinela `END`; el consumidor drena y termina. El aislamiento de
  errores por etapa (a `errors.jsonl`) se mantiene.

### Contrato unificado del canal (pull)

```python
class TransportAdapter:
    # lado productor (Nodo A)
    def offer(unit: NormalizedUnit) -> None   # política: block (deterministic) | head-drop (bounded_freshness)
    def close() -> None                        # señal END
    # lado consumidor (Nodo B)
    def request() -> NormalizedUnit | END      # bloquea hasta que haya unidad
```

`request()` es lo único que cambia de forma entre backends: en memoria es un `pop`; en red es un
mensaje `REQUEST`. El buffer + la política viven del lado productor y son idénticos en ambos backends.

### Transporte por caso

- **Un host — backend `memory`**: 2 hilos, mismo proceso. El `NormalizedUnit` (con su payload `ndarray`)
  se pasa **por referencia** — sin copia ni pickling (el pickling solo ocurre entre procesos). Buffer
  acotado (`deque` + `Condition` o `queue.Queue`). Lo más rápido posible en proceso.
- **Dos hosts — backend `network` (declarado)**: **ZeroMQ REQ/REP** multipart (header msgpack + buffer
  uint8 crudo), heartbeat ZMTP, variante robusta Lazy Pirate / DEALER-ROUTER. Sin compresión en LAN;
  payload uint8 (no float32); cast a float en el Nodo B pegado a la GPU.
- **Un host — backend `ipc` (declarado)**: ring buffer en `multiprocessing.shared_memory` entre 2
  procesos locales, para esquivar el GIL si el productor satura un core. No necesario para DBE.

## 4. Esquema de config

Las secciones nuevas son decisiones de **despliegue** (nivel run); `source.kind` es propiedad de la
**fuente** (nivel catálogo). El caso común queda mínimo por derivación.

### Caso común (un host + DBE)

```yaml
run:
  scenario: DBE              # etiqueta de trazabilidad (DBE | EBE)
  name: dbe_gdino_v2
  max_units: null            # cota operativa opcional (null = todo)

source:
  ref: bench_v2              # del catálogo configs/datasets/*.yaml; kind=pulleable se hereda

model:
  ref: grounding_dino/gdino-tiny
prompts:
  ref: canonical_v2
  active_ids: [person, helmet, vest, bare_head]
```

Se derivan: `rate_control.policy=deterministic`, `transport.backend=memory`,
`topology.mode=single_host`, `payload_format=uint8_rgb`.

### Esquema completo

```yaml
source:
  ref: <catalog>
  kind: pulleable            # pulleable | live (default: del type)
  # type: image_folder | video_file (impl) | camera | rtsp (DECLARADOS)

rate_control:
  policy: deterministic       # default DERIVADO de source.kind
  # solo deterministic:
  stride: 1                   # 1=todos; N=cada N (determinista, reproducible)
  max_queue_size: 8           # backpressure: el productor bloquea si la cola se llena
  overflow: fail_run          # si fuente viva usa deterministic y desborda
  # solo bounded_freshness:
  buffer_size: 2              # N>=1; N=1 = latest-only
  max_staleness_ms: 200       # opcional: descarta por edad del frame

transport:
  backend: memory             # default DERIVADO de topology.mode
                              # memory (impl) | ipc (DECLARADO) | network (DECLARADO)
  payload_format: uint8_rgb   # uint8_rgb (impl) | fp32 (impl) | fp16 (DECLARADO)
  # endpoint: tcp://nodoA:5555   # solo backend=network (DECLARADO)

topology:
  mode: single_host           # single_host (impl) | two_node (DECLARADO)
```

`model`, `prompts`, `postprocess`, `outputs`, `logging` quedan igual que hoy.

### Migración de `sampling` (la sección desaparece)

| Hoy (`sampling`) | Pasa a | Motivo |
|---|---|---|
| `every_n` | `rate_control.stride` | Selección determinista de frames (el doc la ubica en rate control). |
| `max_units` | `run.max_units` | Cota operativa del run, ortogonal a la política. |
| `target_fps` | **eliminado** | En `bounded_freshness` el rate emerge del consumidor; en `deterministic` no hay pacing. |
| `mode` | **eliminado** | Reemplazado por `rate_control.policy` (derivado). |

**Migración dura con error claro**: si un YAML trae `sampling`, `validate-config` falla indicando el
mapeo. Sin shim de compatibilidad silencioso.

### Reglas de derivación y validación

1. **Derivación en cascada**: `source.type → source.kind → rate_control.policy`, y
   `topology.mode → transport.backend`. Override explícito permitido.
2. **Coherencia dura (error)**:
   - `topology=two_node` exige `backend=network`; `single_host` prohíbe `network`.
   - Params cruzados: `stride`/`max_queue_size` solo bajo `deterministic`;
     `buffer_size`/`max_staleness_ms` solo bajo `bounded_freshness`. Mezclar = error.
3. **Avisos (warn)**:
   - `deterministic` + fuente `live` → atípico; `max_queue_size` = límite duro con `overflow=fail_run`.
   - `bounded_freshness` + fuente `pulleable` → inusual (perderías reproducibilidad).
4. **Gating implementado vs declarado**: la config puede expresar EBE/dos nodos/fp16/ipc, pero
   `validate-config` marca qué features son "declaradas, no implementadas en este build", y `run`
   falla rápido con mensaje claro si el run requiere algo no implementado.
5. Los defaults derivados se **materializan en `effective_config.yaml`** (trazabilidad).

### Dónde vive cada cosa

- `source.kind` → catálogo `configs/datasets/*.yaml` (propiedad de la fuente). Override en run.
- `rate_control`, `transport`, `topology` → nivel run (decisiones de despliegue).

## 5. Etapa de normalización + contrato de payload + punto de corte

Hoy la normalización está implícita dentro de `adapter.infer(pil_image, …)`. Se la convierte en
**etapa propia del productor** y se define qué cruza el canal.

### Split que dicta el documento

- **Normalización espacial** (decode → RGB → resize/letterbox al target del modelo → `uint8 RGB`):
  decisión cara/con-pérdida → **productor (Nodo A)**.
- **Normalización tensorial** (cast `uint8→float`, mean/std, layout HWC→CHW, `to(device)`): trivial,
  pegada a la GPU → **consumidor (Nodo B)**.

### Contrato nuevo: `NormalizedUnit` (lo que viaja por el canal)

Como el consumidor está desacoplado (otro hilo, eventualmente otro host), por el canal viajan los
píxeles ya normalizados:

- **metadata** (copiada de `VisualUnit`): `run_id`, `unit_id`, `source_id`, `frame_index`,
  `timestamp_ms`, `width`/`height` **originales**.
- `payload`: buffer normalizado (`ndarray`).
- `payload_format`: `uint8_rgb` | `fp32` (impl) | `fp16` (declarado).
- `target_size`: `(H, W)` del payload.
- `transform`: resize transform (`scale_x`, `scale_y`, `pad_x`, `pad_y`) — **imprescindible** para
  reproyectar cajas del espacio-modelo a píxeles originales.

Flujo de contratos: `VisualUnit` (ingesta) → `NormalizedUnit` (normalización) → `RawDetection[]`
(inferencia) → `Detection[]` (postproceso, usa `transform`) → `DetectionEvent`. El buffer de
`rate_control` contiene `NormalizedUnit`s.

### `payload_format` = el punto de corte hecho config

| `payload_format` | Productor (Nodo A) | Consumidor (Nodo B) | Estado |
|---|---|---|---|
| `uint8_rgb` (default) | decode + resize → uint8 RGB | cast float + mean/std + layout + device | impl |
| `fp32` | decode + resize + cast + mean/std → float32 | layout + device | impl |
| `fp16` | resize + cast media precisión | layout + device | declarado |

En un host el `NormalizedUnit` se pasa por referencia → el split no tiene consecuencia funcional, pero
la etapa y el contrato ya existen, así que el corte es real.

### Cambio en los adapters: `ModelInputSpec`

Cada adapter expone un `ModelInputSpec` (target_size, resize_mode, channel_order, mean, std, dtype).
Como un run tiene un solo modelo, el `Normalizer` toma la parte espacial y un finalizador compartido
`prepare_model_input(unit, spec)` (lado consumidor) completa lo que falte según `payload_format`. Los
adapters dejan de reimplementar preprocesamiento; declaran su spec y hacen solo el `forward`.

### Real vs diferido (Sección normalización)

- **Real ahora**: `Normalizer` como etapa del productor, `NormalizedUnit` con `transform`, flujo del
  pipeline a través de la etapa en un host, reproyección correcta de cajas, `ModelInputSpec` por
  adapter, `uint8_rgb` y `fp32`.
- **Matiz adapters de framework (GDINO/HF)**: su `AutoProcessor` agrupa resize+normalize. El
  `Normalizer` hace decode+RGB+resize al target del spec y el finalizador respeta su mean/std; se
  **verifica paridad numérica** contra la salida actual (test golden + `MockDetector`) para que runs
  previos no cambien.
- **Diferido**: `fp16`, serialización byte-level y micro-optimizaciones de payload que solo importan
  cruzando la red (se finalizan junto al backend `network`).

## 6. Trazabilidad + interfaz con datasets + artefactos de métricas

Base existente: `effective_config.yaml`, `run_manifest.json` (run_id, timestamps, git SHA, archivos),
`detections.jsonl`, `metrics.jsonl`, `summary.json`, `errors.jsonl`, `previews/`.

### A. Descriptor de despliegue (bloque en `summary.json`)

```jsonc
"run_descriptor": {
  "scenario": "DBE",
  "topology": "single_host",
  "transport": { "backend": "memory", "payload_format": "uint8_rgb" },
  "rate_control": { "policy": "deterministic", "stride": 1, "max_queue_size": 8 },
  "source_kind": "pulleable",
  "model": "gdino-tiny", "prompt_set": "canonical_v2", "device": "cuda:0",
  "code_version": "<git SHA media-plane>"
}
```

`effective_config.yaml` sigue siendo la fuente de verdad completa; el descriptor son las llaves de
comparación. **Auto-naming**: si `run.id` no se fija, el run_id codifica los ejes
(`run_{ts}_{scenario}_{model}_{policy}`).

### B. Interfaz con `e-ovrt_datasets` — contrato de procedencia

1. La entrada de catálogo `configs/datasets/*.yaml` gana: `dataset_id`, `view` (`canonical_v2`),
   `split` (`bench_v2`), `vocabulary` (lista de clases esperada).
2. El run emite `run_provenance.json` con esos campos + **`source_fingerprint`** (hash del listado
   ordenado de archivos fuente: path + tamaño).
3. **Seam opcional en el repo datasets** (diferible): que `build_role_views.py` emita
   `datasets/splits/v2/<split>.manifest.json` (vocabulario + conteo + hash). Si el media-plane lo
   encuentra, usa ese fingerprint autoritativo; si no, recomputa.
4. Chequeo de coherencia: `prompts.active_ids` debe ser subconjunto del `vocabulary` de la fuente →
   `validate-config` avisa si no alinean.

### C. Artefactos de métricas versionados (contrato para el módulo futuro)

- `schema_version` en `summary.json` y en cada registro de `metrics.jsonl`. Se bumpea ante cambios
  incompatibles.
- `summary.json` lleva `run_descriptor` (A) + `provenance` (B) + métricas alineadas a "capacidad,
  latencia y uso de memoria":

| Eje | Métricas | Estado |
|---|---|---|
| Capacidad/throughput | `fps_effective`, `units_processed`, `duration_seconds` | existe |
| Latencia | `avg/p50/p95/p99_latency_ms` + desglose por etapa (read/normalize/inference/postprocess/write) | p99 + desglose nuevos |
| Memoria | `gpu_memory_peak_mb` | existe |
| Efecto rate control | `units_dropped` (head-drop), `backpressure_wait_ms`, `max_staleness_observed_ms` | nuevo |

El último eje permite comparar `deterministic` vs `bounded_freshness` sobre el mismo escenario (el
experimento del doc). `MetricSample.dropped_units` (hoy siempre 0) toma valores reales bajo
`bounded_freshness`.

### D. CLI

- **`inspect-run runs/<id>`** (implementar): lee artefactos versionados y muestra `run_descriptor` +
  `provenance` + métricas.
- **`compare-runs`** / agregación: lo deja el futuro módulo de métricas. Los artefactos versionados ya
  lo hacen trivial. No se construye ahora.

## 7. Interfaces declaradas (diferidas)

| Pieza | Estado | Costura |
|---|---|---|
| Política `deterministic` (stride + backpressure) | impl | sobre backend `memory` |
| Política `bounded_freshness` (head-drop + staleness) | impl | sobre backend `memory` |
| Backend `memory` (cola en proceso) | impl | `TransportAdapter` concreto |
| Fuente `pulleable` (image_folder, video_file) | impl | `BaseSource` concreto |
| Fuente `live` (camera, rtsp) | declarado | `LiveSource(BaseSource)` abstracta; factory `NotImplementedError` |
| Backend `ipc` (shared-memory ring buffer) | declarado | `TransportAdapter` registrado |
| Backend `network` (ZMQ REQ/REP + heartbeat ZMTP) | declarado | `TransportAdapter` registrado; mensajes `REQUEST`/`RESPONSE`/`HEARTBEAT` como contratos |
| Topología `two_node` (corte tras normalización) | declarado | config válida, `run` falla rápido |
| `payload_format: fp16` + serialización wire | declarado | enum válido; se finaliza con backend `network` |

**Costura declarada (no TODO suelto)**: interfaz abstracta existe y la referencia la factory; tipos
de mensaje del protocolo de dos nodos definidos como contratos; la factory reconoce el tipo declarado
y lanza `NotImplementedError` con mensaje explícito. La config lo expresa, el runtime lo rechaza con
claridad.

## 8. Testing

`MockDetector` permite el pipeline end-to-end sin pesos. Sobre esa base:

- **Reproducibilidad de `deterministic`**: misma config dos veces → `detections.jsonl` idéntico (pese
  a hilos). Verifica que la concurrencia no rompe la comparabilidad de DBE.
- **Políticas de rate control**: `deterministic` (stride determinista; productor bloquea con cola
  llena); `bounded_freshness` (head-drop bajo carga simulada, `max_staleness_ms`, `units_dropped`).
- **Concurrencia**: hilos productor/consumidor, apagado limpio vía `END`, aislamiento de errores por
  etapa.
- **`Normalizer`**: reproyección de cajas vía `transform` (golden) y paridad numérica con el
  preprocesamiento actual de cada adapter.
- **Config**: derivación, errores de validación cruzada, gating (features declaradas fallan rápido).
- **Trazabilidad**: `source_fingerprint` estable, `schema_version` presente, `run_descriptor`
  materializado.
- **Contrato `TransportAdapter` agnóstico de backend**: suite que hoy corre contra `memory`, escrita
  para que el futuro backend `network` corra los mismos tests.

## 9. Riesgos y puntos abiertos

- **Paridad numérica del `Normalizer`** con los `AutoProcessor` de HF (GDINO): riesgo de que los
  resultados de runs previos cambien. Mitigación: test golden + verificación explícita antes de migrar.
- **Concurrencia vs reproducibilidad**: garantizar que `deterministic` no introduce no-determinismo
  por el desacople en hilos. Mitigación: test de reproducibilidad como criterio de aceptación.
- **Migración dura de `sampling`**: rompe configs existentes a propósito. Hay que migrar los YAML del
  repo en el mismo cambio.
- **Seam datasets**: el `*.manifest.json` en el repo datasets es opcional; definir bien el fallback
  de recomputar fingerprint.

## 10. Próximo paso

Plan de implementación (skill `writing-plans`) descomponiendo este diseño en fases verificables, con
el camino un host + DBE como primer hito end-to-end.
