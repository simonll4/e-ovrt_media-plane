# Media-Plane como Servicio de Inferencia — Diseño (Spec A)

- **Fecha:** 2026-07-01 · **Revisión:** 2026-07-02 (cerrado tras auditoría de código:
  contrato canónico del run request, lifecycle stop/shutdown, operación del servicio)
- **Estado:** aprobado para escribir plan de implementación
- **Repo:** `e-ovrt_media-plane`
- **Relación:** fundación de la consola web (Spec B, en
  `e-ovrt_experimental-setup/docs/superpowers/specs/2026-07-01-webconsole-design.md`,
  que se reescribe como cliente de este servicio).

## 1. Propósito y pivote

El media-plane deja de ser una **CLI batch** y pasa a ser un **servicio de inferencia
desplegable en contenedores**: carga pesos una vez, queda esperando, se le configuran
**runs** (fuente + prompts + parámetros, sobre el modelo ya cargado), **ingiere frames por su adaptador de
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
Cliente (consola)  ──HTTP──▶  API de control      (crear/parar/consultar run)
                   ◀─WS────   stream de run        (telemetría + detecciones en vivo)
                   ──HTTP──▶  API de artefactos    (summary, detections.jsonl, annotated.mp4, previews)
                   ──HTTP──▶  API de catálogos      (modelos, plugins de ingesta, datasets)
