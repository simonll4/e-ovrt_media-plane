# Pre-filtro de frames on-device en OAK-D (EN-2) — Diseño

**Fecha**: 2026-07-15
**Estado**: propuesto (pendiente de revisión)
**Repos afectados**: `e-ovrt_media-plane` (código), `docs/` (tesis: EN-2 pasa de "condicionada" a "implementada como variante opcional")

## 1. Contexto y motivación

El media-plane consume frames de la OAK-D Pro PoE mediante `OakDSource` (spec
`2026-07-13-oak-d-source-design.md`): la cámara opera en modo **EN-0** (captura sin
análisis local) y todos los frames viajan al host, donde el único filtro previo a la
inferencia OVD es el stride determinista de `RateGate` y el descarte por antigüedad de
`bounded_freshness`. No existe ninguna selección por contenido.

Esto desperdicia cómputo en tres frentes:

1. **Link PoE (1 Gbps)**: 1080p NV12 @30 FPS ≈ 747 Mbps; el throughput útil real en PoE
   es bastante menor que el teórico y saturarlo dispara la latencia de forma no lineal.
2. **Inferencia OVD en el host**: GDINO es el costo dominante del sistema; inferir sobre
   frames sin personas ni movimiento no aporta evidencia.
3. **Almacenamiento/cola**: frames inservibles ocupan buffer y presionan
   `bounded_freshness`, descartando potencialmente frames útiles más nuevos.

La arquitectura de la tesis ya prevé este modo: **EN-2, "preselección liviana
conservadora"** (`docs/contexto/diseno-arquitectonico.md`, Tabla 56): *"El EN utiliza
criterios simples, movimiento o un modelo cerrado liviano para priorizar segmentos
candidatos. Condicionado; debe ser conservador, registrar descartes y considerar falsos
negativos potenciales antes de la inferencia OVD."* La Tabla 57 registra el riesgo
asociado (pérdida de evidencia por preselección) y exige: criterios conservadores,
registro de descartes y comparación contra el flujo sin preselector.

**Este spec activa EN-2 cumpliendo esas tres condiciones.** El objetivo del filtro NO es
detectar bien (eso es tarea del OVD): es descartar barato lo claramente inservible, con
sesgo estructural a *fail-open* — ante cualquier duda o falla, el frame pasa.

**Distinción de alcance para la defensa**: esto NO es "inferencia OVD en borde" (EN-3,
sigue fuera de alcance). Es un detector cerrado liviano usado como compuerta, alineado
con la letra de EN-2. La inferencia de vocabulario abierto sigue concentrada en el CPN.

## 2. Objetivos y no-objetivos

**Objetivos**

- Filtrar on-device (en la propia cámara) los frames sin evidencia de personas,
  reduciendo tráfico PoE, inferencias OVD y presión de cola.
- Sesgo fail-open verificable: umbral de confianza bajo, ventana de gracia temporal,
  heartbeat periódico y apertura total ante fallas del filtro.
- Registrar cada descarte con motivo (contadores agregados + bloque en `summary.json`),
  como exige EN-2.
- Reducir la latencia captura→host y el trabajo por frame en el host (ajustes de
  transporte XLink + escala en el ISP de la cámara), y **medir** ese tramo con los
  timestamps de device sincronizados (hoy es invisible para la telemetría).
- Comparabilidad experimental: el filtro se activa/desactiva por config de corrida sin
  ningún otro cambio; una corrida con `prefilter.enabled: false` es bit a bit el flujo
  actual.

**No-objetivos**

- Inferencia OVD o de vocabulario configurable en la cámara (EN-3, fuera de alcance).
- Filtrado para las demás fuentes (`rtsp`, `video_file`, `image_folder`): el gate es una
  capacidad de la OAK-D; un preselector host-side genérico queda como trabajo futuro.
- Migración a DepthAI v3 (sigue fuera de alcance; todo el diseño usa la API v2 ya
  presente en `oak_d_source.py`).
- Tracking / deduplicación temporal (`ObjectTracker`) y gating por movimiento
  (`FeatureTracker`): documentados como extensiones (§11), no en v1.

## 3. Capacidades de la cámara relevadas (resumen de investigación)

