# Media-Plane como Servicio de Inferencia — Diseño (Spec A)

- **Fecha:** 2026-07-01
- **Estado:** aprobado para escribir plan de implementación
- **Repo:** `e-ovrt_media-plane`
- **Relación:** fundación de la consola web (Spec B, en
  `e-ovrt_experimental-setup/docs/superpowers/specs/2026-07-01-webconsole-design.md`,
  que se reescribe como cliente de este servicio).

## 1. Propósito y pivote

El media-plane deja de ser una **CLI batch** y pasa a ser un **servicio de inferencia
desplegable en contenedores**: carga pesos una vez, queda esperando, se le configuran
sesiones (fuente + modelo + prompts + parámetros), **ingiere frames por su adaptador de
ingesta visual, infiere y produce salida** (detecciones + telemetría + artefactos).

Esto alinea con la dirección ya documentada del proyecto:
- Las fuentes visuales son **externas al plano**; el primer componente interno es el
  **adaptador de ingesta visual** (DBE y EBE convergen en `VisualUnit`).
- Topología EBE: Nodo A (edge: ingesta+rate+norm) / Nodo B (GPU: inferencia+post),
  corte tras normalización por ZeroMQ.
- Cargar pesos **una vez al arrancar** (el load es caro) y servir múltiples corridas sin
  re-cargar. Un modelo por instancia; cambiar de modelo se resuelve por despliegue, no por
  código (ver §4).

**El CLI se elimina.** La consola y otros clientes hablan con el servicio por HTTP/WS.

## 2. Decisiones de diseño (cerradas)

| Decisión | Resolución |
|---|---|
| Rol del media-plane | Servicio de inferencia persistente (no CLI) |
| Modelo ↔ servicio | **Fijo por instancia**, cargado al arrancar desde env/config. **Cambiar de modelo = reiniciar/redeploy** el contenedor. **Sin recarga in-process** (evita líos de memoria CUDA). Un run activo a la vez (1 GPU) |
| Ingesta | Dentro del servicio, vía **adaptador de ingesta visual** con plugins (dataset/video → bounded; RTSP/cámara → live). OAK-D = slot no disponible |
| Quién conecta la fuente | El servicio (plugin de ingesta). La consola **solo selecciona** plugin+config, prompts, params — **no empuja frames** (el modelo lo define el despliegue) |
| Corte crudo/normalizado | Detalle **interno** del split EBE (no expuesto al cliente); se mantiene "corte tras normalización" |
| Contrato externo | HTTP/REST (control) + WebSocket (telemetría/detecciones) + API de artefactos |
| Prompts | La consola resuelve el prompt set y lo envía **inline** al crear el run; el servicio no necesita montar `experimental-setup` |
| Despliegue Fase 1 | **Contenedor único DBE** (todo el pipeline en una imagen, un host GPU) |
| Despliegue Fase 2 | Split EBE en dos imágenes (edge sin GPU / GPU) + ZeroMQ |
| CLI | Eliminado |

## 3. Arquitectura

### 3.1 Contrato externo (hacia la consola / clientes)

```
Cliente (consola)  ──HTTP──▶  API de control      (crear/parar/consultar sesión)
                   ◀─WS────   stream de sesión     (telemetría + detecciones en vivo)
                   ──HTTP──▶  API de artefactos    (summary, detections.jsonl, annotated.mp4, previews)
                   ──HTTP──▶  API de catálogos      (modelos, plugins de ingesta, datasets)
```

El **modelo no se elige por request**: es el que la instancia cargó al arrancar. Un run
compone ingesta + prompts + params sobre ese modelo.
- `GET /api/model` — modelo cargado por esta instancia (ref, device, thresholds).
- `POST /api/runs` — crea y arranca un run: `{ ingest: {plugin, config},
  prompts: {set_inline, active_ids}, run: {stride, max_units, save_annotated_video, ...} }`.
  Valida con el loader/schemas Pydantic existentes. Si ya hay un run activo → `409 busy`
  (o cola de un solo slot, opcional). Devuelve `run_id`.
- `POST /api/runs/{id}/stop` — detiene (imprescindible para fuentes live).
- `GET /api/runs/{id}` — estado (`running/succeeded/failed/stopped`) + summary (parcial si activo).
- `GET /api/runs` — run activo + historial.
- `WS /api/runs/{id}/stream` — progreso (units/total si bounded), FPS, latencia p95,
  GPU mem, detecciones por label, errores, tail de log.
- `GET /api/runs/{id}/detections?page=`,
  `GET /api/runs/{id}/artifacts/{annotated.mp4|previews/*}` (range requests para video).
- `GET /api/catalog/{ingest-plugins,datasets}` — el servicio **posee** estos catálogos (la
  ingesta vive en él). El modelo disponible se consulta en `GET /api/model`. Los prompt
  sets y manifiestos son del lado declarativo (consola/exp-setup).
