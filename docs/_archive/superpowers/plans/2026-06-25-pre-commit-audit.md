# Auditoría Pre-Commit — e-ovrt_media-plane

**Fecha:** 2026-06-25  
**Método:** workflow multi-agente (50 agentes, ~1.4M tokens), 8 dimensiones + verificación adversarial por hallazgo  
**Commit objetivo:** único final — todos los workstreams implementados por Codex  

---

## Verificación fresca (baseline)

| Check | Resultado |
|---|---|
| `pytest -q` | **210 passed**, 0 failed, 0 skipped |
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

> Los hallazgos adicionales que el workflow inicial dejó fuera por límite operativo fueron
> revisados manualmente en este cierre — ver sección "Dimensiones revisadas manualmente".

**Veredicto:** Ningún bloqueante. Cero hallazgos críticos o importantes. El repo está en estado comprometible.

---

## Dimensiones revisadas manualmente

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
- 210 tests pasan con 0 fallas.
- Las features nuevas (FP16, heartbeat, compresión, previews, validación de config network) tienen cobertura en los tests correspondientes.
- **Sin hallazgos de cobertura bloqueantes.**

---

## Hallazgos confirmados — Minor (14)

### [M1] docs/implementation-status.md — conteo de tests desactualizado
- **Archivo:** `docs/implementation-status.md:130`
- **Evidencia de cierre:** La suite real ejecuta 210 tests tras los tests de cierre.
- **Por qué importa:** El plan `deploy-validation-closure-design.md:58-59` exige explícitamente conteo real, no histórico.
- **Fix:** Actualizar al conteo vigente verificado por la suite completa.

### [M2] pipeline.py — timing de normalización nombrado de forma explícita
- **Archivo:** `src/eovrt_media/runtime/pipeline.py:255`
- **Evidencia de cierre:** `DetectionEvent.timing` escribe `"normalize_ms": granular.normalize_ms`.
- **Por qué importa:** El artefacto persistido ahora usa la misma semántica que `metrics.jsonl`
  (`latency_normalize_ms`) y evita campos de etapa no instrumentada.
- **Fix:** Cerrado.

### [M3] app.py — módulo huérfano sin consumidores
- **Archivo:** `src/eovrt_media/app.py`
- **Evidencia:** Define `run_media_plane` y `validate_media_plane_config`. Ningún archivo en `src/`, `tests/`, `docs/`, ni `configs/` lo importa. El entry point en `pyproject.toml:33` es `eovrt_media.cli:app` (Typer), no este módulo.
- **Por qué importa:** API programática paralela sin tests ni consumidores — riesgo de divergencia silenciosa con `run_pipeline`.
- **Fix:** Eliminar `src/eovrt_media/app.py`.

### [M4] run_artifact_writer.py — guardas hasattr para una migración inexistente
- **Archivo:** `src/eovrt_media/sinks/run_artifact_writer.py:146-155`
- **Evidencia de cierre:** `RunArtifactWriter.write_summary()` llama directamente a los métodos
  de `LatencyTracker` cuando el tracker está presente.
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

### [M6] timers.py — contrato granular limitado a etapas medidas
- **Archivo:** `src/eovrt_media/metrics/timers.py:61-77`
- **Evidencia de cierre:** `UnitTimingResult` contiene sólo `normalize_ms`, `inference_ms`,
  `postprocess_ms`, `write_ms` y `total_ms`.
- **Por qué importa:** El contrato ya no sugiere etapas no instrumentadas ni persiste campos
  perpetuamente nulos.
- **Fix:** Cerrado.

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
- **Evidencia de cierre:** `CompressionConfig`, `create_transport()` y
  `NetworkTransportAdapter.__init__` usan `"jpeg"` como default canónico del transporte de red.