OAK-D Pro PoE = RVC2 (Myriad X): ~1.4 TOPS para NN, 16 SHAVEs, 2 CPUs LEON, encoder HW.
Lo aprovechable para un pre-filtro:

| Capacidad | Nodo DepthAI v2 | Uso en este diseño |
|---|---|---|
| Detector NN liviano on-device | `MobileNetDetectionNetwork` + blob | **Sí (v1)**: detector de personas como compuerta |
| Lógica de flujo programable on-device | `Script` (CPython 3.9 en LEON) | **Sí (v1)**: decisión de reenvío frame a frame + stats |
| Redimensionado HW para entrada NN | `ColorCamera.preview` | **Sí (v1)**: rama preview a resolución del blob, full-FOV |
| Tracking HW (skip de inferencia, dedup) | `ObjectTracker` | Extensión (§11) |
| Optical flow HW (score de movimiento) | `FeatureTracker` | Extensión (§11) |
| Micro-NN custom (frame-diff, blur/Laplaciano) | `NeuralNetwork` con blob custom | Extensión (§11) |
| Escalado en el ISP (hardware, sin costo de SHAVEs) | `ColorCamera.setIspScale(num, den)` | **Sí (v1)**: reducir resolución antes de transmitir (§7) |
| Transporte XLink sin chunking | `pipeline.setXLinkChunkSize(0)` | **Sí (v1)**: baseline oficial de baja latencia (§7) |
| Timestamps de device sincronizados al host | `ImgFrame.getTimestamp()` (timesync, <0.5 ms en PoE) | **Sí (v1)**: métrica captura→host (§7) |
| Compresión HW | `VideoEncoder` | Extensión (§11); v1 mantiene frames crudos como hoy |
| Gating por profundidad | `SpatialLocationCalculator` | Descartado: no aporta al caso de uso actual |

Restricción dura del nodo `Script` (documentada por Luxonis): corre en el LEON, sin
numpy/cv2, y NO debe hacer cómputo sobre píxeles — solo lógica de enrutamiento de
mensajes. Todo lo pesado va a nodos HW o a la NN. En dispositivos PoE el LEON_CSS ya
carga el stack de red, así que el script se mantiene mínimo.

**Modelo elegido para v1**: `person-detection-retail-0013` (Open Model Zoo, Apache-2.0,
MobileNetV2+SSD, entrada 544×320, 2.3 GFLOPs, AP ~88% en peatones): corre en tiempo real
en RVC2, es el estándar de los ejemplos Luxonis de conteo de personas, su salida es
directamente compatible con `MobileNetDetectionNetwork`, y su licencia es permisiva.
Alternativa evaluada y descartada para v1: YOLOv6n (~60 FPS pero licencia GPL-3.0) y
YOLOv5n/v8n (AGPL). El blob se compila para 6 SHAVEs vía blobconverter.

## 4. Alternativas de arquitectura consideradas

**A. Preselector host-side** (motion/NN en el producer del media-plane, junto a
`RateGate`). Genérico para todas las fuentes y fácil de testear, pero no ahorra el
recurso más escaso (el link PoE) ni usa las capacidades de la cámara, que es el
requerimiento. Descartada como v1; queda como generalización futura.

**B. Gate NN on-device con `Script` (elegida)**. Detector de personas en la cámara; un
nodo `Script` reenvía el frame de video al host solo si hay evidencia reciente de
persona, con heartbeat y fail-open. Ahorra transmisión + inferencia + cola; complejidad
contenida (3 nodos nuevos en el pipeline existente); el patrón "Script reenvía frames
condicionalmente" es el canónico documentado por Luxonis (`script_forward_frames`,
`gen2-people-counter`).

**C. EN-2 completo multi-etapa** (movimiento por `FeatureTracker` → NN persona →
`ObjectTracker` para dedup → `VideoEncoder`). Máximo ahorro pero triplica la superficie
de fallas y de tuning sin evidencia de que la etapa NN sola no alcance. YAGNI:
descartada para v1; cada etapa queda especificada como extensión incremental (§11).

## 5. Diseño: pipeline on-device

