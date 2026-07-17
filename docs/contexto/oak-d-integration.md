# OAK-D Pro PoE: integración como fuente viva (`oak_d`)

Estado: **implementado y verificado con hardware real** (2026-07-13).
Spec: `docs/superpowers/specs/2026-07-13-oak-d-source-design.md`.

Cámara del laboratorio: `DeviceId 194430105168741300`, MAC `44:a9:2c:3f:9c:1e`,
IP `192.168.1.50` (DHCP con reserva), bootloader `0.0.28`, sensores
IMX378 (color, CAM_A) + par estéreo OV9282. Solo se usa el stream **RGB**.

## La trampa que cuesta medio día: viene con IP estática, no DHCP

Las OAK PoE salen de fábrica con **IP estática link-local `169.254.1.222`**.
Enchufada al router, la cámara **se queda en esa dirección** mientras el host vive
en `192.168.1.0/24`: no hay ruta entre las dos subredes y la cámara es **invisible
al ping, al ARP y al discovery**. El síntoma engaña — parece que "no toma IP" o que
"no tiene alimentación" — pero la cámara está perfecta: es su config de flash.

Se delata así: enchufada **directo a la PC** sí aparece, porque ahí Windows también
cae a link-local (`169.254.x.x`) y quedan en la misma subred por casualidad.

**Solución (una sola vez por cámara):** grabar la config de red en modo DHCP.

```bash
# DESDE WINDOWS (ver abajo por qué), con un venv que tenga depthai>=2.24,<3:
python scripts/provision_oak_d.py --ip 192.168.1.50 --gateway 192.168.1.1
# -> power-cycle del PoE. La camara pide DHCP y toma la IP.
```

Después, **reserva DHCP por MAC** en el router (`44:a9:2c:3f:9c:1e` → `192.168.1.50`)
para que no cambie nunca.

## Dos reglas que no son negociables

**1. Se provisiona desde Windows, se usa desde WSL.**
El bootloader se alcanza por **discovery UDP broadcast**, y el NAT de WSL2 no lo deja
pasar (`Specified device not found`). En cambio el uso normal —lo que hace
`OakDSource`— es **TCP unicast** contra la IP de la cámara, y desde WSL anda perfecto
(verificado: ping 2 ms, frames a 1080p). O sea: el flasheo va desde Windows; el
media-plane corre desde WSL sin problema.

**2. No mezclar depthai v3 y v2 contra la misma cámara.**
Flashear con v3 y después abrirla con v2 la deja en estado inconsistente y **crashea
al bootear**: `Device likely crashed` + `json.exception.type_error.302: type must be
boolean, but is array`. Se recupera regrabando con v2 y haciendo un ciclo de arranque
limpio. El media-plane pinea `depthai>=2.24,<3` (extra `edge`) y
`scripts/provision_oak_d.py` **aborta** si detecta otra major.

## Topología

    Router (DHCP, 192.168.1.1)
      ├── Ethernet ──────────────── PC (WSL2, NAT hacia la LAN)
      └── Ethernet ── Inyector PoE 802.3af ── OAK-D Pro PoE (192.168.1.50)

La OAK-D Pro PoE **se alimenta solo por PoE 802.3af** (no tiene fuente aparte). Un
router hogareño no entrega PoE: hace falta **inyector o switch PoE 802.3af/at**. Los
inyectores *pasivos* de 24 V no sirven (la cámara negocia alimentación como PD).

## Config del media-plane

```yaml
source:
  type: oak_d
  url: "192.168.1.50"      # requerido: IP de la cámara
  fps: 10                   # default 10
  resolution: 1080p         # 720p | 1080p | 4k (default 1080p)
  orientation: rotate_180   # normal | rotate_180 | mirror | flip (default normal)
  reconnect_retries: 3
  reconnect_delay_ms: 1000
```

**`orientation` no es cosmético.** Si la cámara está montada invertida, el modelo
infiere sobre una escena dada vuelta y la detección se degrada mucho. Medido sobre la
cámara del laboratorio con GDINO-tiny y los prompts `cr01_cr02_v2_short`:

| | imagen invertida | `orientation: rotate_180` |
|---|---|---|
| frames con `person` detectado | 10/23 (**43 %**) | 19/19 (**100 %**) |
| confianza media de `person` | 0.44 | **0.63** |
| falsos positivos de `helmet` (pelo oscuro) | 13 | **1** |

La rotación la hace el **ISP de la cámara**, no la CPU del host: no cuesta nada.
DepthAI solo ofrece 180°/espejo/flip — **no rota 90°**; si la cámara quedara de costado
hay que montarla derecha (o meter un nodo `ImageManip`, hoy fuera de alcance).