- **Por qué importa:** El path de producción es correcto (`run_node_a` pasa `codec` explícitamente), pero una llamada directa al factory o al adapter sin pasar `codec` comprimiría diferente a lo que el esquema declara como default — trampa para tests o uso programático.
- **Decisión de cierre:** default canónico `jpeg` para el transporte de red. `create_transport()` y
  `NetworkTransportAdapter` usan el mismo default que `CompressionConfig`; `serialize_unit()` conserva
  `raw` como default low-level/lossless.

### [M10] mm-gdino-large.yaml — catálogo sin runs que lo referencien
- **Archivo:** `configs/models/mm-grounding-dino/mm-gdino-large.yaml`
- **Evidencia:** Ningún run config lo usa via `ref:`. Sin embargo, `cli.py:124-127` sí lo descarga desde HF en `download-models`. La variante está en alcance operativo.
- **Decisión:** Aceptar como-está. La entrada existe porque los pesos se descargan; crear un run de bench para large está fuera del alcance de este commit.

### [M11] two_node.py — heartbeat puramente informativo (sin gating de liveness)
- **Archivo:** `src/eovrt_media/runtime/two_node.py:51`
- **Evidencia:** `is_peer_alive()` está implementado en `network.py:165-170` y `_last_heartbeat` se actualiza en el hilo PULL. Sin embargo, `run_node_a` nunca llama `is_peer_alive()`. Ante caída del consumidor, el productor sigue normalizando y descartando indefinidamente. Además, `wait_for_consumer()` hace `self._server.join()` sin timeout → bloquea indefinidamente si el consumidor muere antes de recibir END.
- **Por qué importa:** El heartbeat existe para liveness pero no tiene efecto de control. No rompe el camino feliz.
- **Decisión de cierre:** activar liveness efectiva en Nodo A después del primer heartbeat observado.
  Si el consumidor deja de emitir heartbeat, el productor corta ingesta, cierra el transporte y
  `wait_for_consumer(timeout_s=...)` evita bloqueo indefinido.

### [M12–M14] Timer granular
Cubierto por [M6]. Los tres hallazgos adicionales de la dimensión deadcode sobre timers
se resolvieron con el mismo cierre.

---

## Hallazgos confirmados — Nit (5)

| # | Archivo | Descripción | Acción |
|---|---|---|---|
| N1 | `deploy/docker-compose.yml:16` | `expose` lista solo `5555`; falta `5556` (heartbeat). Inofensivo en red bridge — todos los puertos son alcanzables entre contenedores. | Cerrado: agregar `"5556"` |
| N2 | `docs/deployment/two-node-docker.md` | Redirección de una línea. `docs/README.md` apunta a la guía vigente en `deploy/README.md`. | Aceptar — el redirect es claro |
| N3 | `src/eovrt_media/runtime/two_node.py:47` | `run_node_a` serializa `run_id=""` en el wire. Node B usa su propio `run_id` para todos los artefactos — inofensivo para trazabilidad de producción. | Aceptar |
| N4 | `deploy/docker-compose.node-b.yml` | Default apunta a `tcp://node-a:5555` (solo resuelve en compose combinado). El propio archivo y el README advierten que debe editarse para deploy real. | Aceptar |
| N5 | `deploy/docker-compose.yml:16` | Duplicado de N1 desde dimensión e2e-mediaplane. | Cerrado con N1 |

---

## Cierre aplicado

### Fixes aplicados