Extensión del pipeline actual de `OakDSource._build_pipeline` (hoy: `ColorCamera` →
`XLinkOut "rgb"`). Con `prefilter.enabled: true` el pipeline pasa a:

```
ColorCamera CAM_A
 ├── .video (full res, como hoy) ──────────────► Script.inputs['frames']
 └── .preview (544×320, full FOV) ─► MobileNetDetectionNetwork ─► Script.inputs['detections']
                                                                     │
     Script (gate, LEON) ── io['out'] ─────────► XLinkOut "rgb"  ◄───┘
                └───────── io['stats'] ────────► XLinkOut "prefilter_stats"
```

- `cam.setPreviewSize(544, 320)` + `cam.setPreviewKeepAspectRatio(False)`: la rama NN
  recibe el FOV completo estirado (sin crop central), porque para una compuerta importa
  no perder personas en los bordes más que la fidelidad geométrica.
- `orientation` se aplica a nivel `ColorCamera` (`setImageOrientation`, como hoy), así
  que la rama preview de la NN y el video al host comparten orientación automáticamente
  — no hay que rotar nada aparte, y el detector ve exactamente lo que se reenvía. Con
  `rotate_180` en montaje invertido la imagen ya queda derecha, que es lo que el
  detector espera; el fail-open cubre cualquier degradación residual de recall.
- `MobileNetDetectionNetwork`: `setBlobPath(<blob>)`,
  `setConfidenceThreshold(prefilter.confidence)` (bajo, default 0.25),
  `input.setBlocking(False)`, `input.setQueueSize(1)` (siempre el frame más fresco).
- El `XLinkOut "rgb"` y todo el lado host aguas abajo quedan idénticos: el gate es
  transparente para `VisualUnit`, el transport y el consumer.
- Con `prefilter.enabled: false` (default) se construye el pipeline actual sin ningún
  nodo extra: paridad exacta con EN-0.

### Lógica del gate (nodo `Script`)

Decisión por **ventana de evidencia**, no por apareo estricto frame↔detección (la NN
corre más lenta que la cámara; aparear exactamente agrega complejidad sin beneficio para
un filtro). Estado del script: `last_person_ts`, `last_nn_ts`, `last_sent_ts`,
contadores. Por cada frame de video recibido:

```
REENVIAR el frame si CUALQUIERA de:
  1. persona:    now - last_person_ts <= keepalive_window_ms
                 (alguna detección 'person' con conf >= confidence en la ventana)
  2. heartbeat:  now - last_sent_ts >= heartbeat_interval_ms
  3. fail-open:  now - last_nn_ts >= stall_failopen_ms
                 (la NN dejó de responder: se abre la compuerta por completo)
  4. warm-up:    todavía no llegó ningún resultado de la NN desde el arranque
en caso contrario, DESCARTAR e incrementar dropped_no_person.
```

Los resultados de NN se drenan con `tryGet()` en el mismo loop (no bloquean el paso de
frames). Cada ~1 s el script publica por `io['stats']` un `Buffer` con JSON:
`{seen, forwarded, dropped_no_person, forwarded_by_reason: {person, heartbeat,
failopen, warmup}, nn_results}`. Reglas 2–4 son el mecanismo estructural de fail-open:
aunque el detector no vea nunca a nadie, el host recibe ≥1 frame por
`heartbeat_interval_ms`, y cualquier silencio de la NN abre la compuerta.

El código del script vive como constante de módulo en Python (template con los
parámetros interpolados de forma segura — solo números validados por schema), para poder
testearlo en host sin hardware (§10).

## 6. Diseño: lado host

### `OakDSource` (`sources/oak_d_source.py`)

- `_build_pipeline()` bifurca según `prefilter.enabled`; rama nueva
  `_build_prefiltered_pipeline()`.
- `__iter__` agrega una segunda cola `prefilter_stats` (maxSize=4, non-blocking) drenada
  con `tryGet()` en el mismo loop del productor; el último JSON recibido se acumula en
  un atributo `prefilter_stats` del source (dict, thread-safe por asignación atómica).
