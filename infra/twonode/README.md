# Split two-node EBE (Nodo A edge + Nodo B GPU)

Despliegue Docker de la topología EBE: **Nodo A** (edge, sin GPU: ingesta + rate
control + normalización + servidor ZeroMQ) y **Nodo B** (GPU: inferencia +
postproceso + artefactos). Un run por `up`: ambos contenedores son procesos batch
que terminan al agotar el stream — no son servicios de larga vida (eso es el DBE
de `infra/docker-compose.yml`). Nodo B es el dueño del `run_id` y de `runs/`.

Equivalencia validada (gate 2026-06-24): mAP idéntico DBE vs EBE; JPEG q90 con
pérdida marginal (solo vests limítrofes).

## Single-host (smoke / demo)

```bash
cd infra/twonode
docker compose build            # eovrt/media-plane-edge + eovrt/media-plane
docker compose up               # corre el run de configs/two_node_{a,b}.yaml
# Nodo B escribe runs/<run_id>/ en el runs/ del repo (montado).
docker compose down
```

Default: `model.ref: mock` + `max_units: 20` (sin GPU; comentar el bloque
`deploy.resources` de node-b si el host no tiene nvidia-container-toolkit).
Para un run real: cambiar `model.ref` a `yoloe/yoloe-26s` en AMBAS configs
(el ref debe coincidir — Nodo A lo usa para el input_spec de normalización).

## Dos hosts (edge + GPU por LAN)

1. Host edge: `docker compose -f docker-compose.node-a.yml up`
2. Host GPU: editar `configs/two_node_b.yaml` → `endpoint: tcp://<ip-edge>:5555`
   y `heartbeat_endpoint: tcp://<ip-edge>:5556`, después
   `docker compose -f docker-compose.node-b.yml up`

## Fallas (comportamiento esperado)

- **Muere el Nodo A a mitad de corrida** → el Nodo B corta con error explícito
  dentro de `transport.request_timeout_ms` (default 10s) y exit != 0. Sin
  reconexión automática: relanzar el run.
- **Muere el Nodo B** → el Nodo A corta por heartbeat timeout
  (`transport.heartbeat_timeout_ms`, default 5s).

## Fuentes

`image_folder` (dataset montado en `/datasets`), `video_file`, `rtsp`. La cámara
**OAK-D Pro PoE** (`source.type: oak_d`) está declarada con contrato de config
(`url` = IP del dispositivo PoE o null para autodescubrimiento; fuente live sin
`len()`, como rtsp) pero NO implementada — requiere DepthAI y el hardware.

## Seguridad (riesgo aceptado)

Los puertos ZeroMQ (5555 datos, 5556 heartbeat) **no tienen autenticación ni
cifrado**: cualquiera con acceso de red puede inyectar frames o consumir el
stream. Aceptado para la LAN de laboratorio del proyecto académico. No publicar
esos puertos fuera de la LAN; revisar esta decisión si el despliegue cambia.

## Ejecutado y verificado (2026-07-06)

**Imágenes construidas** (`docker compose build`):
- `eovrt/media-plane-edge:latest` — 245MB content size / 970MB disk usage (sin torch, cumple el límite de "no >10GB").
- `eovrt/media-plane:latest` — 4.65GB content size / 13.2GB disk usage (con CUDA/torch; sin límite exigido por el criterio).

**Run mock end-to-end** (`docker compose up --abort-on-container-exit`, `max_units: 20`, dataset `construction_site_safety/valid/images`):
corrido dos veces. Ambas veces Nodo A sirvió las 20 units y salió exit 0; Nodo B
escribió `runs/<run_id>/` con `summary.json` completo (`units_processed: 20`,
`units_failed: 0`, `total_detections: 102`) y `detections.jsonl` con 20 líneas.
Nota: el `summary.json` no tiene un campo `status` explícito — el estado exitoso
se infiere de `units_failed: 0` + `errors.jsonl` vacío + `finished_at` presente.