Ejemplo completo: `configs/runs/local/oak_d_camera.yaml` (git-ignoreado). Al ser fuente
viva, `kind=live` y `rate_control.policy=bounded_freshness` se derivan solos, y
`source_clock=wallclock` habilita t_capture→alert (spec 40/42).

Robustez (revisión 2026-07-13): el plugin aparece `available: false` en el catálogo
si el SDK DepthAI no está instalado en esa build (y el POST da 4xx claro, no un run
muerto); `resolution`/`orientation` inválidas y claves desconocidas en `ingest.config`
dan **422 en el POST**; la cola del device usa `maxSize=1` (siempre el frame más
fresco — staleness honesta para `bounded_freshness`); watchdog de stream mudo (10 s
sin frames con conexión viva ⇒ reconexión); backoff de reconexión interrumpible por
`stop()`; credenciales en `url` redactadas en logs y errores, como en RTSP.

## Prefilter EN-2 y latencia

Spec: `docs/superpowers/specs/2026-07-15-oak-d-prefilter-en2-design.md`.
Estado: **implementado, default off**. Paridad exacta con EN-0 mientras
`prefilter.enabled` no se declara.

### Qué es

Un gate de personas on-device (compuerta EN-2 de la tesis, Tabla 56): un nodo
`Script` en la propia cámara reenvía el frame de video al host solo si hay
evidencia reciente de persona, con sesgo estructural a *fail-open* (el objetivo
no es detectar bien — eso es tarea del OVD en el host — sino descartar barato
lo claramente inservible sin arriesgar evidencia). El detector on-device es
`person-detection-retail-0013` (Open Model Zoo, Apache-2.0), corriendo sobre la
rama `.preview` full-FOV de la `ColorCamera`; la rama `.video` (la que hoy llega
al host) no cambia de contenido, solo se reenvía condicionalmente.

El script reenvía el frame si se cumple **cualquiera** de estas 4 reglas:

1. **persona**: hubo una detección `person` con `confidence >= confidence` en
   los últimos `keepalive_window_ms`.
2. **heartbeat**: pasaron `>= heartbeat_interval_ms` desde el último frame
   enviado (late aunque no haya nadie — mantiene vivo el watchdog del host).
3. **fail-open**: la NN dejó de responder por `>= stall_failopen_ms` (silencio
   del detector on-device) → la compuerta se abre por completo, como si no
   hubiera prefilter.
4. **warm-up**: todavía no llegó ningún resultado de la NN desde el arranque
   del pipeline.

