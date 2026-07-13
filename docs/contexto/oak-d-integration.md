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