*Caveat observado*: el exit code de Nodo B fue no determinístico entre corridas
(0 en una, 137/SIGKILL en la otra) aunque el resultado escrito a disco fue
idéntico y correcto en ambos casos. Causa: `--abort-on-container-exit` dispara
en cuanto Nodo A termina (su rol es solo servir frames, termina antes que Nodo B
cierre transporte/artefactos) y envía SIGTERM/SIGKILL a Nodo B sin esperar su
apagado natural — una carrera de docker compose, no un bug del pipeline (los
artefactos siempre se completan antes de que el proceso muera). No bloqueante
para el criterio de la fase; si se quiere un exit code determinístico habría que
desacoplar Nodo A de `abort-on-container-exit` (p.ej. `depends_on` con
`restart: "no"` y esperar solo a Nodo B) — diferido, fuera de alcance de Fase 2.

**Caso de falla — matar Nodo A a mitad de corrida** (`max_units: 200` temporal,
114 imágenes disponibles en el dataset montado; `docker compose kill -s SIGKILL node-a`
inmediatamente después de `up -d`, sin esperar):
Nodo B detectó la caída y cortó en ~13s (dentro de `request_timeout_ms=10000` +
margen) con exit code 1 y el mensaje `Nodo A no respondió en 10000 ms — ¿murió el
nodo edge? La corrida se aborta (sin reintento automático).` — **criterio de
aceptación del hardening cumplido**. `max_units` restaurado a 20 en ambos configs
al terminar.

**Run real con GPU (Step 4, opcional)**: no ejecutado — no hay GPU/pesos
disponibles en este entorno.

## Visibilidad en la consola web (2026-07-06, rebuild post-fixes)

Tras implementar la spec `e-ovrt_experimental-setup/docs/superpowers/specs/2026-07-06-webconsole-twonode-visibility-design.md`
(finalización garantizada de `run_node_b`, `status: running`+`live` en el disk-scan
del servicio, ownership two-node en `reconcile_orphan_runs`), se reconstruyeron
ambas imágenes (`docker compose build`, invalida la capa de `pip install` porque
el Dockerfile copia `src/` antes del `RUN pip install` — ~11min, igual que el
primer build) y se repitieron los tres escenarios contra un servicio media-plane
real (`make serve`, mock) + el BFF de la consola (`eovrt_webconsole`) apuntándole:

- **Run mock end-to-end**: ahora `summary.json` tiene `status: "succeeded"`,
  `error: null` explícitos (antes ausentes). La consola (`GET /api/runs` del BFF)
  lo muestra `succeeded`, `live: false`, `topology: "two_node"`.
- **Caso de falla** (kill `node-a` a mitad de corrida): la consola mostró la
  transición en vivo — `running` (t=2-4s) → `failed` (t=6s) — con
  `summary.error` = `"Nodo A no respondió en 10000 ms — ¿murió el nodo edge? La
  corrida se aborta (sin reintento automático)."`, sin intervención manual.
- **Reconciliación durante un run en vuelo**: se capturó un run two-node recién
  arrancado (directorio con `effective_config.yaml`, sin `summary.json` aún) y se
  pausó el contenedor `node-b` (`docker compose pause`) para congelarlo en ese
  estado sin ambigüedad de timing. Se reinició el servicio media-plane (dispara
  `reconcile_orphan_runs()` en el arranque) — el run siguió sin `summary.json`
  después del restart (prueba directa de que NO fue estampado `interrupted`) y la
  consola lo mostró `running` correctamente. Se despausó `node-b`: el run terminó
  solo, `status: "succeeded"`, `units_processed: 114`.

Los tres escenarios de la spec quedaron validados de punta a punta (docker →
servicio → BFF de la consola). `max_units` restaurado a 20 en ambos configs;
sin contenedores ni procesos de prueba corriendo al terminar.
