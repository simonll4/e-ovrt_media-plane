# OakDSource: integración OAK-D Pro PoE como fuente viva

**Fecha**: 2026-07-13
**Estado**: aprobado (diseño validado en sesión con el usuario)
**Contexto previo**: ADR-0005 (EBE vía RTSP) dejó `OakDSource` declarado-no-implementado
a la espera del hardware. El hardware ya está disponible (aún sin conectar a la LAN).

## Objetivo

Completar el plugin `oak_d` del media-plane para que una OAK-D Pro PoE funcione como
fuente viva de ingesta, siguiendo el patrón de `RtspSource` y el contrato `BaseSource`
/ `VisualUnit` existentes. Solo stream RGB; la inferencia sigue siendo 2D en el host.

## Decisiones

| Tema | Decisión |
|---|---|
| Streams | Solo RGB (ColorCamera). Sin depth: `VisualUnit` no lo transporta y nada lo consume. |
| Conexión | IP fija / reserva DHCP vía `dai.DeviceInfo(ip)`. **Nunca autodiscovery** (falla en WSL: `X_LINK_DEVICE_NOT_FOUND`). Ver `/home/simonll4/projects/OAKD-PRO-POE.txt`. |
| SDK | `depthai>=2.24,<3` (API v2: `Pipeline` + `ColorCamera` + `XLinkOut`). Migración a v3 fuera de alcance. Import lazy dentro de la fuente. |
| Resolución/FPS | Config-driven: `resolution` (default `1080p`) y `fps` (default `10`) en `SourceSection`, solo válidos para `oak_d`. |
| Reconexión | Mismos knobs que RTSP: `reconnect_retries` (default 5), `reconnect_delay_ms` (default 1000). |
| Reloj | `SOURCE_CLOCK = "wallclock"`; `timestamp_ms = time.time() * 1000`. Habilita t_capture→alert (spec 42). |
| Despliegue | Servicio nativo en WSL (`make serve`). Imagen Docker edge de `infra/twonode/` queda para una tanda posterior. |
| Dependencia | `depthai` va al extra `edge` de `pyproject.toml` (hoy vacío). |

## Componentes

### 1. `src/eovrt_media/sources/oak_d_source.py`

Implementar `OakDSource(BaseSource)`:

- `__init__(url, source_id=None, resolution="1080p", fps=10, reconnect_retries=5,
  reconnect_delay_ms=1000, max_units=None)`. `url` = IP de la cámara (requerida).
- `__iter__`: import lazy de `depthai`; construye pipeline v2 (`ColorCamera` con
  `setResolution` según `resolution`, `setFps(fps)`, `setInterleaved(False)`,
  salida BGR por `XLinkOut` nombre `"rgb"`); conecta con
  `dai.Device(pipeline, dai.DeviceInfo(url))`; loop:
  `getOutputQueue("rgb", maxSize=4, blocking=False)` y `tryGet()`/`get()` con
  espera corta para poder chequear el stop event entre lecturas; cada frame →
  `VisualUnit(unit_id, source_id, source_type="video_frame", frame_index, width,
  height, timestamp_ms=time.time()*1000, pixel_data=frame_bgr,
  source_clock="wallclock")`.
- Reconexión: ante excepción de conexión/lectura, cerrar device, esperar
  `reconnect_delay_ms` y reintentar hasta `reconnect_retries` fallos consecutivos;
  un frame exitoso resetea el contador (igual que `RtspSource`).
- `stop()`: setea `threading.Event`. El device se abre y cierra **siempre en el hilo
  productor** (context manager dentro de `__iter__`) — nunca cerrar recursos desde
  otro hilo (misma disciplina que la trampa ZeroMQ del workspace).
- `__len__` → `raise TypeError` (fuente viva).
- `max_units` opcional para runs acotados de prueba.
- Resoluciones soportadas: `"1080p"`, `"4k"`, `"720p"` → mapa a
  `dai.ColorCameraProperties.SensorResolution`. Valor inválido → `ValueError` al
  construir la fuente (no al iterar).

### 2. `src/eovrt_media/sources/registry.py`

- `PLUGINS["oak_d"]`: `available=True`, description "OAK-D Pro PoE (RGB vía DepthAI,
  conexión por IP fija)".
- Rama `oak_d` en `create_source`: instancia `OakDSource` con los campos de
  `SourceSection` (patrón de la rama `rtsp`).

### 3. `src/eovrt_media/config/schemas.py`