- El watchdog de stream mudo (`_NO_FRAME_TIMEOUT_S = 10 s`) hoy fuerza reconexión si no
  llegan frames; con gate activo un silencio ≤ `heartbeat_interval_ms` es normal. Regla:
  el timeout efectivo pasa a `max(10 s, 3 × heartbeat_interval_ms)` cuando el prefilter
  está activo. El heartbeat cumple doble función: fail-open y keepalive del watchdog.
- Resolución del blob: `prefilter.model_blob` es una ruta relativa a la raíz del repo
  (mismo convenio que los pesos actuales). Si el archivo no existe → error al construir
  la fuente (fail-fast en el 422/409 del POST, no a mitad de corrida).

### Configuración (`config/schemas.py`)

Bloque nuevo anidado en `SourceSection`, válido solo para `type: oak_d` (el validador
`_check_locator` rechaza `prefilter` en otros tipos):

```yaml
source:
  type: oak_d
  url: "192.168.1.50"
  resolution: 1080p
  fps: 10
  prefilter:
    enabled: true                # default false → EN-0 exacto
    model_blob: models/edge/person-detection-retail-0013_6shave.blob
    confidence: 0.25             # (0,1); bajo a propósito (fail-open)
    keepalive_window_ms: 1500    # ventana de evidencia de persona
    heartbeat_interval_ms: 2000  # frame incondicional cada N ms
    stall_failopen_ms: 3000      # silencio de NN que abre la compuerta
```

Modelo Pydantic `OakDPrefilterConfig` con esos campos y validaciones (`gt=0`,
`confidence` en `(0,1)`, `stall_failopen_ms >= keepalive_window_ms`). Sin valores
hardcodeados en el código: todo knob viaja por config, como exige el proyecto.

### Telemetría (requisito EN-2: "registrar descartes")

- `RunContext` suma: `prefilter_frames_seen`, `prefilter_frames_forwarded`,
  `prefilter_dropped_no_person`, `prefilter_forwarded_by_reason` (dict). Se pueblan al
  cierre del run (y periódicamente) desde `OakDSource.prefilter_stats`.
- `summary.json` (`run_artifact_writer.write_summary`) suma un bloque `prefilter` con
  esos contadores más la config efectiva (`enabled`, `confidence`,
  `keepalive_window_ms`, `heartbeat_interval_ms`, `stall_failopen_ms`, `model_blob`),
  para que toda corrida declare su preselector — condición de comparabilidad de la
  Tabla 57. Con `enabled: false` el bloque es `{"enabled": false}`.
- Los frames descartados on-device NO cuentan en `units_dropped` (ese contador significa
  descarte en cola del host: staleness, desborde de buffer o canal cerrado — rate
  control/transporte); son una causa distinta con contador propio. `source_count` sigue
  significando "unidades que entraron al pipeline del host".
- **Two-node (EBE distribuido)**: el gate funciona igual (vive en la cámara, aguas
  arriba de todo), pero los **contadores** no llegan al `summary.json` en v1: el source
  vive en Nodo A y el `RunArtifactWriter` en Nodo B, y no hay canal para
  `prefilter_stats` por el link ZeroMQ. El bloque `prefilter` del summary sale con la
  config efectiva (Nodo B la tiene, la run config es compartida) más
  `counters_available: false` y `reason: "two_node_v1"`; Nodo A loguea los stats
  periódicos en su log local. Transportar los contadores por el link queda como
  extensión (§11). Consecuencia deliberada: **las corridas A/B de validación EN-2 se
  hacen en single-host**, donde el registro de descartes es completo; esto se resuelve
  a nivel del writer, sin tocar `runtime/two_node.py`.

### Provisión del blob

Script `scripts/download_prefilter_blob.py` (o target en el Makefile junto a
`download-models`): descarga `person-detection-retail-0013` y lo compila a blob RVC2
(6 SHAVEs) vía el paquete `blobconverter` (se agrega al extra `edge`), dejándolo en
`models/edge/`. El blob (~3 MB) se git-ignora como el resto de los pesos; el registry de
modelos documenta procedencia y licencia (Apache-2.0, Open Model Zoo).

## 7. Diseño: latencia de captura y envío

