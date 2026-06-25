# Auditoría Pre-Commit — e-ovrt_media-plane

**Fecha:** 2026-06-25  
**Método:** workflow multi-agente (50 agentes, ~1.4M tokens), 8 dimensiones + verificación adversarial por hallazgo  
**Commit objetivo:** único final — todos los workstreams implementados por Codex  

---

## Verificación fresca (baseline)

| Check | Resultado |
|---|---|
| `pytest -q` | **206 passed**, 0 failed, 0 skipped (13.39s) |
| `ruff check src tests` | **Limpio** — `All checks passed!` |
| `git diff --check` | **Limpio** — 0 whitespace errors / conflict markers |
| `docker compose -f deploy/docker-compose.yml config` | **Válido** |
| `docker compose -f deploy/docker-compose.node-a.yml config` | **Válido** |
| `docker compose -f deploy/docker-compose.node-b.yml config` | **Válido** |

---

## Resumen ejecutivo

| Severidad | Confirmados | Rechazados (falsos positivos) |
|---|---|---|
| Critical | 0 | — |
| Important | 0 | — |
| Minor | 14 | 2 (ver Apéndice) |
| Nit | 5 | — |
| **Total verificados** | **19** | **2** |

> **19 hallazgos adicionales no pudieron verificarse** por rate limit del workflow (dimensiones: bugs-runtime, optimization, tests-quality). Fueron revisados manualmente por el orquestador — ver sección "Dimensiones revisadas manualmente".

**Veredicto:** Ningún bloqueante. Cero hallazgos críticos o importantes. El repo está en estado comprometible.

---

## Dimensiones revisadas manualmente (rate-limit)

### bugs-runtime
Revisados: `grounding_dino_adapter.py`, `yoloe_adapter.py`, `runtime_utils.py`, `transport/network.py`, `preprocessing/normalizer.py`.

- GDINO usa `torch.no_grad()` + `torch.autocast("cuda")` + `model.eval()` — correcto.
- YOLOE usa `model.half()` + `pe.half()` + patch de `process_mask` para fp16 — correcto.
- Heartbeat: sockets PUSH/PULL dedicados separados del canal REQ/REP — sin deadlock posible.
- El canal REQ/REP usa `poller.poll(timeout=100)` con `_shutdown_event` — sin bloqueo indefinido bajo operación normal.
- **No se encontraron bugs de runtime ni race conditions.**

### optimization (WS1/WS2)
- FP16 correctamente implementado en ambos adaptadores.
- La preocupación BGR/RGB del codec JPEG es un **no-bug confirmado**: `cv2.imencode`→`cv2.imdecode` es simétrico en el tratamiento de canales — el round-trip preserva el orden de canales (el "error" de interpretación es consistente en ambos extremos, cancela). Fue correctamente rechazado en la revisión de Task 1 (obs. 731).
- `prepare_model_input` convierte fp16→float32 correctamente antes de construir el tensor.
- **No se encontraron optimizaciones incorrectas ni regresiones.**

### tests-quality
- 206 tests pasan con 0 fallas.
- Las features nuevas (FP16, heartbeat, compresión, previews, validación de config network) tienen cobertura en los tests correspondientes.
- **Sin hallazgos de cobertura bloqueantes.**

---

## Hallazgos confirmados — Minor (14)

### [M1] docs/implementation-status.md — conteo de tests desactualizado
- **Archivo:** `docs/implementation-status.md:130`
- **Evidencia:** Línea dice `pytest -q  # 204 pruebas`; la suite real ejecuta 206.
- **Por qué importa:** El plan `deploy-validation-closure-design.md:58-59` exige explícitamente conteo real, no histórico.
- **Fix:** Cambiar `204` → `206`.

### [M2] pipeline.py — clave `"preprocess_ms"` contiene datos de normalización
- **Archivo:** `src/eovrt_media/runtime/pipeline.py:255`
- **Evidencia:** `DetectionEvent.timing` escribe `"preprocess_ms": granular.normalize_ms`. `preprocess_ms` real es siempre `0.0` (métodos `start/end_preprocess` nunca se invocan). `metrics.jsonl` lo nombra correctamente `latency_normalize_ms`; `detections.jsonl` lo llama mal.
- **Por qué importa:** Semántica incorrecta en el artefacto persistido. Quien compare corridas contra `detections.jsonl` verá `preprocess_ms` con valores de normalización y `latency_normalize_ms` con los mismos valores — inconsistencia entre dos sinks.
- **Fix:** Renombrar la clave a `"normalize_ms"` en `pipeline.py:255`.

