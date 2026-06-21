# Diseño: EBE completo — fuente viva (RTSP) y topología de dos nodos

> **Estado**: diseño aprobado, pendiente de implementación.
> **Fecha**: 2026-06-21
> **Alcance**: completar el Escenario B (EBE) del plano de medios, dejándolo
> funcional y testeado tanto en un solo host como en dos nodos.

## Contexto

El andamiaje de despliegue (spec `2026-06-21-plano-medios-topologia-despliegue-andamiaje-design.md`)
dejó el Escenario A (DBE / fuente pulleable) completo y funcional en un host, y dejó
**declarados pero no implementados** los componentes que faltan para EBE:

- La política `bounded_freshness` (head-drop + `max_staleness_ms`) **ya existe** en
  `MemoryTransportAdapter`.
- `source.kind=live` y la derivación de política **ya existen** en el loader.
- Faltan: la **fuente viva** (`RtspSource`), los **timestamps de captura** que hacen
  significativa la métrica de frescura, y el **transporte de red** (`NetworkTransportAdapter`
  ZeroMQ) para la topología de dos nodos.

Este diseño cierra esos huecos. La premisa de la arquitectura no cambia: **la topología no
cambia los contratos ni la lógica conceptual de los componentes; solo cambia el adaptador
de comunicación entre productor y consumidor.**

## Estrategia de implementación: dos fases

Una sola spec cubre EBE completo, pero la implementación se hace en dos fases para validar
incrementalmente:

- **Fase 1 — EBE en un solo host**: `RtspSource` + timestamps de captura, consumido por el
  pipeline actual con `MemoryTransportAdapter` y política `bounded_freshness`. Se valida que
  la fuente viva, el head-drop y la frescura funcionan de punta a punta sin red.
- **Fase 2 — EBE en dos nodos**: `NetworkTransportAdapter` (ZeroMQ REQ/REP + heartbeat),
  serialización de `NormalizedUnit`, y los comandos CLI `run-producer` / `run-consumer`. Se
  habilita cuando la Fase 1 funciona y la infraestructura de red está lista. Esta fase tiene
  una sub-fase final de **containerización (2c)**: empaquetar Nodo A y Nodo B como imágenes
  Docker separadas (ver "Decisión: containerización con Docker").

El diseño de la Fase 1 anticipa lo que necesita la Fase 2 (timestamps precisos, payload
serializable) para no retocar contratos después.

## Arquitectura — flujos por escenario

```
DBE single-host (HOY — completo)
───────────────────────────────
ImageFolderSource / VideoFileSource
  → RateGate(deterministic)
  → Normalizer
  → MemoryTransportAdapter
  → Inference → Postprocess → Artifacts


EBE single-host (FASE 1)
────────────────────────
RtspSource  ←── NUEVO
  → RateGate(bounded_freshness)
  → Normalizer
  → MemoryTransportAdapter (sin cambios)
  → Inference → Postprocess → Artifacts


EBE two-node (FASE 2)
─────────────────────
NODO A                              NODO B
──────                              ──────
RtspSource                          NetworkTransportAdapter (cliente REQ)
  → RateGate(bounded_freshness)       → Inference
  → Normalizer                        → Postprocess
  → NetworkTransportAdapter           → Write artifacts
    (servidor REP + buffer)
```

El `pipeline.py` actual ya está dividido en `_producer_thread` + loop de consumidor. Para dos
nodos, esos dos lados corren en procesos/hosts distintos conectados por ZeroMQ en lugar de una
cola en memoria. El comando `eovrt-media run` existente sigue sirviendo para todo single-host
(DBE y EBE).

## Componente 1: fuentes vivas

### `RtspSource`

Implementa `BaseSource`. Internamente usa `cv2.VideoCapture(url)`, que funciona con cualquier
URL RTSP estándar (EZVIZ, Hikvision, Dahua, etc.).

Diferencias respecto a `VideoFileSource`:

| | `VideoFileSource` | `RtspSource` |
|---|---|---|
| Fuente | archivo local | URL RTSP de red |
| Looping | posible | nunca |
| Timestamp | índice/fps calculado | reloj de pared al capturar |
| Reconexión | no aplica | sí, con backoff configurable |
| `__len__()` | frames totales (finito) | `-1` (indefinido) |

**Apertura de la captura**: `RtspSource` delega la apertura a un método `_open_capture(url)`
que devuelve un `cv2.VideoCapture`. Esta indirección permite que los tests monkeypatcheen la
apertura para usar un archivo local en lugar de una URL de red real.

