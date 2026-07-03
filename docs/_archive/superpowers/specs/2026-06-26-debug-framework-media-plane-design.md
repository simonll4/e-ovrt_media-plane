# Diseño: framework de debug del media plane v1

## Objetivo

Crear un framework de debug para ejecutar campañas de prueba del media plane,
capturar trazas estructuradas durante la corrida y detectar brechas operativas,
warnings, errores ocultos y oportunidades de optimización. La primera versión
debe servir para iterar rápido sobre el banco nativo two-node y sobre corridas
single-host existentes, sin convertir todavía el sistema en un servicio
productivo permanente.

El framework debe producir evidencia auditable. Cada corrida conserva sus
eventos propios y cada campaña agrupa resultados comparables en una sesión de
debug.

## Principios

- No duplicar el runtime del media plane: reutilizar `run-two-node-local`,
  `run-producer`, `run-consumer`, `summary.json`, `metrics.jsonl`,
  `errors.jsonl`, `run_manifest.json` y `run_provenance.json`.
- Los logs humanos no son suficientes: las señales críticas se escriben como
  eventos JSONL estructurados.
- El modo debug debe ser activable; las corridas normales no deben llenarse de
  ruido.
- El framework debe priorizar diagnóstico reproducible antes que UI visual.
- Los reportes deben señalar riesgos concretos y rutas de artefactos, no solo
  imprimir tablas.

## Artefactos

Cada corrida puede incluir:

```text
runs/run_20260626_120000_ebe_yoloe_deterministic/
  debug_events.jsonl
```

Cada campaña de debug genera:

```text
runs/debug-sessions/20260626-bench-val-yoloe/
  session_config.yaml
  session_report.json
  session_report.md
  generated-configs/
  logs/
```

`debug_events.jsonl` viaja con la corrida y explica qué ocurrió dentro del run.
La sesión agrupa múltiples corridas, logs de nodos, configs generadas y el
análisis comparativo.

## CLI

Nuevo comando principal:

```bash
eovrt-media debug-run \
  --source bench-val \
  --model-ref yoloe/yoloe-26s \
  --device cuda:0 \
  --codecs raw,jpeg \
  --max-units 50 \
  --debug
```

Parámetros v1:

- `--source`: perfiles existentes del banco local (`bench-val`, `bench-test`,
  `demo`, `video`, `ezviz`).
- `--video`: path requerido para `--source video`.
- `--rtsp-url`: URL requerida para `--source ezviz` si no existe
  `EZVIZ_RTSP_URL`.
- `--model-ref`: default `yoloe/yoloe-26s`.
- `--device`: default `cuda:0`.
- `--codecs`: lista separada por coma, default `raw,jpeg`.
- `--payload-format`: default `uint8_rgb`.
- `--max-units`: límite por corrida.
- `--session-id`: opcional; si se omite se genera por timestamp y fuente.
- `--debug/--no-debug`: activa trazas estructuradas.
- `--skip-probe`: pasa al flujo RTSP.

La v1 ejecuta una matriz simple: una corrida por codec. La ampliación a matrices
modelo x fuente x payload_format queda para una versión posterior.

## Componentes

### `DebugEventWriter`

Responsabilidad: escribir `debug_events.jsonl` con un contrato estable.

Campos mínimos:

```json
{
  "schema_version": "media.debug.v1",
  "ts": "2026-06-26T00:00:00.000000+00:00",
  "run_id": "run_x",
  "node": "A",
  "stage": "transport",
  "event": "offer",
  "unit_id": "frame_000001",
  "elapsed_ms": 1.23,
  "payload_bytes": 921344,
  "codec": "jpeg",
  "device": "cuda:0",
  "message": null,
  "extra": {}
}
```

El writer debe aceptar `enabled=False` y convertirse en no-op para no ensuciar
corridas normales.

### `DebugContext`

Responsabilidad: transportar el modo debug, rutas y writer a runtime,
transporte, modelo y sinks con bajo acoplamiento.

La v1 puede integrarlo de forma pragmática:

- `RunContext` conoce `debug_enabled` y `debug_events_path`.
- `RunArtifactWriter` abre el `DebugEventWriter` si debug está activo.
- Runtime y transporte reciben un writer opcional o helper no-op.

### Instrumentación Estratégica

Nodo A:

- `source.start`, `source.unit_read`, `source.end`.
- `rate.pass`, `rate.drop`.
- `normalize.start`, `normalize.end`, `normalize.error`.
- `transport.offer`, con `payload_bytes`, `payload_format`, codec efectivo.
- `transport.end_sent`.
- `heartbeat.peer_seen`, `heartbeat.peer_lost`, `heartbeat.peer_alive`.
- `producer.stop`, con razón.

Nodo B:

- `transport.start`, `heartbeat.start`.
- `model.load_start`, `model.load_end`, `model.load_error`.
- `model.warmup_start`, `model.warmup_end` cuando sea observable.
- `transport.request`, `transport.receive`, `transport.end_received`.
- `inference.start`, `inference.end`, `inference.error`.
- `postprocess.end`, `write.end`.
- `shutdown.start`, `shutdown.end`.

