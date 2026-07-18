# Fase 2 — EBE two-node containerizada — Diseño

- **Fecha:** 2026-07-05 · **Estado:** aprobado (brainstorming 2026-07-05), pendiente plan de implementación
- **Repo:** `e-ovrt_media-plane` @ `feature/inference-service` (**sin merge a main**). No toca `e-ovrt_experimental-setup`.
- **Depende de:** Fase 1 completa (servicio DBE single-host, Spec A) + plataforma DBE Docker con orquestación desde consola (smoke Task 10 pasado el 2026-07-05, commits pusheados).

## 0. Decisiones de alcance (cerradas con el usuario, 2026-07-05)

1. **Motivación:** completar la topología EBE del proyecto para todas las fuentes (dataset de imágenes/video, RTSP) y dejar el terreno listo para la cámara OAK-D Pro PoE cuando llegue — aunque hoy no haya hardware.
2. **OAK-D: interfaz + stub, implementación diferida.** Se formaliza el contrato de configuración; `OakDSource` sigue con `NotImplementedError` explícito. No se instala DepthAI ni se escribe el adaptador real en esta fase.
3. **ZeroMQ: timeout + error claro, sin reconexión automática.** Si un nodo muere a mitad de corrida, la corrida falla con mensaje explícito; el usuario relanza. No se versionan mensajes en vuelo ni se reanudan sesiones.
4. **Sin autenticación ni cifrado entre nodos.** Despliegue en LAN controlada de laboratorio; riesgo aceptado y documentado. No token, no TLS/CURVE.
5. **Topología separada, manual — NO integrada al switching de la consola.** El par Nodo A + Nodo B se levanta/baja con `docker compose` a mano. El `TargetManager`/`ComposeOrchestrator` de la consola y toda la plataforma DBE quedan intactos.

## 1. Contexto y problema

El runtime two-node ya existe y está validado en-proceso: `runtime/two_node.py` (`run_node_a` / `run_node_b`) sobre `transport/network.py` (ZeroMQ REQ/REP de datos + PUSH/PULL de heartbeat), con gate de equivalencia documentado (2026-06-24: mAP idéntico DBE vs EBE; JPEG q90 con pérdida marginal). Lo que está roto es el **empaquetado**: los artefactos Docker de `deploy/` (Dockerfile.node-a/b, composes) invocan el CLI `eovrt-media run-producer/run-consumer`, eliminado en la Fase 1 (Task 17), y están marcados DEPRECADO/ROTO. `run_two_node_local` quedó neutralizado por la misma razón (`RuntimeError` en `two_node_local.py`).

Además, `NetworkTransportAdapter.request()` (lado consumidor, Nodo B) hace `send`+`recv` **bloqueante sin límite** (`network.py`): si el Nodo A muere a mitad de corrida, el Nodo B cuelga para siempre.

## 2. Arquitectura

Dos contenedores, un run batch por invocación (proceso que termina al agotar el stream — igual que hoy en-proceso; **no** se convierte el Nodo B en servicio FastAPI de larga vida, eso exigiría rehacer `RunManager` que asume transporte en memoria y no está pedido):

- **Nodo A (edge, sin GPU)** — imagen `python-slim` + `pip install .[edge]` (extra vacío: solo deps base, sin torch). Ejecuta ingesta (`image_folder`/`video_file`/`rtsp`; `oak_d` declarado) + `RateGate` + normalización + servidor ZeroMQ (REP datos, PULL heartbeat). Reutiliza `run_node_a()` **sin cambios funcionales**. Restricción a preservar: el Nodo A construye el adaptador solo para leer `adapter.input_spec` y nunca llama `adapter.load()` — la imagen edge debe poder resolver `input_spec` de cualquier modelo del catálogo sin deps GPU (ya probado en el gate 2026-06-24 "Node A no-Torch").
- **Nodo B (GPU/CUDA)** — imagen CUDA (misma base/estrategia que `infra/docker/Dockerfile` actual). Consumidor ZeroMQ (REQ datos, PUSH heartbeat) + inferencia + postproceso + `RunArtifactWriter`. Reutiliza `run_node_b()` sin cambios funcionales. Es el dueño del `run_id` y de `runs/`.

### 2.1 Entrypoint nuevo: `eovrt_media.tools.run_node`

Reemplazo delgado del CLI eliminado, mismo patrón que `tools/evaluate|inspect_runs|debug_run`:

```
python -m eovrt_media.tools.run_node --role {a|b} --config /path/al/config.yaml
```

Carga el `RunConfig` con `load_run_config(config_path)` (ya existente, resuelve refs de modelo/dataset/prompts) y despacha a `run_node_a(config)` o `run_node_b(config)`. Exit code ≠ 0 ante cualquier excepción, con el error en stderr (los contenedores reportan por exit code + logs). Sin subcomandos, sin Typer: `argparse` puro.

### 2.2 Layout: `infra/twonode/` reemplaza a `deploy/`

Consistente con el layout `infra/` recién introducido para el standalone:

```
infra/
  docker/Dockerfile              # (ya existe) imagen GPU del servicio DBE
  docker-compose.yml             # (ya existe) standalone single-host
  twonode/
    Dockerfile.node-a            # edge sin GPU, ENTRYPOINT python -m eovrt_media.tools.run_node --role a
    # (sin Dockerfile.node-b: el Nodo B reusa la imagen eovrt/media-plane:latest
    #  construida por infra/docker/Dockerfile, con entrypoint override en el compose)
    docker-compose.yml           # ambos nodos en un host (red bridge interna) — smoke y demo
    docker-compose.node-a.yml    # solo Nodo A (host edge real, publica 5555/5556)
    docker-compose.node-b.yml    # solo Nodo B (host GPU real, endpoint remoto vía config)
    configs/                     # two_node_a/b.example.yaml migrados desde deploy/configs/
    README.md                    # operación, topologías, riesgo de seguridad aceptado
```