- `SourceSection`: campos nuevos `resolution: str = "1080p"`, `fps: int = 10`
  (documentados como exclusivos de `oak_d`; `fps` validado > 0).
- `_check_locator`: `oak_d` exige `url` (la IP), con mensaje claro.

### 4. `pyproject.toml`

- Extra `edge = ["depthai>=2.24,<3"]`.

### 5. Config de ejemplo

`configs/runs/local/oak_d_camera.yaml` (directorio git-ignoreado; IP real ahí):

```yaml
source:
  type: oak_d
  url: "192.168.1.50"   # reserva DHCP de la OAK
  fps: 10
  resolution: 1080p
  reconnect_retries: 3
  reconnect_delay_ms: 1000
model: {ref: mock}
rate_control:
  policy: bounded_freshness
  max_staleness_ms: 1000
```

### 6. Tests (sin hardware)

- `tests/test_oak_d_source.py` — reescribir: hoy verifica `NotImplementedError`.
  Nuevo: fake del módulo `depthai` inyectado en `sys.modules` (el import es lazy,
  así que el fake se instala antes de iterar). Cubre:
  - emisión de `VisualUnit` con `source_clock="wallclock"`, `pixel_data` BGR,
    dimensiones y `frame_index` correctos;
  - `stop()` interrumpe el loop y el iterador termina limpio;
  - reconexión: N fallos < retries → sigue; fallos consecutivos > retries → error;
  - `__len__` → `TypeError`; `max_units` corta la iteración;
  - `resolution` inválida → `ValueError` en el constructor;
  - sin `depthai` instalado y sin fake → error claro (ImportError con mensaje).
- `tests/test_ingest_registry.py`, `tests/test_runs_api.py`,
  `tests/test_catalog_api.py`, `tests/test_config_deployment.py` — actualizar los
  asserts que asumen `oak_d.available == False` / 422.

### 7. Documentación

- Crear `docs/contexto/oak-d-integration.md` (referido por el stub): topología LAN,
  reserva DHCP, WSL/NAT, snippet de smoke test, knobs de config, troubleshooting
  (`X_LINK_DEVICE_NOT_FOUND` ⇒ usar IP directa).
- Actualizar menciones "hardware no disponible": `docs/implementation-status.md`,
  `docs/usage.md`, `docs/architecture.md` (media-plane) y
  `docs/operacion/30-runbook-local.md` (repo docs).

## Verificación

1. **Sin hardware (esta tanda)**: `make test` (suite completa con fakes) +
   `make lint` + `make serve` con `EOVRT_MODEL_REF=mock` y `POST /api/runs` con
   `plugin: oak_d` apuntando a una IP inexistente ⇒ el run falla limpio por
   reconexión agotada (no cuelga, no 500 en el POST).
2. **Con hardware (cuando se conecte la cámara)**: `ping <ip>` →
   `python3 -c "import depthai as dai; print(dai.DeviceInfo('<ip>'))"` → run real
   con `model: mock`: verificar `runs/<id>/detections.jsonl`, dimensiones de frame,
   `capture_wallclock_ms` monotónicamente creciente, y `POST /api/runs/<id>/stop`
   detiene en < 3 s (ventana de drenaje de 2 s + margen).

## Fuera de alcance

Depth/estéreo, inferencia on-device (la OAK solo captura), imagen Docker edge,
tracker/track_id (spec 42 §3), depthai v3, MQTT (spec 45).

## Addendum (post-implementación, mismo día)

Dos desvíos respecto del diseño original, ambos surgidos del hardware real y de la
revisión de código posterior:

1. **Knob `orientation`** (`normal` | `rotate_180` | `mirror` | `flip`, default
   `normal`): la cámara del laboratorio quedó montada invertida y la detección se
   degradaba fuerte (person 43% → 100% de frames al rotar). La rotación la hace el
   ISP de la cámara (costo cero de host). No estaba en la spec original.
2. **Endurecimientos de la revisión**: `available` del registry dinámico según
   `find_spec("depthai")`; validación de `resolution`/`orientation` en el schema
   (422 en el POST, no muerte asíncrona); rechazo de claves desconocidas en
   `ingest.config` (422); cola del device `maxSize=1` (staleness real para
   bounded_freshness); backoff de reconexión interrumpible por `stop()`;
   watchdog de stream mudo (reconexión si la cola no entrega frames);
   redacción de credenciales en logs/errores (paridad con RtspSource).