Números de referencia (tablas oficiales Luxonis, medidas con chunking deshabilitado):
color 1080p crudo cámara→host ≈ **51 ms por PoE** (33 ms por USB3); el link GbE rinde
~800 Mbps útiles y **saturarlo dispara la latencia de forma no lineal** (4K@8 fps =
148 ms vs 4K@10 fps = 530 ms). Con la config actual (1080p NV12 @10 fps ≈ 250 Mbps) el
link no está saturado: las palancas dominantes son el tamaño de frame, el chunking de
XLink y el trabajo por frame en el host — no el ancho de banda.

### Medidas adoptadas en v1 (independientes del prefilter, config-driven)

1. **`pipeline.setXLinkChunkSize(0)`**: deshabilita el particionado de paquetes XLink;
   es la condición bajo la cual Luxonis mide sus propias tablas de baja latencia.
   Config `xlink_chunk_size` (default `0`; `-1` = default del device, 64 KiB).
2. **Escala en el ISP** (`setIspScale(num, den)`): reduce la resolución en el bloque
   scaler del ISP (hardware dedicado, sin consumir SHAVEs) **antes** de transmitir; se
   aplica a la salida `.video` que ya usamos. Config opcional `isp_scale: [num, den]`
   (el schema valida solo la forma de la fracción: `num ≤ 16`, `den ≤ 63` tras
   simplificar — no su interacción con el modelo). Beneficio triple: menos
   bytes por el PoE, `getCvFrame()` (NV12→BGR en host) más barato, y resize de
   `normalize_spatial` más barato. Regla de elección (heurística **operativa**, va en
   la documentación, no en el schema — la fuente no conoce el `input_spec` del adapter
   al validar): que el lado corto emitido quede **≥ el lado corto del `input_spec` del
   OVD** — reducir por debajo de lo que el host igual va a submuestrear no pierde nada;
   reducir más sí. Ej.: 1080p con `[3, 4]` → 1440×810.
3. **Métrica captura→host con timestamps de device**: `ImgFrame.getTimestamp()` llega
   ya traducido al reloj monotónico del host (protocolo de timesync activo por defecto,
   error < 0.5 ms en PoE desde depthai 2.24). Nueva métrica por frame
   `capture_to_host_ms = dai.Clock.now() - frame.getTimestamp()`, con p50/p95 en
   `summary.json`. Portador: la mide `OakDSource` al leer y viaja como campo **opcional
   aditivo** `capture_to_host_ms: float | None = None` en `VisualUnit` y
   `NormalizedUnit` (mismo patrón de copiado explícito que `capture_monotonic_ns`;
   `None` para toda otra fuente). **El ancla del G2A no cambia en v1**: `capture_monotonic_ns` se
   sigue estampando al leer en host, para no romper la comparabilidad con corridas
   previas. La métrica nueva expone el tramo cámara→host que hoy es invisible;
   re-anclar el G2A al instante real de captura queda como decisión explícita
   posterior, con datos de esta métrica sobre la mesa.
4. **Colas**: el lado host ya está en el óptimo oficial de latencia
   (`getOutputQueue(maxSize=1, blocking=False)`); la rama NN del prefilter usa
   `queueSize=1` non-blocking (§5). Sin cambios.

Nota operativa (documentación, no código): en el host Linux, el tuning de NIC
recomendado por Luxonis para PoE (`ethtool -C <iface> rx-usecs 1022`) mejora
throughput/carga del Leon CSS; va a `docs/` como procedimiento, no a la config del run.

### Enviar frames "ya preprocesados": qué sí y qué no

- **Sí (v1)**: la reducción de resolución en el ISP (punto 2) — es exactamente la parte
  del preprocesado del host que la cámara hace gratis y sin trade-off de contrato.
- **Rechazado — conversión NV12→BGR on-device**: ahorraría los ~2–5 ms de
  `getCvFrame()` en host, pero BGR son 3 B/px contra 1.5 B/px de NV12: **duplica** el
  tráfico PoE (1080p30 BGR = 1.5 Gbps, ni siquiera entra en el link). Solo cierra a
  resoluciones chicas y no justifica cambiar el contrato de la fuente.