`deploy/` se **elimina** al final de la fase (sus cuatro configs de ejemplo migran a `infra/twonode/configs/`). `two_node_local.py`: `run_two_node_local` **conserva su guard** de `RuntimeError` (lo importan `debugging/session.py` y lo monkeypatchean los tests de debug session — borrarla rompería el módulo de debug entero); se elimina solo el **cuerpo inalcanzable** después del raise y los helpers exclusivos de subprocesos (`_command_for_node`, `_subprocess_env`, `_open_log`, `_terminate_process`, `_endpoints_for_options`). El mensaje del guard se actualiza para apuntar a `infra/twonode/`.

### 2.3 Configuración

Los YAMLs de ejemplo ya tienen la forma correcta (`topology.mode: two_node`, `transport.backend: network`, endpoints, `compression: jpeg q90` validado). Cambios:
- Endpoints del compose single-host usan el nombre de servicio Docker (`tcp://node-a:5555`) en vez de `localhost`.
- El dataset se monta `:ro` en el Nodo A (`EOVRT_DATASETS_ROOT`-compatible); `models/` y `runs/` se montan solo en el Nodo B.
- Nuevo campo `transport.request_timeout_ms` (ver §3).

## 3. Hardening ZeroMQ

`TransportConfig` gana `request_timeout_ms: int = Field(default=10000, gt=0)`. En `NetworkTransportAdapter.request()` (consumidor), el `recv()` bloqueante se reemplaza por el patrón poller-con-timeout ya usado por el heartbeat en el mismo archivo: si no llega respuesta dentro de `request_timeout_ms`, se lanza `RuntimeError` con mensaje explícito ("Nodo A no respondió en Xms — ¿murió el nodo edge?"; mismo estilo que el `RuntimeError` de heartbeat timeout en `_wait_for_consumer_end`) que aborta la corrida limpiamente (el `finally` existente ya hace `transport.shutdown()` + `adapter.close()` + `artifact_writer.close()`). El REQ socket queda en estado inconsistente tras un send sin recv — es aceptable porque la corrida termina ahí (sin reintento, decisión §0.3).

El lado productor (Nodo A) ya tiene su protección equivalente: `_wait_for_consumer_end` corta por heartbeat timeout si el Nodo B muere. No se toca.

## 4. Contrato OAK-D (formalización, sin implementación)

`source.type: oak_d` ya está registrado como plugin live no disponible (`sources/registry.py`); esta fase solo **documenta** su contrato de config — sin cambios de schema (YAGNI):

```yaml
source:
  type: oak_d
  url: "169.254.1.222"      # IP del dispositivo PoE (None => autodescubrimiento USB/LAN)
  max_units: null            # cámara viva: sin límite salvo que se pida
```

Semántica: fuente **live** (como `rtsp`) — timestamps wall-clock, sin `len()`, corre hasta stop externo o `max_units`. `OakDSource` conserva el `NotImplementedError` explícito con mensaje que apunta a instalar DepthAI. La implementación real es una fase futura disparada por la llegada del hardware.

## 5. Seguridad

Sin auth ni cifrado entre nodos (decisión §0.4). El `README.md` de `infra/twonode/` documenta explícitamente: los puertos ZeroMQ (5555/5556) solo deben publicarse en la LAN de laboratorio; cualquiera con acceso de red a esos puertos puede inyectar frames o consumir el stream. Riesgo aceptado para el contexto académico; revisar si el despliegue algún día sale de la LAN controlada.

## 6. Testing y aceptación

- **Unit tests** del entrypoint `tools/run_node`: parsing de args, dispatch a `run_node_a`/`run_node_b` (mockeados), exit codes ante config inexistente/rol inválido/excepción del runtime.
- **Unit tests** del timeout de `request()`: consumidor contra un productor que no responde → error explícito dentro del timeout configurado (patrón de tests existentes de `network.py`/heartbeat).
- **Test de regresión**: suite completa existente (421) sigue verde — `run_node_a/b` no cambian de firma.
- **Smoke de aceptación (manual, documentado en `infra/twonode/README.md`):** en un solo host, `docker compose up` del par → run corto `image_folder` (subset BENCH o demo) con YOLOE-26s o mock → Nodo B produce `runs/<run_id>/` con `detections.jsonl` + `summary.json` coherentes con el equivalente DBE; ambos contenedores terminan con exit 0. Caso de falla: matar el Nodo A a mitad de corrida → el Nodo B termina con error explícito (no cuelga) dentro del timeout.
- **Fuera de alcance del smoke:** dos hosts físicos reales (documentado como próximo paso si se consigue un segundo host) y OAK-D (sin hardware).

## 7. Exclusiones (YAGNI)

- Reconexión/reanudación automática de sesiones ZeroMQ.
- TLS/CURVE o token entre nodos.
- Nodo B como servicio HTTP de larga vida / integración con `RunManager`.
- Integración del par two-node en la página Plataforma de la consola.
- Implementación real de `OakDSource` (DepthAI).
- Orquestación multi-run o colas sobre la topología two-node.
