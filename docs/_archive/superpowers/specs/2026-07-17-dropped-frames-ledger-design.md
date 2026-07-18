# Registro por-frame de descartes — Diseño (Pieza A2)

**Fecha**: 2026-07-17
**Estado**: aprobado en brainstorming; pendiente de plan de implementación
**Repo**: `e-ovrt_media-plane`
**Alcance**: el media-plane registra **por-frame** qué frames se descartaron y por qué, y lo
expone por HTTP, para reconstruir post-hoc el ciclo de vida completo de cada frame.

## 1. Propósito y contexto

Esta es la **pieza A2** de una feature de tres piezas que cruza tres repos:

- **A — control-plane**: progreso parcial de patrones (spec aparte).
- **A2 (este spec) — media-plane**: registro por-frame de descartes internos.
- **B — webconsole**: la vista correlacionada (ciclo de diseño aparte), que consume A + A2
  + los artefactos existentes.

A y A2 son **ortogonales** (repos distintos, se construyen y testean por separado). Ambas
son cimiento de B. Este spec cubre solo A2.

**Modo: post-hoc.** El ledger se escribe durante la corrida y se relee una vez terminada.
Sin streaming en vivo.

## 2. El problema que resuelve

Hoy el media-plane **cuenta** los descartes pero no registra **cuáles**. Un frame puede no
llegar a ser procesado (ni a emitir detección) por cuatro motivos, y ninguno deja rastro
por-frame:

| Motivo | Dónde | Hoy queda registrado |
|---|---|---|
| `rate_gate` — submuestreo por stride (intencional) | `transport/rate_gate.py`, aplicado en `runtime/pipeline.py:81-84` | nada (ni siquiera contado) |
| `queue_full` — cola `bounded_freshness` llena, se hace `popleft` | `transport/memory.py:53-54` | solo `units_dropped` (agregado) |
| `staleness_timeout` — unidad vencida por `max_staleness_ms` | `transport/memory.py:109-113` | solo `units_dropped` (agregado) |
| `channel_closed` — canal cerrado al ofrecer | `transport/memory.py:49` | solo `units_dropped` (agregado) |

El detalle "qué `frame_index` específico se cayó" **no existe post-hoc** — se descarta en
silencio. Esta feature lo materializa.

**Límite upstream — submuestreo de la fuente**: en video, `VideoFileSource` selecciona por
`target_fps` qué `frame_index` del archivo emite (`sources/video_file_source.py:66-85`);
los no elegidos **jamás entran al pipeline** y NO son descartes: son el muestreo declarado
de la corrida. El ledger cubre desde la emisión de la fuente hacia adelante. Esos huecos se
explican por parámetro (`target_fps`/`fps` en el summary), no por registro.

Nota sobre el otro punto de descarte (bus media→control, EBE): **NO es parte de A2.** Se
deriva en la pieza B cruzando los `unit_id` de `detections.jsonl` (lo que el media-plane
envió) contra el `metrics.jsonl` del control-plane (lo que recibió); la diferencia son los
drops del bus, recuperable sin instrumentación nueva.

## 3. Decisiones cerradas

| # | Decisión | Razón |
|---|---|---|
| D1 | Registrar **los cuatro** motivos, incluido `rate_gate` | El usuario quiere el ledger completo de todo frame no procesado; el campo `reason` permite separar intencional (`rate_gate`) de falla real |
| D2 | Artefacto **nuevo** `dropped_units.jsonl`, un registro por descarte | No toca `detections.jsonl` ni `metrics.jsonl` ni `summary.json` |
| D3 | `units_dropped` del summary **queda igual** | Retrocompatible; el ledger complementa, no reemplaza |
| D4 | Endpoint nuevo `GET /api/runs/{id}/dropped`, simétrico a `/detections` | Reusa el patrón de lectura paginada del jsonl |
| D5 | **Todos** los registros llevan identidad completa (`unit_id`, `frame_index`, `timestamp_ms`, `source_clock`) | Verificado en código: la unidad que el rate-gate descarta es un `VisualUnit` ya emitido por la fuente con identidad estampada (`contracts/visual_unit.py`); no hay motivo para un registro pobre |

## 4. El registro

Contrato `media.dropped_unit.v1`, un registro (línea JSON) por frame descartado:

```
{
  schema_version: "media.dropped_unit.v1",
  run_id,
  reason: "rate_gate" | "queue_full" | "staleness_timeout" | "channel_closed",
  frame_index, unit_id, timestamp_ms, source_clock,   # identidad completa en TODOS los reasons (D5)
  dropped_wallclock_ms         # cuándo se descartó (epoch ms, misma base que capture_wallclock_ms)
}
```

- **`rate_gate`**: se emite en `run_producer_loop` (`pipeline.py:81-84`) cuando
  `rate_gate.should_pass(source_index)` es falso. La unidad descartada es el `VisualUnit`
  crudo que la fuente ya emitió, con identidad completa. Ojo: el gate filtra por
  `source_index` (posición de enumeración), pero el registro lleva la identidad propia de la
  unidad (`unit.frame_index`, que en video es el índice real del archivo).
- **`queue_full` / `staleness_timeout` / `channel_closed`**: se emiten en los tres puntos de
  `MemoryTransportAdapter` (`memory.py:49,53-54,109-113`). La unidad descartada es un
  `NormalizedUnit`, también con identidad completa.

## 5. Emisión y persistencia

- **Rate-gate**: hoy `pipeline.py:81-84` hace `continue` sin registrar. Se agrega la
  escritura del registro `rate_gate` antes del `continue`.