**Timestamp de captura**: `timestamp_ms = time.time() * 1000` tomado justo antes de cada
`cap.read()`. Esto es lo que hace significativo `max_staleness_ms` en `bounded_freshness` — el
frame sabe cuándo fue capturado, y el consumidor puede descartar frames obsoletos por edad real.

**Reconexión**: si `cap.read()` devuelve `(False, _)`, `RtspSource` reintenta abrir la captura
hasta `reconnect_retries` veces, esperando `reconnect_delay_ms` entre intentos. Si agota los
reintentos, propaga una excepción que el `_producer_thread` captura y registra en `errors.jsonl`,
terminando la corrida limpiamente (no cuelga).

**Iteración infinita**: `RtspSource` no tiene fin natural. La corrida termina por
`run.max_units` (límite explícito) o por desconexión agotada. `__len__()` devuelve `-1` para
señalar longitud indefinida. La implementación debe ajustar `pipeline.py` para mapear un
`len()` negativo a `total=None` en la barra de progreso (hoy pasa `source_count` directo, que
con `-1` mostraría una barra inválida).

Config:
```yaml
source:
  type: rtsp
  url: "rtsp://admin:password@192.168.1.100:554/stream1"
  reconnect_retries: 5
  reconnect_delay_ms: 1000
```

### `OakDSource` (declarado, no implementado)

La cámara OAK-D Pro PoE no usa RTSP sino el SDK DepthAI (API propia). Se declara como fuente
separada y se deja para una iteración posterior, cuando se definan los requisitos exactos
(solo RGB, o también profundidad).

```python
class OakDSource(BaseSource):
    """Fuente OAK-D Pro PoE vía DepthAI SDK — declarada, no implementada.

    Requires: pip install depthai
    Produces: RGB frames via dai.Pipeline XLinkOut.
    Ver docs/contexto/oak-d-integration.md cuando se implemente.
    """

    def __iter__(self):
        raise NotImplementedError(
            "OakDSource (source.type=oak_d) requiere depthai instalado y configurado. "
            "Declarada para la cámara OAK-D Pro PoE; pendiente de implementación."
        )

    def __len__(self) -> int:
        return -1
```

Registrada en el factory de sources con `type: oak_d`.

## Componente 2: `NetworkTransportAdapter` (Fase 2)

### Protocolo

ZeroMQ REQ/REP con pull model: Nodo B pide, Nodo A responde. Sin broker, sin estado compartido.

```
Nodo A (REP server)          Nodo B (REQ client)
───────────────────          ──────────────────
                    ←── REQUEST ───
buffer.pop_oldest() ───  FRAME ───→   inference
                    ←── REQUEST ───
buffer.pop_oldest() ───  FRAME ───→   inference
                    ←── REQUEST ───
(producer terminó)  ───   END  ───→   consumer loop sale
```

**Heartbeat**: independiente del flujo de frames, sobre un socket PUSH/PULL separado. Cada
`heartbeat_interval_ms` ambos nodos envían `HEARTBEAT`. Si Nodo A no recibe heartbeat de Nodo B
en `heartbeat_timeout_ms`, asume que Nodo B se cayó y termina limpiamente en lugar de producir
al vacío.

### Dos roles del mismo adaptador

`NetworkTransportAdapter` recibe un parámetro `role`:

| Role | Socket ZMQ | Comportamiento |
|---|---|---|
| `producer` | REP — `bind` al endpoint | Espera REQUEST, responde con frame del buffer |
| `consumer` | REQ — `connect` al endpoint | Envía REQUEST, bloquea hasta recibir frame o END |

El buffer del lado productor es el mismo `deque` con head-drop de `bounded_freshness`. ZeroMQ es
solo el canal entre los dos lados; **no reemplaza la política de rate control**.

### Serialización de `NormalizedUnit`

`NormalizedUnit` tiene metadata (strings/ints/floats) + un payload numpy. Formato de wire:

```
[4 bytes big-endian: header_len]
[header_len bytes: msgpack({unit_id, source_id, run_id, orig_width, orig_height,
                            frame_index, timestamp_ms, payload_format,
                            target_size, transform: {scale_x, scale_y, pad_x, pad_y}})]
[resto: payload numpy crudo (ndarray.tobytes()); el shape y dtype se reconstruyen
        desde target_size y payload_format]
```

Mensajes de control: `b"REQUEST"`, `b"END"`, `b"HEARTBEAT"` — bytes cortos sin header.