```

El **modelo no se elige por request**: es el que la instancia cargó al arrancar. Un run
compone ingesta + prompts + params sobre ese modelo.
- `GET /api/model` — modelo cargado por esta instancia (ref, device, thresholds).
- `POST /api/runs` — crea y arranca un run: `{ ingest: {plugin, config},
  prompts: {set_inline, active_ids}, run: {stride, max_units, save_annotated_video, ...} }`.
  Si ya hay un run activo → `409 busy` (sin cola en Fase 1). Devuelve `run_id`.
  - **Validación (requiere extender lo existente, no es reuso directo):** (a) factorizar
    `load_run_config` para validar un dict (hoy solo acepta un archivo YAML en disco,
    `config/loader.py:238-240`); (b) extender `PromptsSection` con `set_inline` (hoy exige
    `ref` o `file`, `config/schemas.py:259-267`).
  - **Sección `model`: rechazada con `422`.** Los thresholds del modelo quedan fijados al
    construir el adapter en el startup; aceptar overrides `model.*` por run e ignorarlos
    en silencio sería peor que un error explícito.
  - **`run_id` único:** lo genera el servicio (sufijo único tipo uuid corto) y lo inyecta
    vía `run.id` (override ya soportado por `RunContext`). El default actual (timestamp a
    resolución de segundos + `mkdir(exist_ok=True)`) colisiona y mezclaría artefactos de
    dos runs creados en el mismo segundo.
- `POST /api/runs/{id}/stop` — detiene (imprescindible para fuentes live).
- `GET /api/runs/{id}` — estado (`running/succeeded/failed/stopped`) + summary (parcial si activo).
- `GET /api/runs` — run activo + historial. El historial se **reconstruye escaneando
  `RUNS_DIR`** (los `summary.json` son la fuente de verdad); no hay base de datos. Así el
  historial sobrevive al restart del contenedor — que es el mecanismo normal de cambio de
  modelo.
- `WS /api/runs/{id}/stream` — progreso (units/total si bounded), FPS, latencia p95,
  GPU mem, detecciones por label, errores, tail de log. **Backpressure:** los eventos se
  coalescen (último estado gana) sobre una cola acotada con drop-oldest; un cliente WS
  lento jamás frena el pipeline.
- `GET /api/runs/{id}/detections?page=`,
  `GET /api/runs/{id}/artifacts/{annotated.mp4|previews/*}` (range requests para video).
- `GET /api/catalog/{ingest-plugins,datasets}` — el servicio **posee** estos catálogos (la
  ingesta vive en él). El modelo disponible se consulta en `GET /api/model`. Los prompt
  sets y manifiestos son del lado declarativo (consola/exp-setup).
- `GET /healthz` (proceso vivo), `GET /readyz` (modelo cargado) — para el contenedor.

#### Contrato canónico del run request (compartido con Spec B)

Esta tabla es la única fuente de verdad de nombres; Spec B y la traducción desde los
manifiestos declarativos derivan de acá. El BFF (consola) es el dueño de la traducción
manifiesto ↔ request.

| Concepto | Manifiesto declarativo (formato actual) | Run request (servicio) |
|---|---|---|
| Fuente | `source: {ref}` (catálogo del plano) | `ingest: {plugin, config}` |
| Prompt set | `prompts: {ref, active_ids}` | `prompts: {set_inline, active_ids}` (resuelto in-repo por el cliente) |
| Stride | `rate_control: {stride}` | `run: {stride}` |
| Video anotado | `outputs: {save_annotated_video}` | `run: {save_annotated_video}` |
| Modelo | `model: {ref}` | **sin campo** (fijo por instancia; si viene → `422`) |

Nota semántica: en el manifiesto `stride` está ligado a `policy: deterministic` (el loader
lo valida); el request conserva esa regla (`run.stride` implica policy deterministic).

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

- **Un modelo por instancia, cargado al arrancar** desde `MODEL_REF` (env/config), con
  **warmup** incluido (y compilación si el backend lo pide, §4.1). `MODEL_REF` se resuelve
  contra `configs/models/` con una función **factorizada del loader** (hoy esa resolución
  está fusionada a la carga de run configs desde archivo). El servicio queda `ready`
  cuando el modelo está cargado (`/readyz`).
- **Cambiar de modelo = reiniciar/redeploy** el contenedor con otro `MODEL_REF`. Proceso
  fresco, sin estado previo. Con contenedores es trivial y reproducible.
- **Run = configuración + corrida** sobre el modelo cargado. Produce `run_id` + artefactos
  persistidos (reproducibilidad BENCH). Los runs live pueden ser no acotados.
- **Concurrencia mínima:** **un run activo a la vez** (1 GPU). Otro request mientras hay
  uno corriendo → `409 busy` (o cola de un solo slot, opcional). Sin scheduler complejo.
- **Stop:** corta la ingesta (fuentes live **y bounded** — parar un run de 5540 imágenes
  también debe poder hacerse) y cierra sinks limpiamente; el run queda `stopped` con
  summary parcial.
- **Shutdown (SIGTERM):** como el redeploy es el mecanismo de cambio de modelo, recibir
  SIGTERM con un run activo es el caso *normal*, no excepcional: el servicio ejecuta el
  mismo camino que stop, marca el run `stopped` (causa `shutdown`), cierra sinks y recién
  entonces sale. Periodo de gracia configurable (compatible con `stop_grace_period` del
  orquestador).
- **Watchdog:** si un run no progresa (ninguna unit ni evento durante N segundos,
  configurable), se marca `failed` (causa `stalled`) y se libera el slot.
- **BENCH (6 modelos):** se orquesta **una corrida de contenedor por modelo** (script /
  docker-compose / la consola en Fase 2), cada una con su `MODEL_REF`. No hay recarga
  in-process en ningún caso.

### 4.1 Backend de inferencia (extensión futura, fuera de Fase 1)

El patrón "modelo fijo por instancia, cargado al startup" habilita backends compilados:
la entrada del catálogo de modelos gana un campo opcional `backend: torch|onnx|tensorrt`
(default `torch`) y la compilación/warmup ocurre una sola vez al arrancar.

- **YOLOE → ONNX/TensorRT (viable, barato):** `set_classes()` congela los text embeddings
  y el export de ultralytics produce un detector de vocabulario fijo — exactamente el
  caso de uso (vocabulario canónico v2 fijo). Caveat: el engine queda ligado a
  (modelo, vocabulario); cambiar el prompt set invalida la caché.
- **Grounding DINO → ONNX (no recomendado):** dos encoders con fusión texto-imagen,
  atención deformable con kernel custom, shapes dinámicas por longitud de texto y
  postproceso fuera del grafo; sin ruta oficial de export. Esfuerzo alto, ganancia
  incierta.
- **Quick wins previos a cualquier runtime compilado** (medidos en runs reales del
  2026-06-30: GDINO-tiny ~452 ms/frame de inferencia vs ~2000 ms/frame de
  decode+letterbox CPU en el productor — acelerar solo la inferencia no sube el fps
  efectivo en video):
  1. Cachear el cómputo de texto en GDINO — hoy re-tokeniza y re-ejecuta el encoder de
     texto **en cada frame** aunque el vocabulario es fijo por run
     (`grounding_dino_adapter.py:223-224`); YOLOE ya lo cachea.
  2. `torch.compile` para GDINO (shapes estáticas: letterbox 800×800 + caption fijo).
  3. Transferir uint8 y normalizar mean/std en GPU (hoy se normaliza en CPU y se
     transfiere float32, 4× más bytes).
  4. Atacar el decode/letterbox del productor — el cuello dominante en video.

fp16 ya está implementado en ambos adapters (autocast en GDINO, `half=True` en YOLOE);
no hay ganancia pendiente ahí.

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
  y el entry point `eovrt-media` de `pyproject.toml`. **Destino de los subcomandos
  utilitarios** (no desaparecen sin reemplazo):
  - `download-models` → script standalone / target de Make, usado al construir la imagen
    o provisionar el volumen de caché de pesos (§7.3 depende de él).
  - `evaluate` → script standalone que consume `detections.jsonl` (vía API o volumen);
    sigue alimentando el flujo BENCH junto a `evaluate_bench.py` del repo datasets.
  - `inspect-run` / `compare-runs` → consola (Fase 2) o script sobre la API de runs.
  - `two_node_local` (spawnea el CLI por subprocess) se elimina; su equivalente en Fase 2
    es el docker-compose de las dos imágenes.
- **Se agrega:** paquete `service/` — app FastAPI, **carga del modelo al startup** (una
  vez, desde `MODEL_REF`), `RunManager` mínimo (un run activo; `409` si ocupado; stop),
  routers (runs, catalog, model, health), capa WebSocket de streaming, y adaptación de
  `RunContext`/telemetría a eventos push además de los archivos. **Sin `ModelRegistry` ni
  recarga dinámica.**
- **Se descompone (el punto duro del refactor):** `run_pipeline`
  (`runtime/pipeline.py:331`) **no** es reutilizable tal cual para un servicio:
  - el adapter se crea, carga y **cierra adentro** (`:360/:367/:433`) — hay que extraer su
    lifecycle para que el modelo viva a nivel servicio y no se descargue tras el primer
    run;
  - el único stop hoy es `KeyboardInterrupt`; el hook `should_continue` ya existe en
    `run_producer_loop` (`:84`) pero `run_pipeline` no lo cablea — es el gancho natural
    del stop del RunManager (cubre también fuentes bounded, cuyo `stop()` es no-op);
  - `MemoryTransportAdapter.close()` hace un `put(END)` **bloqueante** sobre cola acotada
    (`transport/memory.py:51-53`) — debe volverse idempotente y no bloqueante para no
    acumular threads productores huérfanos en un proceso persistente;
  - una excepción en setup (modelo/fuente) hoy propaga **sin** escribir `summary.json`
    (`write_summary` queda fuera del try) — el estado `failed` con summary parcial de §8
    lo fabrica el RunManager.

  El bucle de consumo emite telemetría en vivo por un **event sink** in-process hacia el
  WebSocket, decorando el embudo existente `RunArtifactWriter` (hoy ya escribe
  `metrics.jsonl`/`detections.jsonl` incrementales con flush por línea).
  `run_node_a`/`run_node_b` quedan para el split EBE (Fase 2) — el consumer ya corre
  headless ahí.
- **Se formaliza:** `sources/` → registro de plugins de ingesta (§5).
- **Se agrega:** `Dockerfile` (imagen GPU única, Fase 1) + healthchecks.

## 7. Integración y contorno (contenedores)

1. **Datasets montados:** los `configs/datasets/*.yaml` hoy usan rutas relativas
   `../e-ovrt_datasets/...` **resueltas contra el CWD** (`ImageFolderSource`). En
   contenedor eso se rompe, y el env existente (`EOVRT_MEDIA_CATALOG_ROOT`) **no
   alcanza**: reubica los YAML del catálogo pero no toca los `path:` internos. Pieza
   nueva de Fase 1: una raíz de datasets por env (p.ej. `EOVRT_DATASETS_ROOT`)
   interpolada en las entradas del catálogo, con los datasets montados en esa ruta.
2. **Prompts inline:** la consola resuelve el prompt set (vive con `experimental-setup`) y
   lo envía inline en el run → el servicio **no** necesita montar `experimental-setup`.
3. **Pesos:** volumen de caché para no re-descargar en cada arranque de contenedor.
4. **`RUNS_DIR`:** volumen persistente para artefactos, con **política de retención**:
   los runs live no acotados crecen sin límite (`detections.jsonl`, `annotated.mp4`);
   límites configurables por antigüedad/tamaño, `DELETE /api/runs/{id}` y GC al arrancar.
5. **Pines de dependencias:** `pyproject.toml` hoy no pinea torch/transformers/ultralytics
   y el extra `edge` está vacío; la imagen se construye con constraints/lockfile, y el
   extra `edge` se define de verdad para la imagen sin GPU de Fase 2.
6. **Secretos de ingesta (RTSP):** credenciales embebidas en la config del plugin se
   **redactan** en `effective_config`/manifest persistidos y en las respuestas de la API.

## 8. Manejo de errores

- **Validación de config de run:** errores de schemas Pydantic devueltos con detalle a
  nivel de campo (`422`); la sección `model` presente en el request también es `422` (§3.1).
- **Fallo de carga de modelo (al arrancar):** el servicio no pasa a `ready` (`/readyz`
  falla) y reporta el error; el contenedor no acepta runs. No hay recarga que reintentar.
- **Fallo en setup del run (fuente/plugin/config):** el RunManager marca el run `failed`
  y **escribe él mismo el summary parcial** (hoy una excepción en setup propaga sin
  `summary.json`, ver §6).
- **Errores de runtime por unit:** se escriben a `errors.jsonl` sin cortar el run; se
  emiten por WS como contador+tail. Exit anómalo del bucle → run `failed`.
- **Run colgado:** watchdog de progreso (§4) → `failed` (causa `stalled`), slot liberado.
- **Fuente live caída:** el plugin RTSP reintenta (reconnect existente); si agota, el
  run pasa a `failed`/`stopped` con causa.
- **OAK-D u otro plugin no disponible:** rechazo con mensaje claro al crear el run.

## 9. Testing

- **Unit:** carga de modelo al startup (éxito y fallo → `/readyz`), `RunManager` (un run
  activo, `409` si ocupado, stop), registro de plugins de ingesta, validación de config de
  run, mapeo de telemetría a eventos WS.
- **Integración (sin GPU):** servicio en proceso + detector `mock` sobre `demo_v2` —
  `POST /api/runs` → WS emite telemetría → `GET /api/runs/{id}` legible con artefactos.
  Run live simulado (fuente fake unbounded) + `stop`. Dos `POST /api/runs` seguidos →
  `409`. SIGTERM con run activo → `stopped` con summary parcial. Fallo en setup →
  `failed` con summary. Historial reconstruido desde `RUNS_DIR` tras reinicio.
- **Contenedor:** smoke de arranque (`/healthz`, `/readyz`) y un run mock end-to-end
  con datasets montados.
- Reusar los tests existentes de sources/models/binding/transport que sigan aplicando.

## 10. Plan de fases

- **Fase 1 (servicio DBE):** eliminar CLI (con destino de utilitarios, §6); API de
  control + WS + artefactos; carga de modelo al startup (`MODEL_REF`, sin recarga);
  `RunManager` mínimo (un run activo, `409`, stop + SIGTERM + watchdog); registro de
  plugins de ingesta (bounded + RTSP live con stop); contenedor único GPU con datasets
  montados (`EOVRT_DATASETS_ROOT`), prompts inline y retención de `RUNS_DIR`; suite de
  tests con mock.
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
4. **Eliminar el CLI** — impacto en tests acotado (solo 4 archivos lo invocan, 7
   `invoke()` sobre 291 tests); el punto real son los utilitarios (`evaluate`,
   `download-models`, `inspect-run`/`compare-runs`), resuelto en §6 con destino explícito
   por subcomando.
5. **El transport ZeroMQ en Fase 2 no es "reusar tal cual"** — `request()` REQ/REP es
   bloqueante sin timeout (`transport/network.py:186-191`): si el nodo edge cae a mitad
   de corrida, el consumidor queda colgado para siempre (el heartbeat cubre solo la otra
   dirección). El split EBE agrega poller+timeout y estrategia de reconexión.
6. **Sin auth** — aceptado en Fase 1 (localhost / red confiable). En Fase 2 el API cruza
   la red entre nodos: mínimo un token estático compartido (+TLS si sale del host) antes
   de exponer el servicio.

## 12. Impacto en Spec B (consola)

- El `RunBackend` de la consola deja de spawnear subprocess y **pasa a ser cliente HTTP/WS
  del servicio**. `LocalRunBackend` → apunta a una instancia local del servicio;
  `RemoteNodeBackend` → apunta a otra instancia (Nodo B). Se caen la correlación de
  `run_id`, el tailing de archivos y los hacks de `cwd`.
- La consola resuelve prompt sets (in-repo `experimental-setup`) y los manda inline.
  Nombres por capa (fijados en la tabla canónica de §3.1): el form/BFF referencia por
  `set_id`, el request al servicio lleva `prompts.set_inline`, y el manifiesto
  declarativo conserva `prompts.ref`.
- Catálogos: plugins-de-ingesta/datasets vienen del **servicio**; el modelo cargado se
  consulta con `GET /api/model`; prompt sets/manifiestos del lado declarativo.
- **Selección de modelo:** como el modelo es fijo por instancia, elegir modelo en la
  consola = apuntar/lanzar la instancia del servicio con ese `MODEL_REF`. En **Fase 1**
  (una instancia local) el modelo es el que está cargado y cambiarlo es un restart del
  contenedor; en **Fase 2** el `RemoteNodeBackend` rutea (o levanta) la instancia del
  modelo pedido. La UI muestra el modelo activo (`GET /api/model`) en vez de un dropdown
  libre.