| Fix | Archivo(s) | Tipo | Riesgo |
|---|---|---|---|
| M1 — conteo vigente en implementation-status.md | `docs/implementation-status.md:130` | 1 línea | Nulo |
| M2 — nombrar normalización como `normalize_ms` | `src/eovrt_media/runtime/pipeline.py:255` | 1 línea | Muy bajo (solo cambia clave en JSON output) |
| M3 — eliminar app.py | `src/eovrt_media/app.py` | Delete | Nulo (sin consumidores) |
| M4 — limpiar hasattr en run_artifact_writer | `src/eovrt_media/sinks/run_artifact_writer.py:146-155` | Refactor menor | Bajo — misma semántica |
| M5 — HEARTBEAT en serialization.py | `src/eovrt_media/transport/serialization.py`, `tests/test_serialization.py`, `src/eovrt_media/transport/network.py` | Cleanup + test update + comentario | Bajo |
| M6 — limitar timers a etapas medidas | `src/eovrt_media/metrics/timers.py` | Delete | Bajo — nada los invoca |
| M7 — ampliar configs/README.md transport | `configs/README.md` | Docs | Nulo |
| M8 — agregar rtsp/oak_d a configs/README.md | `configs/README.md` | Docs | Nulo |
| M9 — unificar default `jpeg` de transporte de red | `src/eovrt_media/transport/factory.py`, `src/eovrt_media/transport/network.py`, `tests/test_transport_compression.py`, `tests/test_network_transport.py` | Código + tests | Bajo |
| M11 — liveness efectiva en Nodo A | `src/eovrt_media/runtime/two_node.py`, `src/eovrt_media/runtime/pipeline.py`, `src/eovrt_media/transport/network.py`, `tests/test_pipeline_two_threads.py`, `tests/test_network_transport.py` | Código + tests | Medio-bajo |
| N1/N5 — exponer heartbeat en compose local | `deploy/docker-compose.yml`, `tests/test_deploy_contract.py` | Config + test | Bajo |
| Contratos de artefactos — remover aliases planos v1 | `src/eovrt_media/contracts/events.py`, `src/eovrt_media/contracts/metrics.py`, `src/eovrt_media/sinks/jsonl_sink.py`, `tests/test_contracts.py`, `tests/test_jsonl_sink.py`, `tests/test_pipeline_mock.py` | Código + tests | Medio-bajo |

### Hallazgos conservados por decisión explícita

M10 (mm-gdino-large sin runs), N2 (redirección de deploy), N3 (`run_id` canónico en Nodo B)
y N4 (default `node-a` válido sólo para compose combinado, documentado para deploy real).

---

## Cierre de brechas vs planes

Los planes `media-plane-completion`, `deploy-validation-closure`, `infra-deploy` y `deploy-alignment` fueron auditados contra el código real. Todos los criterios de aceptación están cerrados:

1. **Conteo de tests en docs** (cubierto por fix M1).
2. **Commit único final** — cubierto por el commit de cierre de esta auditoría.

OAK-D queda correctamente marcado como deferred en `oak_d_source.py` (raises `NotImplementedError`) y en el ADR/docs pertinentes.

---

## Hallazgos rechazados (falsos positivos verificados)

### FP1 — "Node A con edge=[] falla si el adaptador importa torch al construirse"
**Refutado:** Ningún adaptador importa `torch` en `__init__` ni en `input_spec`. Los imports de `torch` en `yoloe_adapter.py` están bajo `TYPE_CHECKING` o dentro de métodos (`load/predict`). `grounding_dino_adapter.py` importa `torch` solo dentro de `_run_inference`. Node A con `edge=[]` funciona correctamente con la config de ejemplo.

### FP2 — "Preview en single-host dibuja sobre imagen letterboxed con cajas en espacio incorrecto"
**Refutado:** El comportamiento es correcto e intencional. Las cajas `RawDetection.box_xyxy` están en píxeles del espacio letterbox/modelo, coherente con dibujar sobre `item.payload` (que es la imagen letterboxed). `visualize.py` soporta float16 y uint8. En two-node, Node B no tiene acceso al archivo original — la consistencia entre modos es intencional.

---

## Seguimiento no bloqueante

Los siguientes puntos NO son bloqueantes y quedan como recomendaciones para el siguiente ciclo:

1. **Instrumentación adicional por etapa** (M6): si se necesita profiling más granular,
   cablear medición explícita en `image_loader` y en el hilo productor.
2. **Run de bench para mm-gdino-large** (M10): agregar configuración de experimento `b2_g_e7_mmgdino_l_{val,test}.yaml` cuando el hardware lo permita.