Con `payload_format=uint8_rgb` el payload de un frame 640×640×3 es ≈1.2 MB; a 5 fps son ~6 MB/s,
sin problema en LAN gigabit. El cast a float + normalización mean/std ocurre en el Nodo B (pegado
a la GPU), no viaja por la red.

### Config para dos nodos

```yaml
topology:
  mode: two_node

transport:
  backend: network
  endpoint: "tcp://192.168.1.10:5555"   # IP de Nodo A
  payload_format: uint8_rgb
  heartbeat_interval_ms: 1000
  heartbeat_timeout_ms: 5000
```

### Dependencia

Se agrega `pyzmq` a las dependencias del proyecto en `pyproject.toml`. Es una dependencia pura
de pip (bindings + libzmq embebida), sin pasos de build adicionales.

## Componente 3: CLI y configuración

### Comandos CLI

`eovrt-media run` **no cambia** — sigue sirviendo para todo single-host (DBE y EBE).

Dos comandos nuevos para dos nodos:

```bash
# Nodo A: ingesta + normalización + servidor ZeroMQ
eovrt-media run-producer --config config.yaml

# Nodo B: cliente ZeroMQ + inferencia + artefactos
eovrt-media run-consumer --config config.yaml
```

`run-producer` corre el `_producer_thread` actual con un `NetworkTransportAdapter(role=producer)`.
`run-consumer` corre el loop de consumidor actual con un `NetworkTransportAdapter(role=consumer)`.
Ambos reusan la lógica de `pipeline.py`; la refactorización extrae las dos mitades en funciones
reutilizables sin cambiar su comportamiento.

### Cambios en el schema de configuración

**`SourceSection`** gana campos para RTSP:

```yaml
source:
  type: rtsp                 # nuevo valor válido (se quita el gate NotImplementedError)
  url: "rtsp://..."          # nuevo
  reconnect_retries: 5       # nuevo
  reconnect_delay_ms: 1000   # nuevo
```

**`TransportConfig`** gana campos de heartbeat:

```yaml
transport:
  heartbeat_interval_ms: 1000   # nuevo
  heartbeat_timeout_ms: 5000    # nuevo
```

### Derivación automática

Cuando `source.type=rtsp`, el loader deriva (si no están explícitos):
- `source.kind = live`
- `rate_control.policy = bounded_freshness`

Es una regla explícita en el loader, análoga a la derivación `pulleable → deterministic`
existente, y se refleja en el `effective_config.yaml`.

### Gates que cambian

- `source.type=camera` → renombrado a `oak_d`; sigue lanzando `NotImplementedError`.
- `source.type=rtsp` → implementado; se elimina su gate.
- `topology.mode=two_node` + `transport.backend=network` → se elimina el gate al implementar
  la Fase 2. Hasta entonces sigue gateado.

## Manejo de errores

- **RTSP desconectado**: reintentos con backoff; al agotarse, excepción → `errors.jsonl` →
  corrida termina limpiamente.
- **Buffer vacío al REQUEST (dos nodos)**: el servidor (Nodo A) espera hasta tener un frame
  disponible antes de responder (mismo comportamiento que `bounded_freshness` en memoria).
- **Nodo B caído**: detectado por timeout de heartbeat en Nodo A → termina limpiamente.
- **Nodo A caído**: el `request()` del consumidor con timeout → reintento de conexión o
  terminación con error registrado.

## Estrategia de testing

No se requiere hardware (cámara) ni dos máquinas para la suite.

### `RtspSource`
`_open_capture` se monkeypatchea para devolver un `cv2.VideoCapture` sobre un archivo de video
local. Verifica: emisión de frames, timestamps de captura crecientes y > 0, `kind=live`,
`max_units`, y la lógica de reconexión (mock que falla N veces antes de conectar). ~8 tests.

### `OakDSource`
Un test: `__iter__` lanza `NotImplementedError`. 1 test.

### Serialización de `NormalizedUnit`
Round-trip metadata + payload numpy para cada `payload_format` soportado; mensajes de control
(`REQUEST`/`END`/`HEARTBEAT`) se serializan y reconocen. ~4 tests.

### `NetworkTransportAdapter`
ZeroMQ en loopback (`tcp://127.0.0.1:PORT`) con threads en el mismo proceso — no requiere dos
máquinas. Se agrega `network` como tercer caso al `TestTransportContract` parametrizado existente
(backend-agnóstico). Tests adicionales: heartbeat timeout, reconexión de Nodo B ante caída de
Nodo A. ~8 tests.