- `GET /healthz` (proceso vivo), `GET /readyz` (modelo cargado) — para el contenedor.

### 3.2 Pipeline interno (reusa lo existente)

```
Adaptador de ingesta visual (plugin) → RateGate → Normalizador espacial
        → [corte EBE: aquí, en Fase 2] → Adaptador de detección (modelo) → Postproceso
        → Sinks (detections.jsonl, metrics, errors, annotated.mp4, previews, summary)
```

- **Ingesta:** los `sources/` actuales (`ImageFolderSource`, `VideoFileSource`,
  `RtspSource`, `OakDSource`-stub) se formalizan como **registro de plugins de ingesta**
  detrás del adaptador de ingesta visual; todos emiten `VisualUnit`.
- **Modelo:** `create_adapter` + `adapter.load()` existentes, invocados **una vez al
  startup** del servicio (desde `MODEL_REF`). Sin recarga dinámica.
- **Resto:** `preprocessing/normalizer`, `postprocessing/detection_normalizer`, `sinks/*`,
  `transport/*`, `metrics/*`, `RunContext` se reusan tal cual.

### 3.3 Despliegue

- **Fase 1 — contenedor único DBE:** una imagen con GPU (runtime NVIDIA), FastAPI+uvicorn.
  Volúmenes: `RUNS_DIR` (artefactos), caché de pesos, y **datasets montados** (ver §7).
- **Fase 2 — dos nodos EBE:** dos imágenes (edge sin GPU: ingesta+rate+norm; GPU:
  inferencia+post), unidas por el `transport` ZeroMQ existente (corte tras normalización).
  Respeta la decisión previa de dockerizar recién en la fase de dos nodos para el split.

## 4. Ciclo de vida y modelo (mantenerlo simple)

**Principio:** el media-plane **no gestiona modelos dinámicamente**. Cargar/descargar
pesos en un proceso vivo con PyTorch/CUDA es frágil (memoria GPU que no se libera del
todo, fragmentación, estado que se filtra entre corridas). Se evita por completo.

- **Un modelo por instancia, cargado al arrancar** desde `MODEL_REF` (env/config). El
  servicio queda `ready` cuando el modelo está cargado (`/readyz`).
- **Cambiar de modelo = reiniciar/redeploy** el contenedor con otro `MODEL_REF`. Proceso
  fresco, sin estado previo. Con contenedores es trivial y reproducible.
- **Run = configuración + corrida** sobre el modelo cargado. Produce `run_id` + artefactos
  persistidos (reproducibilidad BENCH). Los runs live pueden ser no acotados.
- **Concurrencia mínima:** **un run activo a la vez** (1 GPU). Otro request mientras hay
  uno corriendo → `409 busy` (o cola de un solo slot, opcional). Sin scheduler complejo.
- **Stop:** para fuentes live, corta la ingesta y cierra sinks limpiamente; el run queda
  `stopped` con summary parcial.
- **BENCH (6 modelos):** se orquesta **una corrida de contenedor por modelo** (script /
  docker-compose / la consola en Fase 2), cada una con su `MODEL_REF`. No hay recarga
  in-process en ningún caso.

## 5. Adaptador de ingesta visual (plugins)

Registro explícito de plugins (reemplaza el despacho por string actual en
`create_source`). Cada plugin declara: id, tipo (bounded|live), esquema de config,
disponibilidad. MVP del servicio:

| Plugin | Tipo | Estado |
|---|---|---|
| `image_folder` | bounded | activo |
| `video_file` | bounded | activo |
| `rtsp` | live | activo (fuente live existe; lifecycle stop nuevo) |
| `oak_d` | live | **no disponible** (stub) |

`GET /api/catalog/ingest-plugins` expone este registro; la consola lo usa para el
selector de fuente.

## 6. Refactor del media-plane (qué cambia)

- **Se elimina:** `cli.py` (Typer app y subcomandos `run`, `run-producer`,
  `run-consumer`, `run-two-node-local`, `validate-config`, `inspect-run`, `compare-runs`)
  y el entry point `eovrt-media` de `pyproject.toml`.
- **Se agrega:** paquete `service/` — app FastAPI, **carga del modelo al startup** (una
  vez, desde `MODEL_REF`), `RunManager` mínimo (un run activo; `409` si ocupado; stop),
  routers (runs, catalog, model, health), capa WebSocket de streaming, y adaptación de
  `RunContext`/telemetría a eventos push además de los archivos. **Sin `ModelRegistry` ni
  recarga dinámica.**
- **Se reusa envolviendo:** `run_pipeline` (`runtime/pipeline.py:331`) se descompone para
  que el bucle de consumo emita eventos de telemetría en vivo (hoy ya escribe
  `metrics.jsonl`/`detections.jsonl` incrementales; se añade un canal in-process hacia el
  WebSocket). `run_node_a`/`run_node_b` quedan para el split EBE (Fase 2).