Cada descarte se cuenta (`prefilter_dropped_no_person`) y cada corrida declara
su config efectiva y sus contadores en el bloque `prefilter` de
`summary.json` — condición no negociable de EN-2 (Tabla 57: "registrar
descartes"). **En two-node (EBE distribuido) los contadores no llegan al
summary en v1** (`counters_available: false, reason: two_node_v1`): el source
vive en Nodo A y el `RunArtifactWriter` en Nodo B, y todavía no hay canal para
transportar `prefilter_stats` por el link ZeroMQ (extensión futura, spec §11).
Por eso las corridas A/B de validación de EN-2 se hacen en single-host, donde
el registro de descartes es completo.

### Cómo activarlo

1. Bajar y compilar el blob del detector on-device:

   ```bash
   make download-prefilter-blob
   ```

   Deja `models/edge/person-detection-retail-0013_6shave.blob` (git-ignorado,
   como el resto de los pesos). Si el blob falta o está corrupto, la fuente
   falla al construirse — 422/409 en el `POST /api/runs`, nunca degrada en
   silencio a EN-0 a mitad de corrida.

2. Declarar el bloque `prefilter` en `source:` (ver ejemplo completo,
   comentado, en `configs/runs/local/oak_d_camera.yaml`):

   ```yaml
   source:
     type: oak_d
     url: "192.168.1.50"
     prefilter:
       enabled: true
       confidence: 0.25             # bajo a propósito (fail-open)
       keepalive_window_ms: 1500
       heartbeat_interval_ms: 2000
       stall_failopen_ms: 3000
   ```

`prefilter` (y `isp_scale`/`xlink_chunk_size`, ver abajo) solo son válidos con
`type: oak_d`; declararlos en `rtsp`/`video_file`/`image_folder` es 422 en el
POST.

### Latencia: `isp_scale` y `xlink_chunk_size`

Independientes del prefilter, config-driven, default = comportamiento actual:

- **`xlink_chunk_size: 0`** (default): deshabilita el particionado de paquetes
  XLink — la condición bajo la cual Luxonis mide sus propias tablas oficiales
  de baja latencia. `-1` = chunking default del device (64 KiB).
- **`isp_scale: [num, den]`** (opcional, ausente = sin escalar): reduce la
  resolución en el bloque *scaler* del ISP — hardware dedicado, sin costo de
  SHAVEs — antes de transmitir por PoE. Ej.: `[3, 4]` sobre 1080p → 1440×810.
  **Regla operativa (no está en el schema — la fuente no conoce el
  `input_spec` del adapter al validar la config): el lado corto emitido debe
  quedar `>=` el lado corto del `input_spec` del modelo OVD de la corrida.**
  Reducir por debajo de lo que el host igual va a submuestrear en
  `normalize_spatial` no pierde nada; reducir más sí puede perder evidencia
  antes de la inferencia.

Con esto se agrega `capture_to_host_ms` (percentiles p50/p95 en
`summary.json`): `dai.Clock.now() - frame.getTimestamp()`, usando el
timestamp de device ya traducido al reloj del host por el timesync de DepthAI
(error < 0.5 ms en PoE). Es puramente informativo — **no cambia el ancla del
G2A**, que sigue estampándose al leer el frame en host.

### Tuning de NIC (host, PoE)

Recomendación oficial de Luxonis para reducir la carga del Leon CSS en
dispositivos PoE — es tuning de sistema operativo, no config de la corrida:

```bash
sudo ethtool -C <iface> rx-usecs 1022
```

### Corrida A/B de validación

EN-2 exige (Tabla 57) comparación contra el flujo sin preselector antes de
usarse en experimentos que alimenten métricas de tesis. El procedimiento
manual E2E (misma escena, `prefilter.enabled` true/false, verificando tasa de
paso con y sin persona y consistencia de los contadores del summary) está
detallado en el spec §10 y se ejecuta como Task 11 del plan de implementación
(`docs/superpowers/specs/2026-07-15-oak-d-prefilter-en2-design.md`).

#### Resultados A/B (ejecutada 2026-07-15) — evidencia Tabla 57

Servicio single-host con `EOVRT_MODEL_REF=grounding-dino/gdino-tiny` (RTX 4060
Laptop 8 GB, WSL2), cámara del laboratorio (`192.168.1.50`, PoE), fuente `oak_d`
a `fps: 10`, 1080p, prompts inline `person`/`helmet`/`vest`. Escena **no
controlada**: en la corrida A hubo una persona en el FOV prácticamente todo el
tiempo; en la corrida B la escena estuvo mayormente vacía con presencia
intermitente (lo declaran los propios contadores del prefilter — ese contraste
de escena hay que tenerlo presente al leer la tabla).

| | **A — EN-0 (sin prefilter)** | **B — EN-2 (prefilter on)** |
|---|---|---|
| run_id | `run_20260715_041509_dbe_grounding_dino_6a2b1d` | `run_20260715_041740_dbe_grounding_dino_4b1b46` |
| duración | ~96 s | ~35 s |
| `prefilter.enabled` | `false` | `true` (defaults: conf 0.25, keepalive 1500 ms, heartbeat 2000 ms, stall 3000 ms) |
| frames vistos por la compuerta | n/a (todo pasa) | **236** (`seen`) |
| `units_processed` (frames inferidos por GDINO) | **277** | **19** |
| descartados on-device | 0 | **206** (`dropped_no_person`, 87 % de lo visto) |
| `forwarded_by_reason` | n/a | person 18, heartbeat 10, warmup 2, failopen 0 |
| aritmética contadores | n/a | `seen == forwarded + dropped_no_person` (236 = 30 + 206) ✓; `stats_stale: false` ✓ |
| `fps_effective` (inferencia) | 2.88 | 0.54 |
| `capture_to_host` p50 / p95 (ms) | 88.0 / 107.0 (n=277) | 108.7 / 236.7 (n=19) |
| detecciones GDINO | 355 (person 276, helmet 42, vest 37) | 52 (person 18, helmet 16, vest 18) |
| `errors.jsonl` | vacío | vacío |
| status | `stopped` (202 al POST /stop) | `stopped` (202 al POST /stop) |

Lecturas:

- **La compuerta hace exactamente su trabajo**: con escena mayormente vacía, el
  87 % de los frames se descarta en la cámara y al host llega ~1 frame por
  `heartbeat_interval_ms` (10 heartbeats en ~25 s de tramos vacíos ≈ 1 cada
  2 s, como está configurado) más los frames con evidencia de persona.
- **Regla de reenvío por persona + heartbeat, sin caída de la NN on-device**:
  los 18 frames reenviados por regla `person` coinciden en conteo total con
  las **18 detecciones `person`** que reportó GDINO en B; es una coincidencia
  de agregados (18 = 18 en total), no una correspondencia verificada
  frame-a-frame — el matching por `unit_id` entre lo que la compuerta marcó
  `person` y lo que GDINO efectivamente confirmó no se hizo en esta corrida,
  así que no se puede afirmar cobertura 1:1 en el sentido estricto. Lo que sí
  queda demostrado es que la regla de reenvío por persona y el heartbeat
  operan como está especificado. `failopen: 0` indica que la red de seguridad
  por *stall* (silencio de la NN on-device) nunca se activó en esta corrida —
  no hay evidencia de fail-open ejercitado, solo de que no hizo falta — y
  `warmup: 2` (los primeros frames pasan siempre, por diseño).
- **`capture_to_host` comparable**: p50 88 vs 109 ms (mismo orden; el p95 de B
  sale de solo 19 muestras y varios de sus frames son heartbeats que esperan
  en cola de la compuerta — no es señal de degradación del link).
- **En A, GDINO es el cuello** (2.88 fps efectivos sobre 10 fps de cámara, GPU
  saturada); en B la GPU queda ociosa durante los tramos vacíos — el ahorro de
  cómputo que EN-2 promete para escenas de baja ocupación.
- **Brecha 30 reenviados vs 19 procesados por GDINO**: la compuerta forwardeó
  30 frames (`forwarded_by_reason` suma 18+10+2+0), pero `units_processed` en
  B es 19 — una diferencia de 11 frames que no es pérdida de la compuerta,
  sino de transporte/cierre: en ambos stops el run se detuvo con frames en
  vuelo (ver nota operativa de la ventana de drenaje, abajo) y parte de esos
  11 frames se descartaron host-side por `bounded_freshness`/cola mientras
  GDINO todavía estaba cargando. El mismo patrón aparece en A: su productor
  también leyó más frames de los que GDINO llegó a procesar (fuente a
  `fps: 10` durante ~96 s implica ~960 frames leídos contra 277
  `units_processed`), así que la brecha no es un artefacto exclusivo de B ni
  invalida los contadores de la compuerta.
- **Falsos negativos no medidos**: si el detector on-device se perdió alguna
  persona dentro de los 206 frames descartados (`dropped_no_person`), estos
  contadores no lo pueden detectar — y como la escena de A difirió de la de B
  (A tuvo presencia casi constante), A tampoco sirve de referencia para
  estimarlo. Queda pendiente una corrida con escena controlada y GT para
  medir la tasa de falsos negativos de la compuerta.
- Nota operativa: en ambos stops el consumer registró "ventana de drenaje
  agotada tras request_stop() sin END del productor" y forzó la salida; los
  artefactos quedaron completos y `errors.jsonl` vacío en ambos, pero el
  productor `oak_d` tarda más que la ventana de drenaje en emitir su END —
  esta es la causa principal de la brecha 30→19 señalada arriba.

## Verificación E2E con hardware (ejecutada 2026-07-13)

Servicio con `EOVRT_MODEL_REF=mock`, run de 20 unidades contra la cámara real:

| Invariante | Resultado |
|---|---|
| `source_type` / `source_clock` | `oak_d` / **`wallclock`** |
| Unidades | 20 procesadas, **0 fallidas**, `errors.jsonl` vacío |
| Frames | 1920×1080 BGR uint8, ~10.6 fps reales (coincide con `fps: 10`) |
| `capture_wallclock_ms` | **estrictamente creciente** |
| G2A | `computed`, p95 = 12.7 ms (presupuesto 50–250 ms) |
| Previews | 20 renderizadas |
| **Stop de fuente viva** | run infinito → `POST /stop` → **202**, `stopped` en **3.0 s** |

Repetir con:

```bash
EOVRT_MODEL_REF=mock make serve
curl -X POST http://localhost:8080/api/runs -H "Content-Type: application/json" -d '{
  "ingest": {"plugin": "oak_d", "config": {"url": "192.168.1.50", "fps": 10}},
  "prompts": {"set_inline": {"id": "demo", "classes": [{"id": "person",
    "phrasings": {"default": ["person"]}}]}, "active_ids": ["person"]},
  "run": {"max_units": 20}
}'
```

## Troubleshooting

- **No aparece en la LAN, ni en el ping ni en el discovery** → casi seguro sigue en su
  IP estática de fábrica. Enchufala directo a la PC: si ahí aparece en `169.254.1.222`,
  es exactamente eso. Corré `scripts/provision_oak_d.py`.
- **`Device likely crashed` / `json.exception.type_error.302`** → se mezclaron SDK v3 y
  v2. Regrabá con v2 (`scripts/provision_oak_d.py`) y hacé power-cycle.
- **`Specified device not found` desde WSL** → el discovery por broadcast no cruza el
  NAT. Las operaciones de bootloader van desde Windows; el media-plane (TCP unicast)
  no necesita discovery.
- **Sin señales de vida** → revisar que el inyector sea **802.3af** (no pasivo) y que
  el puerto `DATA IN` vaya al router y el `PoE OUT` a la cámara (invertirlos no la
  alimenta).
- **`USB protocol not available` al importar depthai** → irrelevante en PoE (la
  conexión es TCP, no USB).