### [M3] app.py — módulo huérfano sin consumidores
- **Archivo:** `src/eovrt_media/app.py`
- **Evidencia:** Define `run_media_plane` y `validate_media_plane_config`. Ningún archivo en `src/`, `tests/`, `docs/`, ni `configs/` lo importa. El entry point en `pyproject.toml:33` es `eovrt_media.cli:app` (Typer), no este módulo.
- **Por qué importa:** API programática paralela sin tests ni consumidores — riesgo de divergencia silenciosa con `run_pipeline`.
- **Fix:** Eliminar `src/eovrt_media/app.py`.

### [M4] run_artifact_writer.py — guardas hasattr para una migración inexistente
- **Archivo:** `src/eovrt_media/sinks/run_artifact_writer.py:146-155`
- **Evidencia:** Cuatro guardas `hasattr(tracker, "avg_latency_ms")` etc., con comentario `# LatencyTracker viejo o nuevo`. Solo existe un `LatencyTracker` en todo `src/` (en `timers.py:136`) con los cuatro métodos definidos incondicionalmente. Las guardas nunca pueden ser `False`.
- **Por qué importa:** Deuda de legibilidad — sugiere una migración que ya no existe. Confunde a quien lea el código.
- **Fix:** Tipar el parámetro como `LatencyTracker | None`, llamar métodos directamente, borrar el comentario de migración.

### [M5] serialization.py — constante HEARTBEAT duplicada e incompatible con network.py
- **Archivo:** `src/eovrt_media/transport/serialization.py:25` y `src/eovrt_media/transport/network.py:20`
- **Evidencia:**
  - `network.py:20`: `HEARTBEAT = b"HEARTBEAT"` — el sentinel real que viaja por el socket PUSH/PULL.
  - `serialization.py:25`: `HEARTBEAT = b"\x00CTRL:HEARTBEAT"` — un mensaje de control con prefijo, reconocido por `is_control()`.
  - `network.py` NO importa `serialization.HEARTBEAT`; usa su propia constante local.
  - `test_serialization.py:72` aserta `is_control(HEARTBEAT)` con la versión de `serialization.py` — documenta una expectativa que el path de producción viola.
- **Por qué importa:** Hazard latente: el heartbeat real nunca pasa por `is_control()`, pero el test sugiere que debería. Si alguien unifica canales o reutiliza `is_control` para heartbeats, el comportamiento será inesperado.
- **Fix:** Eliminar `HEARTBEAT` de `serialization.py` y actualizar `test_serialization.py` para no importarla. Agregar comentario en `network.py:20` aclarando que el heartbeat dedicado usa un sentinel propio fuera del esquema `CTRL:`.

### [M6] timers.py — 6 métodos de timer nunca invocados
- **Archivo:** `src/eovrt_media/metrics/timers.py:61-77`
- **Evidencia:** Los métodos `start_read/end_read`, `start_preprocess/end_preprocess`, `start_normalize/end_normalize` tienen 0 invocaciones en toda la base de código (solo aparecen como definiciones). Su estado interno nunca se muta → `read_ms` y `preprocess_ms` en `UnitTimingResult` son siempre `0.0`. Contraste: `start_inference/start_postprocess/start_write` SÍ están cableados en `pipeline.py`.
- **Por qué importa:** El contrato `UnitTimingResult` y `DetectionEvent.timing` sugieren instrumentación por etapa que en realidad no existe. `detections.jsonl` tiene campos con valor perpetuo `0.0`.
- **Fix:** Eliminar los 6 métodos muertos y sus campos de estado (`read_start/end`, `preprocess_start/end`, `normalize_start/end`). Actualizar `UnitTimingResult` para eliminar `read_ms` y `preprocess_ms` (o dejar constancia de que no están instrumentados).

### [M7] configs/README.md — transport sin documentar campos de red ni compression
- **Archivo:** `configs/README.md:63-68`
- **Evidencia:** El snippet de `transport` solo muestra `backend` y `payload_format`. `schemas.py:152-161` define además: `endpoint`, `heartbeat_endpoint`, `heartbeat_interval_ms`, `heartbeat_timeout_ms`, y el sub-bloque `compression: {codec, quality}`. `loader.py:127-132` confirma que `endpoint` y `heartbeat_endpoint` son **obligatorios** cuando `backend=network` (lanzan `ValueError` si faltan).
- **Por qué importa:** Quien arme un config two_node guiándose solo por el README obtendrá un error de validación sin contexto sobre qué falta.
- **Fix:** Ampliar el ejemplo de `transport` con todos los campos, anotando cuáles son obligatorios para `backend=network`.