- **Rechazado — emitir el letterbox exacto de entrada del OVD** (ImageManip
  `setResizeThumbnail` + conversión on-device, host salta `normalize_spatial`):
  acoplaría la fuente al `input_spec` del adapter (la cámara tendría que conocer el
  modelo de la corrida al armar el pipeline), y el host perdería el frame original para
  previews/`annotated.mp4` y para el mapeo de coordenadas que `normalize_spatial`
  registra. El ahorro marginal sobre la escala ISP no justifica romper esa frontera de
  capas.
- **Diferido (extensión, §11) — MJPEG on-device**: la mayor palanca de ancho de banda
  (~10×; encoder por hardware). Los números oficiales muestran que el encode se paga
  solo (USB 1080p60: MJPEG 31 ms vs crudo 33 ms; en 4K, 71 vs 150 ms) y en PoE la
  ganancia sería mayor; el costo es el decode en host (~2–10 ms, `cv2.imdecode` /
  turbojpeg) y, sobre todo, que hay que **validar el efecto de los artefactos JPEG
  sobre el OVD** con una corrida A/B antes de adoptarlo. No entra en v1.

### Config resultante (campos nuevos en `SourceSection`, solo `oak_d`)

```yaml
source:
  type: oak_d
  url: "192.168.1.50"
  resolution: 1080p
  fps: 10
  isp_scale: [3, 4]        # opcional; ausente = sin escala (comportamiento actual)
  xlink_chunk_size: 0      # default 0 (sin chunking); -1 = default del device
  prefilter: { ... }        # §6
```

## 8. Flujo de datos y semántica

- Un frame descartado on-device **nunca existió** para el host: no hay `VisualUnit`, no
  hay `unit_id`, no cuenta en `source_count`. La evidencia de su existencia son los
  contadores de `prefilter_stats` (y los gaps de `getSequenceNum`, que el host puede
  cruzar como verificación).
- `frame_index` sigue siendo el contador de frames **emitidos** (`emitted`), como hoy;
  el stride de `RateGate` sigue operando aguas abajo sobre los frames que pasaron el
  gate (los dos filtros componen: primero contenido en cámara, después stride en host).
- G2A no cambia de definición: `capture_monotonic_ns` se estampa al leer en host, como
  hoy. El tiempo que el frame pasó en la cámara no entra al G2A (consistente con el
  comportamiento actual de EN-0).
- DBE/EBE: sin cambios. El gate ocurre antes de que exista la unidad, así que replay,
  bus y artefactos son idénticos en semántica.

### Compatibilidad con las demás fuentes (invariantes, no negociables)

Toda esta integración es **aditiva y encapsulada en `oak_d`**; los plugins `rtsp`,
`video_file` e `image_folder` (datasets) no cambian de comportamiento en nada:

1. **Contratos intactos**: `BaseSource` no gana métodos abstractos ni atributos
   requeridos; `VisualUnit`/`NormalizedUnit` solo ganan el campo opcional
   `capture_to_host_ms` con default `None` (§7.3 — aditivo, invisible para las fuentes
   que no lo emiten). `prefilter_stats` es un atributo propio de
   `OakDSource` que el pipeline lee con `getattr(source, "prefilter_stats", None)` al
   cierre — para cualquier otra fuente es `None` y no pasa nada.
2. **Schema aditivo**: `prefilter` e `isp_scale` entran a `SourceSection` como
   opcionales con default `None`; `xlink_chunk_size` con default `0` (solo lo lee
   `OakDSource`, así que el default no afecta a ninguna otra fuente) — mismo patrón que
   `resolution`/`fps`/`orientation`, que ya conviven con todos los tipos. Toda config
   existente de `rtsp`/`image_folder`/`video_file`/datasets valida idéntico que hoy.
   Diferencia deliberada con el patrón actual: si alguien **setea** uno de los campos
   nuevos en una fuente no-`oak_d`, el validador lo rechaza con 422 (explícito mejor
   que ignorado en silencio); los campos ausentes no validan nada. Detalle de
   implementación: para `prefilter`/`isp_scale` "seteado" es `is not None`; para
   `xlink_chunk_size` (default `0`, no distinguible por valor) el validador usa
   `model_fields_set` de Pydantic.
3. **`detections.jsonl` no se toca**: ni formato ni contenido. El invariante de paridad
   byte-a-byte del bus con el control-plane (`bus.envelope.v1`, test de paridad) queda
   intacto.