### CLI `run-producer` / `run-consumer`
Test de integración: subprocess de ambos comandos en loopback; los artefactos del Nodo B son
equivalentes a los de un `run` single-host con la misma fuente determinista. ~3 tests.

### Config
Derivación `rtsp → live → bounded_freshness`, gating de `oak_d`, validación de `two_node` +
`network`. ~4 tests.

| Módulo | Tests nuevos (aprox.) |
|--------|-----------------------|
| `RtspSource` | 8 |
| `OakDSource` | 1 |
| Serialización `NormalizedUnit` | 4 |
| `NetworkTransportAdapter` | 8 |
| CLI `run-producer`/`run-consumer` | 3 |
| Config (derivación rtsp, two_node) | 4 |

## Decisión: containerización con Docker

**Decisión**: dockerizar el servicio, pero **solo al entrar en la Fase 2 (dos nodos)**, como
sub-fase final (2c). **No** dockerizar la Fase 1.

### Por qué Docker sí vale la pena (en Fase 2)

El diseño de dos nodos ya separa responsabilidades que mapean directamente a dos imágenes con
dependencias muy distintas. Docker convierte esa separación lógica en separación real de
artefactos de despliegue:

| | Nodo A (edge) | Nodo B (GPU) |
|---|---|---|
| Dependencias | OpenCV + pyzmq + pydantic | torch + CUDA + transformers + ultralytics |
| Tamaño de imagen | ~300 MB | varios GB |
| Hardware objetivo | máquina chica cerca de las cámaras | servidor con GPU |
| Acceso externo | red local / RTSP | ninguno |

Hoy ambos nodos comparten un `pyproject.toml` monolítico: el Nodo A arrastra PyTorch y CUDA sin
usarlos. Con imágenes Docker separadas (o un multi-stage build con extras opcionales por nodo),
el edge instala solo lo que usa. Beneficios concretos:

- **Reproducibilidad real** entre las máquinas de despliegue y el entorno de desarrollo —
  resuelve de paso la fragilidad conocida del venv al mover el proyecto.
- **Despliegue de dos nodos reproducible**: un `docker-compose` con servicios `node-a` y
  `node-b` y una red puente para el canal ZeroMQ.

### Por qué NO en Fase 1

La Fase 1 valida `RtspSource` + `bounded_freshness` de punta a punta en un solo host. Meter
Docker ahí agrega una capa de depuración ("¿es mi código o el contenedor?") justo cuando se
busca feedback rápido. Un venv local con instalación editable es lo correcto para esa fase.

### Fricciones a tener en cuenta al llegar a 2c

- **GPU passthrough**: el Nodo B necesita `nvidia-container-toolkit` y `--gpus all`. En **WSL2**
  el stack CUDA-en-Docker depende del driver del host Windows, no del contenedor — resoluble,
  pero requiere setup dedicado.
- **Cámaras**: RTSP (EZVIZ) es solo acceso de red — el contenedor solo debe estar en la LAN.
  La OAK-D Pro PoE vía DepthAI puede requerir acceso a dispositivos/red específico que complica
  el contenedor; coincide con que su adaptador ya se difirió.
- **Builds pesados**: las imágenes con PyTorch+CUDA son grandes y lentas de construir; iterar
  sobre el código dentro de Docker es más lento que con un venv editable local.

### Acción para el plan de implementación

El plan de la Fase 2 debe incluir 2c como sub-fase final, **después** de que el `NetworkTransportAdapter`
funcione en loopback local: dos `Dockerfile` (o uno multi-stage), un `docker-compose.yml` con
`node-a`/`node-b` y red puente, y documentación de despliegue. La separación de imágenes por
nodo debe influir en cómo se estructuran las dependencias opcionales en `pyproject.toml`
(p. ej. extras `edge` y `gpu`).

## Lo que NO cambia (núcleo defendible)

- Contratos semánticos: `VisualUnit`, `NormalizedUnit`, `RawDetection`, `DetectionEvent`.
- Lógica conceptual de cada componente del pipeline.
- Contrato de salida del plano: el evento de percepción normalizado.
- La política de rate control y su semántica (`deterministic` / `bounded_freshness`).
- El comando `eovrt-media run` y todo el camino DBE single-host.

## Restricciones globales

- Python 3.11+, Pydantic v2, OpenCV, ZeroMQ (`pyzmq`).
- TDD: tests primero, implementación después.
- Sin `Co-Authored-By` en los commits.
- Los gates de features no implementadas (`oak_d`, `two_node` antes de Fase 2) fallan explícito,
  nunca con fallback silencioso.