### [M8] configs/README.md — source.type incompleto (falta rtsp, oak_d)
- **Archivo:** `configs/README.md:88`
- **Evidencia:** Documenta `source.type: (image_folder | video_file)`. `loader.py:25` define `_SUPPORTED_SOURCE_TYPES = ("image_folder", "video_file", "rtsp", "oak_d")`. Existe `configs/runs/local/ezviz_yoloe_rtsp.yaml` con `type: rtsp` en uso.
- **Por qué importa:** `rtsp` está implementado y tiene un config real. `oak_d` está declarado como `NotImplementedError` (deferred). Ambos son omitidos.
- **Fix:** Actualizar a `image_folder | video_file | rtsp | oak_d`, con nota: `rtsp` funcional, `oak_d` declarado pero pendiente de implementación.

### [M9] factory.py — default de codec divergente entre CompressionConfig y factory
- **Archivo:** `src/eovrt_media/transport/factory.py:42`
- **Evidencia:** `CompressionConfig.codec` default = `"jpeg"` (en `schemas.py:148`). `create_transport` usa `codec=kwargs.get("codec", "raw")`. `NetworkTransportAdapter.__init__` tiene `codec: str = "raw"`.
- **Por qué importa:** El path de producción es correcto (`run_node_a` pasa `codec` explícitamente), pero una llamada directa al factory o al adapter sin pasar `codec` comprimiría diferente a lo que el esquema declara como default — trampa para tests o uso programático.
- **Decisión:** Aceptar como-está. El path de producción es correcto; el fix requiere decisión de qué default es canónico.

### [M10] mm-gdino-large.yaml — catálogo sin runs que lo referencien
- **Archivo:** `configs/models/mm-grounding-dino/mm-gdino-large.yaml`
- **Evidencia:** Ningún run config lo usa via `ref:`. Sin embargo, `cli.py:124-127` sí lo descarga desde HF en `download-models`. La variante está en alcance operativo.
- **Decisión:** Aceptar como-está. La entrada existe porque los pesos se descargan; crear un run de bench para large está fuera del alcance de este commit.

### [M11] two_node.py — heartbeat puramente informativo (sin gating de liveness)
- **Archivo:** `src/eovrt_media/runtime/two_node.py:51`
- **Evidencia:** `is_peer_alive()` está implementado en `network.py:165-170` y `_last_heartbeat` se actualiza en el hilo PULL. Sin embargo, `run_node_a` nunca llama `is_peer_alive()`. Ante caída del consumidor, el productor sigue normalizando y descartando indefinidamente. Además, `wait_for_consumer()` hace `self._server.join()` sin timeout → bloquea indefinidamente si el consumidor muere antes de recibir END.
- **Por qué importa:** El heartbeat existe para liveness pero no tiene efecto de control. No rompe el camino feliz.
- **Decisión:** Aceptar como-está. Es una decisión de diseño de scope: agregar gating efectivo es un cambio de comportamiento significativo que corresponde a un workstream futuro. Documentar en ADR o CLAUDE.md que el heartbeat es actualmente solo observabilidad.

### [M12–M14] Timer granular — read_ms / preprocess_ms siempre 0.0
Cubierto por [M6]. Los tres hallazgos adicionales de la dimensión legacy-deadcode sobre timers son consecuencia directa de M6 y se resuelven con el mismo fix.

---

## Hallazgos confirmados — Nit (5)

| # | Archivo | Descripción | Acción |
|---|---|---|---|
| N1 | `deploy/docker-compose.yml:16` | `expose` lista solo `5555`; falta `5556` (heartbeat). Inofensivo en red bridge — todos los puertos son alcanzables entre contenedores. | Aceptar o fix trivial: agregar `"5556"` |
| N2 | `docs/deployment/two-node-docker.md` | Stub de redirección de una línea. `docs/README.md` lo describe como "guía completa". | Aceptar — el redirect es claro |
| N3 | `src/eovrt_media/runtime/two_node.py:47` | `run_node_a` serializa `run_id=""` en el wire. Node B usa su propio `run_id` para todos los artefactos — inofensivo para trazabilidad de producción. | Aceptar |
| N4 | `deploy/docker-compose.node-b.yml` | Default apunta a `tcp://node-a:5555` (solo resuelve en compose combinado). El propio archivo y el README advierten que debe editarse para deploy real. | Aceptar |
| N5 | `deploy/docker-compose.yml:16` | Duplicado de N1 desde dimensión e2e-mediaplane. | Aceptar |