Wrapper/banco local:

- `session.config_written`.
- `process.start`, con comando sanitizado, PID, nodo y log path.
- `process.exit`, con código de salida.
- `run.resolved`, con `run_id` y `run_dir`.

Transporte:

- codec efectivo (`raw` o `jpeg`).
- tamaño serializado del mensaje.
- fallback a raw cuando JPEG no aplica.
- errores de serialización/deserialización.

## `DebugSessionRunner`

Responsabilidad: orquestar campañas usando el banco local existente.

Flujo:

1. Crear un directorio de sesión como `runs/debug-sessions/20260626-bench-val-yoloe/`.
2. Persistir `session_config.yaml`.
3. Por cada codec solicitado:
   - llamar al banco local con debug activo;
   - copiar config generada a `generated-configs/`;
   - copiar o referenciar logs de Nodo A/B en `logs/`;
   - registrar `run_id`, `run_dir`, retorno y duración.
4. Invocar `RunAnalyzer` por run.
5. Invocar `SessionReporter`.

La v1 puede ejecutar corridas secuencialmente. La ejecución paralela queda fuera
de alcance porque dificulta aislar GPU, logs y uso de puertos durante diagnóstico.

## `RunAnalyzer`

Responsabilidad: leer artefactos de una corrida y producir señales.

Entradas:

- `summary.json`
- `metrics.jsonl`
- `errors.jsonl`
- `debug_events.jsonl`
- logs de Nodo A/B
- `run_manifest.json`
- `run_provenance.json`

Señales v1:

- corrida incompleta o sin `summary.json`;
- `units_failed > 0`;
- líneas en `errors.jsonl`;
- warnings, errors, tracebacks o runtime errors en logs;
- `p95_latency_ms` o `p99_latency_ms` sobre umbral configurable;
- inferencia domina latencia total;
- normalización domina latencia total;
- `units_dropped > 0`;
- `backpressure_wait_ms > 0`;
- VRAM pico sobre umbral configurable;
- diferencia relevante entre detecciones RAW/JPEG;
- diferencia relevante entre latencia RAW/JPEG;
- `debug_events.jsonl` ausente cuando debug estaba activo;
- `run_id` no resuelto por el wrapper.

Cada señal debe tener:

- `severity`: `info`, `warning`, `error`.
- `code`: identificador estable.
- `message`: texto breve.
- `evidence`: rutas y valores medidos.
- `suggestion`: acción concreta de investigación.

## `SessionReporter`

Responsabilidad: producir salida legible y machine-readable.

`session_report.json`:

- configuración de sesión;
- lista de corridas;
- resumen por corrida;
- señales por corrida;
- comparaciones entre corridas;
- rutas de artefactos.

`session_report.md`:

- tabla resumen;
- hallazgos ordenados por severidad;
- comparación RAW/JPEG;
- próximos pasos recomendados.

## Umbrales Iniciales

Defaults v1:

- `p95_latency_ms > 2000`: warning.
- `p99_latency_ms > 3000`: warning.
- `units_failed > 0`: error.
- `errors.jsonl` no vacío: error.
- `units_dropped > 0`: warning.
- `backpressure_wait_ms > 0`: info.
- `gpu_memory_peak_mb > 7000`: warning en GPU de 8GB.
- diferencia RAW/JPEG de detecciones mayor a 20%: warning.
- diferencia RAW/JPEG de p95 mayor a 30%: info.

Los umbrales deben poder vivir en `session_config.yaml`, aunque la v1 use
defaults si no se especifican.

## Fuera De Alcance v1

- Dashboard web o UI interactiva.
- Hot-swap dinámico de fuentes.
- Runner productivo permanente.
- Matriz paralela de corridas.
- Análisis estadístico avanzado sobre muchas repeticiones.
- Integración con OpenTelemetry externa.
- Alertas/notificaciones.
- Reescritura del contrato de métricas existente.

## Testing

La implementación debe cubrir:

- contrato de `DebugEventWriter`;
- no-op cuando debug está apagado;
- escritura de `debug_events.jsonl` dentro del run;
- parsing de `metrics.jsonl`, `errors.jsonl`, logs y summary;
- señales de error por run incompleto;
- señales de warning por latencia alta, drops y logs con traceback;
- reporte JSON y Markdown;
- CLI `debug-run` con runner fakeado;
- integración mínima con `mock` y `max_units=2` usando el banco local.

Verificación mínima:

```bash
pytest -q
ruff check src tests
git diff --check
```

Validación manual esperada:

```bash
eovrt-media debug-run \
  --source bench-val \
  --model-ref yoloe/yoloe-26s \
  --device cuda:0 \
  --codecs raw,jpeg \
  --max-units 5 \
  --debug
```

Debe producir una sesión con dos corridas, ambas con `debug_events.jsonl`, y un
reporte que compare RAW vs JPEG.