- **Transporte**: hoy `memory.py` hace `self.units_dropped += 1` en los tres puntos. Se
  agrega la escritura del registro correspondiente **junto** al incremento (el contador
  sigue, D3). Como el adaptador de transporte no tiene hoy referencia al writer de
  artefactos, se le inyecta un callback/sink de descartes (una función
  `on_drop(record) -> None`), manteniendo el adaptador desacoplado del `RunArtifactWriter`
  concreto.
- **Thread-safety obligatoria**: los drops del rate-gate y de `offer()` ocurren en el hilo
  **productor**; el drop por staleness en `request()` puede ocurrir en el **consumidor**. El
  sink de descartes recibe escrituras desde dos hilos → debe serializar (lock alrededor del
  write de línea). No reusar a ciegas un writer pensado para un solo hilo.
- **Persistencia**: `RunArtifactWriter` (o un writer hermano) escribe
  `runs/<id>/dropped_units.jsonl`, un registro por línea, con el mismo patrón de escritura
  que `detections.jsonl` / `metrics.jsonl`. `detections.jsonl`, `metrics.jsonl` y
  `summary.json` quedan **byte-idénticos** a lo que son hoy.

## 6. El endpoint

`GET /api/runs/{run_id}/dropped?page=&page_size=` en el media-plane
(`src/eovrt_media/service/routers/runs.py`), simétrico a `/detections`
(`service/routers/runs.py:81`): lee `dropped_units.jsonl`, pagina por slicing, devuelve
`{ page, page_size, total, items }`.

- **200**: página de registros (posiblemente vacía).
- **404**: run inexistente.
- Run sin `dropped_units.jsonl` (nada se descartó): **200 con `total: 0`, `items: []`**, no
  404 — cero descartes es un resultado válido y bueno.

## 7. Volumen — consecuencia consciente de D1

Con `rate_gate` incluido y `stride` alto, el ledger puede ser grande (con `stride=5` registra
4 de cada 5 frames). Es la consecuencia aceptada de querer el ledger completo. Mitigaciones
de diseño: (a) el campo `reason` permite que la consola filtre `rate_gate` de un vistazo; (b)
el endpoint pagina; (c) `dropped_units.jsonl` es un artefacto aparte, así que no pesa sobre
la lectura de `detections.jsonl`.

## 8. Fuera de alcance

- **Topología two-node (EBE distribuido)**: A2 es **single-host**. En two-node los descartes
  del buffer ocurren en el Nodo A (ingesta), que no es dueño del `run_dir`; el Nodo B (dueño
  de los artefactos) es el consumidor de red y no tiene el buffer con drops. Por eso en
  two-node `dropped_units.jsonl` **no se escribe** y `GET /api/runs/{id}/dropped` devuelve
  `200 []` — que en ese modo significa "no instrumentado", no "cero descartes". Cablearlo
  requeriría que el Nodo A shipee los registros al Nodo B: es un follow-up de diseño propio,
  no parte de A2. **Consecuencia para la pieza B**: para runs two-node, el detalle de
  descartes internos del media-plane no estará disponible (sí lo estarán los drops del bus,
  derivables por set-difference); la vista debe distinguir "ledger vacío" de "run two-node"
  mirando `summary.run_descriptor.topology`.
- **Drops del bus media→control**: se derivan en B (set-difference de `unit_id`), no se
  instrumentan acá.
- **Streaming en vivo** del ledger.
- **La vista** (pieza B).
- Cambiar `units_dropped`, `detections.jsonl`, `metrics.jsonl` o `summary.json`.

## 9. Testing

- **Un registro por descarte, con el reason correcto**: forzar cada uno de los cuatro
  caminos (stride que saltea; cola llena → `queue_full`; unidad vencida →
  `staleness_timeout`; canal cerrado → `channel_closed`) y verificar el registro emitido.
- **Identidad completa en todos los reasons** (D5): `unit_id`/`frame_index`/`timestamp_ms`/
  `source_clock` poblados tanto en `rate_gate` (del `VisualUnit` crudo) como en los tres del
  transporte (del `NormalizedUnit`).
- **Correlación**: los `frame_index`/`unit_id` del ledger no se solapan con los de
  `detections.jsonl` (un frame o se procesó o se descartó, nunca ambos).
- **`units_dropped` invariante**: el conteo agregado del summary sigue coincidiendo con los
  descartes del transporte (los tres reasons no-`rate_gate`), sin cambio de comportamiento.
- **Endpoint**: 200 paginado, `page`/`page_size` respetados, run inexistente → 404, run sin
  descartes → 200 con `total: 0`.
- **No-regresión**: `detections.jsonl`, `metrics.jsonl`, `summary.json` byte-idénticos.

## 10. Criterios de éxito

1. Una corrida con `stride>1` y algo de backpressure genera `dropped_units.jsonl` con
   registros de los cuatro (o los que apliquen) motivos, cada uno con su `reason`.
2. `GET /api/runs/{id}/dropped` los devuelve paginados, uniéndose con `detections.jsonl` por
   `frame_index`/`unit_id`.
3. La unión "procesados (detections) ∪ descartados (dropped) por `frame_index`" cubre
   **todos los frames que la fuente emitió al pipeline** sin huecos inexplicados. (Los
   frames que la fuente no emitió por submuestreo `target_fps` quedan fuera por diseño y se
   explican por parámetro, ver §2.)
4. `units_dropped`, `detections.jsonl`, `metrics.jsonl`, `summary.json` no cambian; tests
   previos verdes.
5. Cero descartes → endpoint 200 con lista vacía, sin error.