- **Se formaliza:** `sources/` → registro de plugins de ingesta (§5).
- **Se agrega:** `Dockerfile` (imagen GPU única, Fase 1) + healthchecks.

## 7. Integración y contorno (contenedores)

1. **Datasets montados:** los `configs/datasets/*.yaml` hoy usan rutas relativas
   `../e-ovrt_datasets/...`. En contenedor eso se rompe: los datasets se **montan** en una
   ruta conocida y el catálogo de datasets del servicio se vuelve container-aware (por
   env/volumen). Requisito de Fase 1.
2. **Prompts inline:** la consola resuelve el prompt set (vive con `experimental-setup`) y
   lo envía inline en la sesión → el servicio **no** necesita montar `experimental-setup`.
3. **Pesos:** volumen de caché para no re-descargar en cada arranque de contenedor.
4. **`RUNS_DIR`:** volumen persistente para artefactos.

## 8. Manejo de errores

- **Validación de config de sesión:** errores de schemas Pydantic devueltos con detalle a
  nivel de campo (`422`).
- **Fallo de carga de modelo (al arrancar):** el servicio no pasa a `ready` (`/readyz`
  falla) y reporta el error; el contenedor no acepta runs. No hay recarga que reintentar.
- **Errores de runtime por unit:** se escriben a `errors.jsonl` sin cortar la sesión; se
  emiten por WS como contador+tail. Exit anómalo del bucle → sesión `failed`.
- **Fuente live caída:** el plugin RTSP reintenta (reconnect existente); si agota, la
  sesión pasa a `failed`/`stopped` con causa.
- **OAK-D u otro plugin no disponible:** rechazo con mensaje claro al crear la sesión.

## 9. Testing

- **Unit:** carga de modelo al startup (éxito y fallo → `/readyz`), `RunManager` (un run
  activo, `409` si ocupado, stop), registro de plugins de ingesta, validación de config de
  run, mapeo de telemetría a eventos WS.
- **Integración (sin GPU):** servicio en proceso + detector `mock` sobre `demo_v2` —
  `POST /sessions` → `start` → WS emite telemetría → `runs/{id}` legible con artefactos.
  Sesión live simulada (fuente fake unbounded) + `stop`.
- **Contenedor:** smoke de arranque (`/healthz`, `/readyz`) y una sesión mock end-to-end
  con datasets montados.
- Reusar los tests existentes de sources/models/binding/transport que sigan aplicando.

## 10. Plan de fases

- **Fase 1 (servicio DBE):** eliminar CLI; API de control + WS + artefactos; carga de
  modelo al startup (`MODEL_REF`, sin recarga); `RunManager` mínimo (un run activo, stop);
  registro de plugins de ingesta (bounded + RTSP live con stop); contenedor único GPU con
  datasets montados y prompts inline; suite de tests con mock.
- **Fase 2 (EBE + productivo):** split en dos imágenes (edge/GPU) sobre el `transport`
  ZeroMQ; node-agent/orquestación multi-nodo; hardening productivo. (OAK-D cuando haya
  hardware.)

## 11. Riesgos

1. **Rutas relativas de datasets en contenedor** — mitigado montando datasets + catálogo
   container-aware (§7.1).
2. **Cambio de modelo por redeploy** — la recarga in-process se evita por diseño (§4). El
   costo es reiniciar para cambiar de modelo; aceptado a cambio de robustez y simplicidad.
   Para BENCH se orquestan N contenedores.
3. **Telemetría en vivo desde el bucle de consumo** — hoy es file-first; agregar canal
   in-process sin acoplar el pipeline al servidor (usar una interfaz de "event sink").
4. **Eliminar el CLI** — hay tests y flujos (BENCH) que lo usan; migrarlos a un cliente
   HTTP/script o a helpers de test que llamen a la API in-process.

## 12. Impacto en Spec B (consola)

- El `RunBackend` de la consola deja de spawnear subprocess y **pasa a ser cliente HTTP/WS
  del servicio**. `LocalRunBackend` → apunta a una instancia local del servicio;
  `RemoteNodeBackend` → apunta a otra instancia (Nodo B). Se caen la correlación de
  `run_id`, el tailing de archivos y los hacks de `cwd`.
- La consola resuelve prompt sets (in-repo `experimental-setup`) y los manda inline.
- Catálogos: plugins-de-ingesta/datasets vienen del **servicio**; el modelo cargado se
  consulta con `GET /api/model`; prompt sets/manifiestos del lado declarativo.
- **Selección de modelo:** como el modelo es fijo por instancia, elegir modelo en la
  consola = apuntar/lanzar la instancia del servicio con ese `MODEL_REF`. En **Fase 1**
  (una instancia local) el modelo es el que está cargado y cambiarlo es un restart del
  contenedor; en **Fase 2** el `RemoteNodeBackend` rutea (o levanta) la instancia del
  modelo pedido. La UI muestra el modelo activo (`GET /api/model`) en vez de un dropdown
  libre.