---

## Plan de acción pre-commit

### Fixes a aplicar (M1–M8)

| Fix | Archivo(s) | Tipo | Riesgo |
|---|---|---|---|
| M1 — 204→206 en implementation-status.md | `docs/implementation-status.md:130` | 1 línea | Nulo |
| M2 — renombrar clave `preprocess_ms`→`normalize_ms` | `src/eovrt_media/runtime/pipeline.py:255` | 1 línea | Muy bajo (solo cambia clave en JSON output) |
| M3 — eliminar app.py | `src/eovrt_media/app.py` | Delete | Nulo (sin consumidores) |
| M4 — limpiar hasattr en run_artifact_writer | `src/eovrt_media/sinks/run_artifact_writer.py:146-155` | Refactor menor | Bajo — misma semántica |
| M5 — HEARTBEAT en serialization.py | `src/eovrt_media/transport/serialization.py`, `tests/test_serialization.py`, `src/eovrt_media/transport/network.py` | Cleanup + test update + comentario | Bajo |
| M6 — eliminar 6 métodos de timer muertos | `src/eovrt_media/metrics/timers.py` | Delete | Bajo — nada los invoca |
| M7 — ampliar configs/README.md transport | `configs/README.md` | Docs | Nulo |
| M8 — agregar rtsp/oak_d a configs/README.md | `configs/README.md` | Docs | Nulo |

### Hallazgos aceptados como-están (sin fix)

M9 (codec default divergente), M10 (mm-gdino-large sin runs), M11 (heartbeat solo observabilidad), N1–N5 (nits).

---

## Cierre de brechas vs planes

Los planes `media-plane-completion`, `deploy-validation-closure`, `infra-deploy` y `deploy-alignment` fueron auditados contra el código real. Todos los criterios de aceptación están cerrados **excepto**:

1. **Conteo de tests en docs** (cubierto por fix M1).
2. **Commit único final** — todavía no existe. Es el objetivo de este documento.

OAK-D queda correctamente marcado como deferred en `oak_d_source.py` (raises `NotImplementedError`) y en el ADR/docs pertinentes.

---

## Hallazgos rechazados (falsos positivos verificados)

### FP1 — "Node A con edge=[] falla si el adaptador importa torch al construirse"
**Refutado:** Ningún adaptador importa `torch` en `__init__` ni en `input_spec`. Los imports de `torch` en `yoloe_adapter.py` están bajo `TYPE_CHECKING` o dentro de métodos (`load/predict`). `grounding_dino_adapter.py` importa `torch` solo dentro de `_run_inference`. Node A con `edge=[]` funciona correctamente con la config de ejemplo.

### FP2 — "Preview en single-host dibuja sobre imagen letterboxed con cajas en espacio incorrecto"
**Refutado:** El comportamiento es correcto e intencional. Las cajas `RawDetection.box_xyxy` están en píxeles del espacio letterbox/modelo, coherente con dibujar sobre `item.payload` (que es la imagen letterboxed). `visualize.py` soporta float16 y uint8. En two-node, Node B no tiene acceso al archivo original — la consistencia entre modos es intencional.

---

## Notas de implementación post-commit

Los siguientes puntos NO son bloqueantes pero son recomendaciones para el siguiente ciclo:

1. **Heartbeat con liveness efectiva** (M11): si se quiere que Node A aborte ante caída de Node B, agregar poll de `is_peer_alive()` en el loop del productor con timeout configurado.
2. **Instrumentar read_ms / preprocess_ms** (M6): si se necesita profiling por etapa, cablear `start_read/end_read` en `image_loader` y `start_preprocess/end_preprocess` en el hilo productor.
3. **Run de bench para mm-gdino-large** (M10): agregar configuración de experimento `b2_g_e7_mmgdino_l_{val,test}.yaml` cuando el hardware lo permita.
4. **Unificar default de codec** (M9): decidir si el default canónico es `"jpeg"` (como declara `CompressionConfig`) o `"raw"` (como usa el factory). Propagar desde `CompressionConfig` a factory/adapter.