4. **`MetricSample` aditivo**: `capture_to_host_ms: float | None = None`; las demás
   fuentes emiten `null`. Campo opcional → sin bump de versión de `media.metric.v2`.
5. **`summary.json` aditivo**: el bloque `prefilter` sale `{"enabled": false}` en toda
   corrida sin gate (cualquier fuente); los percentiles `capture_to_host` solo aparecen
   para `oak_d`. Ningún campo existente cambia de nombre, tipo ni semántica
   (`units_dropped` y `source_count` conservan su significado actual, §6).
6. **Rutas de código**: `pipeline.py` no agrega lógica condicionada por tipo de fuente
   salvo el `getattr` del punto 1; `RateGate`, transports, normalizador, consumer y
   two-node quedan sin tocar en sus caminos existentes.

## 9. Manejo de errores

| Falla | Comportamiento |
|---|---|
| Blob ausente/corrupto al armar pipeline | Error al crear la fuente → el POST /api/runs falla explícito (fail-fast, nunca degradar en silencio a EN-0) |
| NN deja de emitir en runtime | Regla 3 del gate: compuerta abierta total tras `stall_failopen_ms`; el run continúa como EN-0 de facto y los stats lo evidencian (`forwarded_by_reason.failopen`) |
| Script crashea on-device | No llegan frames ni stats → watchdog de stream mudo → reconexión con backoff (mecanismo existente) |
| Cola `prefilter_stats` sin mensajes | No bloquea nada; los contadores quedan en el último valor conocido y `summary.json` marca `stats_stale: true` si el último JSON tiene > 10 s al cierre |
| `prefilter` configurado en fuente no-oak_d | 422 en validación de config (schema) |

## 10. Testing

- **Unit, lógica del gate**: el template del script se ejecuta en host dentro de un
  harness con dobles de `node.io` y `time` inyectable; casos: pasa con persona, descarta
  sin persona, heartbeat exacto, fail-open por stall de NN, warm-up, contadores
  correctos. Sin hardware ni depthai real.
- **Unit, `OakDSource`**: extiende los dobles de depthai de la suite existente
  (`tests/test_oak_d_source.py`): pipeline con/sin prefilter construye los nodos
  esperados, parseo de stats, timeout de watchdog escalado, fail-fast por blob ausente.
- **Unit, config**: schema acepta/rechaza (`confidence` fuera de rango, `prefilter` en
  `rtsp`, defaults correctos, `enabled: false` ≡ ausencia del bloque; `isp_scale` con
  `num > 16` / `den > 63` rechazado, `xlink_chunk_size` negativo distinto de `-1`
  rechazado).
- **Unit, latencia**: el pipeline aplica `setXLinkChunkSize`/`setIspScale` según config
  (verificado sobre los dobles de depthai); `capture_to_host_ms` calculado desde
  `getTimestamp()` y agregado p50/p95 en summary.
- **Unit, telemetría**: `summary.json` incluye el bloque `prefilter` con y sin gate.
- **Regresión, otras fuentes (gate de los invariantes de §8)**: (a) la suite existente
  de `rtsp`/`video_file`/`image_folder` debe pasar **sin modificar ni un test**; (b)
  configs existentes de esas fuentes validan idéntico; (c) `prefilter`/`isp_scale`/
  `xlink_chunk_size` seteados en una fuente no-`oak_d` → 422; (d) corrida `image_folder`
  con `MockDetector`: el `summary.json` difiere del actual solo por el bloque aditivo
  `prefilter: {enabled: false}` y `metrics.jsonl` trae `capture_to_host_ms: null`.
- **E2E con hardware (manual, no CI)**: corrida A/B contra la cámara real (mismo
  escenario, `enabled` true/false) verificando: (a) con escena vacía, el host recibe
  ~1 frame por heartbeat; (b) con persona, tasa de paso ≈ EN-0; (c) contadores del
  summary consistentes con lo observado. Es además el experimento de validación que
  exige la Tabla 57 (comparación contra flujo sin preselector).

## 11. Extensiones previstas (no en v1)

Cada una es incremental sobre este diseño, activable por config, y solo se justifica con
evidencia de la corrida A/B de v1:

1. **Etapa de movimiento previa** (`FeatureTracker`, 2 SHAVEs): score de desplazamiento
   medio de features decodificado en el mismo `Script`; ahorra inferencias NN on-device
   en escenas estáticas. Útil si la NN on-device resultara cuello de botella.
2. **`ObjectTracker` para deduplicación temporal**: "misma persona estacionaria → bajar
   tasa de reenvío"; requiere definir qué significa redundante para el OVD (riesgo de
   perder cambios de EPP sin movimiento — evaluar contra CR-01/CR-02 antes de activar).
3. **`VideoEncoder` (MJPEG) para la rama de salida**: reduce aún más el link PoE;
   requiere decodificar en host y medir el costo de calidad sobre el OVD.
4. **Blur gating** (micro-NN Laplaciano custom, patrón `gen2-custom-models`): descartar
   frames movidos/desenfocados; requiere calibrar umbral por escena.
5. **Preselector host-side genérico** para `rtsp`/`video_file` reutilizando la misma
   config y telemetría (cierra la generalización de la alternativa A).
6. **Contadores de prefilter en two-node**: transportar `prefilter_stats` de Nodo A a
   Nodo B (p.ej. mensaje final por el canal ZeroMQ existente) para que el summary EBE
   tenga registro de descartes completo (hoy: §8, `counters_available: false`).

## 12. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Falsos negativos del detector (persona presente, frame descartado) — el riesgo central de EN-2 | Umbral 0.25, full FOV en la rama NN, ventana de evidencia (una detección mantiene la compuerta abierta `keepalive_window_ms`), heartbeat, y corrida A/B obligatoria antes de usar el modo en experimentos que alimenten métricas de tesis |
| Carga extra en LEON_CSS (PoE ya usa esa CPU para red) | Script mínimo (solo enrutamiento y contadores); NN y resize en HW/SHAVEs; verificar en E2E que el FPS efectivo no cae vs EN-0 con compuerta abierta |
| Dominio del modelo (retail/peatones) vs obra (posturas, EPP, oclusiones) | El sesgo fail-open acota el daño (duda → pasa); si el A/B muestra recall insuficiente, escalar a un detector de personas más robusto del zoo antes de tocar la arquitectura |
| Divergencia de relojes host/cámara en la lógica del gate | El gate solo usa tiempo relativo local del script (monotónico dentro del device); nunca compara contra relojes del host |
| `SHORT_TERM`/tuning prematuro | Extensiones bloqueadas hasta tener datos de v1 (§11) |

## 13. Resumen de cambios por archivo

| Archivo | Cambio |
|---|---|
| `src/eovrt_media/sources/oak_d_source.py` | Rama de pipeline con prefilter, template del script, cola de stats, watchdog escalado; `setXLinkChunkSize`, `setIspScale`, timestamps de device (`capture_to_host_ms`) |
| `src/eovrt_media/config/schemas.py` | `OakDPrefilterConfig`, campos `prefilter`, `isp_scale`, `xlink_chunk_size` en `SourceSection`, validaciones |
| `src/eovrt_media/contracts/metrics.py` + `metrics/collector.py` | Campo `capture_to_host_ms` en `MetricSample` y agregación p50/p95 |
| `src/eovrt_media/runtime/run_context.py` | Contadores `prefilter_*` |
| `src/eovrt_media/runtime/pipeline.py` | Volcado de `source.prefilter_stats` a `RunContext` al cierre |
| `src/eovrt_media/sinks/run_artifact_writer.py` | Bloque `prefilter` en `summary.json` (en two-node: config efectiva + `counters_available: false`, §8) |
| `scripts/download_prefilter_blob.py` + Makefile | Provisión del blob RVC2 |
| `pyproject.toml` | `blobconverter` en extra `edge` |
| `configs/runs/local/oak_d_camera.yaml` (ejemplo) | Bloque `prefilter` comentado |
| `tests/…` | Suites de §9 |
| `docs/` (media-plane) + repo docs (tesis) | EN-2: de "condicionada, fuera de alcance" a "implementada como variante opcional, default off"; nota operativa de tuning NIC PoE (`ethtool -C <iface> rx-usecs 1022`) |
