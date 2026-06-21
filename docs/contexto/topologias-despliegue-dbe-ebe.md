# Topologías de despliegue del plano de medios

## Dos dimensiones independientes

El despliegue del plano de medios se define sobre dos dimensiones ortogonales:

- **Escenario**: DBE (fuente visual = dataset / archivos) o EBE (fuente visual = cámara / stream RTSP)
- **Topología**: un solo host o dos nodos distribuidos

Estas dimensiones son independientes. Conceptualmente todas las combinaciones son
válidas; su disponibilidad en este build es distinta:

| | Un host | Dos nodos |
|---|---|---|
| **DBE** | **implementado** — escenario principal | declarado — falta backend `network` |
| **EBE** | declarado — falta fuente `live` | declarado — faltan fuente viva y red |

(*) EBE ya implica alta complejidad de montaje (cámara real, entorno controlado, stream en vivo). Agregar la topología distribuida encima puede no aportar valor experimental suficiente para justificarlo dentro del alcance académico del proyecto. La combinación más informativa para comparar el impacto de la distribución es **DBE un host vs DBE dos nodos**, porque el escenario está completamente controlado y los resultados son reproducibles. EBE distribuido queda como combinación posible pero de prioridad baja.

La topología es una decisión de despliegue: **no cambia los contratos ni la lógica conceptual de los componentes; solo cambia el adaptador de comunicación entre responsabilidades** (ver "Qué cambia y qué no entre topologías").

---

## La variable raíz: fuente pulleable vs fuente viva

Antes de hablar de topologías, hay una variable que determina el comportamiento correcto del pipeline y que **no coincide exactamente con la etiqueta DBE/EBE ni con la topología**:

> ¿La fuente visual se puede frenar (pulleable) o no (push / viva)?

| | Fuente pulleable (archivos / DBE) | Fuente viva (cámara / EBE) |
|---|---|---|
| Mecanismo de control | Backpressure al lector | Buffer acotado + descarte de obsoletos |
| Pérdida de frames | Cero | Frames obsoletos descartados |
| Memoria | Acotada gratis (el productor se bloquea) | Acotada por `buffer_size` |
| Selección de frames | Determinista (todos o stride fijo) | Por frescura (depende del timing) |
| Reproducible | Sí | No — ni debe serlo |

De esta distinción se deriva casi todo lo demás:

- **Todo el aparato de descarte de frames (head drop, frescura) es, en el fondo, un asunto de fuente viva.** Con una fuente pulleable no se descarta nada: se frena el lector.
- El problema de memoria no acotada (ver `deterministic` más abajo) desaparece con fuentes pulleables, porque el backpressure bloqueante acota la cola sin necesidad de descartar.
- El default de política correcto **depende del tipo de fuente, no es global**.

---

## Arquitectura general del plano de medios

Independientemente del escenario y la topología, el plano de medios tiene esta estructura interna:

```
+-------------------------+
| External visual sources |
+----------+--------------+
           |
           v
+----------------------------------------------------------+
| MEDIA PLANE                                              |
|                                                          |
|  +----------------------------+                          |
|  | Visual ingestion adapter   |                          |
|  +-------------+--------------+                          |
|                |                                          |
|                v                                          |
|  +----------------------------+                          |
|  | Rate control               |                          |
|  +-------------+--------------+                          |
|                |                                          |
|                v                                          |
|  +----------------------------+                          |
|  | Visual normalization       |                          |
|  +-------------+--------------+                          |
|                |                                          |
|                v                                          |
|  +----------------------------+                          |
|  | OVD inference              |                          |
|  +-------------+--------------+                          |
|                |                                          |
|                v                                          |
|  +----------------------------+                          |
|  | Postprocessing             |                          |
|  +----------------------------+                          |
|                                                          |
+------------------------+---------------------------------+
                         |
                         v
           +-----------------------------+
           | Normalized perception event |
           +-----------------------------+
```

Las fuentes visuales son externas al plano. Ver `justificacion_fuentes_externas_plano_medios.md`.

---

## Política de rate control: dos modos

El acople entre Visual Normalization (productor) y OVD Inference (consumidor) se gobierna con una de dos políticas, configurable vía YAML. La política se elige **según el tipo de fuente**, no hay un default global.

### Política `deterministic` (default para fuente pulleable / DBE)

Procesa frames en orden, **sin descartar por timing**. El consumidor aplica backpressure: si la cola está llena, el lector de la fuente se bloquea hasta que se libere espacio. Con una fuente de archivo esto es trivial (el lector simplemente espera) y produce dos garantías clave para evaluación:

- **Reproducibilidad**: la corrida procesa siempre el mismo conjunto de frames, independientemente de cuánto tarde la inferencia en esa máquina o ese momento. Dos corridas del mismo dataset con el mismo modelo dan el mismo resultado; el modelo A y el modelo B se comparan sobre exactamente la misma evidencia.
- **Memoria acotada gratis**: el backpressure bloqueante limita la cola sin política de descarte.

> **Por qué `realtime`/frescura está MAL como default en DBE**: si se descartaran frames según el reloj de pared (cuánto tardó la inferencia), corridas distintas procesarían frames distintos. Eso rompe la comparabilidad, que es el propósito mismo de DBE. El descarte por frescura no es solo "no ideal" en DBE: es incorrecto.

La selección determinista no obliga a procesar *todos* los frames. Un clip de 10 min a 30 fps son 18.000 frames; `stride` permite procesar 1 de cada N de forma determinista (independiente del timing → sigue siendo reproducible).

```yaml
rate_control:
  policy: deterministic
  stride: 1            # 1 = todos los frames; N = cada N (selección determinista)
  max_queue_size: 8    # backpressure: el lector se bloquea si la cola se llena
```

**Fuente viva con `deterministic`**: una cámara no se puede frenar. Si se usa `deterministic` con una fuente viva (caso atípico), no hay backpressure posible y la cola crecería sin control. Por eso `max_queue_size` es un límite duro con comportamiento de overflow explícito (`fail_run` por defecto) — nunca una cola infinita.

### Política `bounded_freshness` (default para fuente viva / EBE)

Buffer de **capacidad N con head drop**: cuando el productor genera un frame nuevo y el buffer está lleno, se descarta el frame más antiguo y se encola el nuevo. El consumidor toma el más antiguo de los que sobrevivieron — que sigue siendo reciente porque los obsoletos ya fueron eliminados. El descarte está atado a vigencia temporal, no es arbitrario: si el buffer está lleno, el frame más antiguo perdió relevancia frente a los más nuevos.

> **Precisión semántica**: el consumidor **no** recibe siempre "el frame más reciente disponible" — recibe un frame *reciente dentro de una cola acotada*. La política acota la **antigüedad máxima** descartando evidencia obsoleta; no garantiza el último frame. El caso `buffer_size: 1` sí da semántica latest-only (el buffer siempre contiene únicamente el más nuevo); por eso no hace falta una política `latest_only` separada — es el caso N=1.

```
Productor (normalización, continuo)        Consumidor (inferencia)

  frame → normalizar                          toma el más antiguo del buffer
      │                                        (reciente, no obsoleto)
      ▼
  escribir en buffer (cap=N)
      ├─ no lleno → escribir
      └─ lleno    → head drop:
                    descartar el más antiguo
                    encolar el nuevo
```

El tamaño N (`buffer_size`) acota la antigüedad máxima de la percepción:

| `buffer_size` | Antigüedad máxima al procesar* | Comportamiento |
|---|---|---|
| 1 | ~1 ciclo de inferencia | Latest-only. Máxima frescura, descarte agresivo |
| 2–3 | ~2–3 ciclos de inferencia | **Balance recomendado** para tiempo real |
| 5–10 | varios segundos | Frescura baja, menor riesgo de cola vacía |

*Estimado para inferencia a 5 fps (200 ms/ciclo) y normalización a 30 fps.

`buffer_size: 1` es válido pero agresivo: descarta frames que podrían haberse procesado sin coste real para la percepción, y puede dejar la cola vacía justo cuando el consumidor está listo. El rango 2–3 evita ese caso manteniendo la antigüedad baja.

Opcionalmente, el descarte puede atarse al **tiempo** además del conteo. `VisualUnit` lleva timestamp; `max_staleness_ms` descarta cualquier frame cuya antigüedad supere el umbral, acotando la antigüedad en milisegundos de forma independiente del tamaño del buffer — un criterio más principista para justificar "tiempo real":

```yaml
rate_control:
  policy: bounded_freshness
  buffer_size: 2          # N>=1; N=1 da semántica latest-only
  max_staleness_ms: 200   # opcional: descarta también por edad del frame
```

### El rate efectivo emerge del consumidor

En `bounded_freshness` no hay parámetro de FPS a configurar: el ritmo lo impone la velocidad de OVD inference. Rate control es pasivo — solo decide qué frame entregar cuando el consumidor está listo, no a qué velocidad.

---

## Topología de un solo host

Todos los componentes se ejecutan en la misma máquina. Para el prototipo inicial pueden integrarse en un único proceso o en procesos locales; **lo relevante no es "mismo proceso" sino que no existe un salto de red inter-host en la ruta crítica**. El acople productor/consumidor se implementa como una cola en memoria (o IPC local) entre Visual Normalization y OVD Inference, con la política descrita arriba.

```
+------------------------------------------------------------------------------------+
| HOST ÚNICO  (sin salto de red inter-host en la ruta crítica)                      |
|                                                                                    |
|  Fuente visual                                                                     |
|          |                                                                         |
|          v                                                                         |
|  [ Visual ingestion adapter ]                                                      |
|          |  VisualUnit                                                             |
|          v                                                                         |
|  [ Rate control ]                                                                  |
|          |  VisualUnit (gated)                                                     |
|          v                                                                         |
|  [ Visual normalization ]  ──→  [ cola en memoria / IPC local ]  ──→  [ OVD inference ]
|                                  policy + buffer_size                     |  RawDetection[]
|                                                                           v        |
|                                                                [ Postprocessing ]  |
|                                                                           |        |
|                                                                           v        |
|                                                                Normalized perception event
|                                                                                    |
+------------------------------------------------------------------------------------+
```

Es la topología más simple y la primera a implementar. Con DBE (default `deterministic`) ni siquiera hay descarte: el lector se frena y se procesa todo en orden.

---

## Topología distribuida — dos nodos

El plano de medios se divide en dos nodos conectados por red LAN cableada (Ethernet, latencia <1 ms). La cola entre normalización e inferencia pasa a ser un enlace de red, pero la **política de rate control es la misma** — solo cambia el adaptador de transporte (cola en memoria → socket de red).

```
+----------------------------------------------+          +----------------------------------------------+
| NODO A                                       |          | NODO B                                       |
|                                              |          |                                              |
|  Fuente visual                               |          |                                              |
|          |                                   |          |                                              |
|          v                                   |          |                                              |
|  [ Visual ingestion adapter ]                |          |                                              |
|          |  VisualUnit                        |          |                                              |
|          v                                   |          |                                              |
|  [ Rate control ]                            |          |                                              |
|          |  VisualUnit (gated)                |          |                                              |
|          v                                   |  ──────> |  [ OVD inference ]                           |
|  [ Visual normalization ]                    |          |          |  RawDetection[]                   |
|          |  VisualUnit (payload configurable) | <─────── |          v                                   |
|          └──→ buffer (policy, cap=N) ────────|  REQUEST |  [ Postprocessing ]                          |
|                                              |          |          |                                   |
+----------------------------------------------+          |          v                                   |
                                                          |  Normalized perception event                 |
                                                          |                                              |
                                                          +----------------------------------------------+
```

### Punto de corte: después de Visual normalization

- **Nodo A** concentra ingesta, rate control y normalización — opera sobre la fuente visual y produce unidades listas para inferencia.
- **Nodo B** concentra inferencia y postproceso — requiere GPU; consume unidades, produce eventos de percepción.
- Inferencia y postproceso van juntos en Nodo B porque postproceso opera directamente sobre `RawDetection[]` producido por inferencia; separarlos no tiene sentido.

### Representación física del payload (no obligar a float32)

El corte es lógico: lo que cruza la red es una `VisualUnit` **normalizada semánticamente para la corrida**. Pero su representación física **no tiene por qué ser siempre un tensor float32**. Un tensor 640×640×3 float32 ≈ 4.9 MB; a 5 fps son ~25 MB/s, perfectamente manejable en LAN gigabit, pero es desperdicio de ancho de banda.

Fix concreto: transportar **uint8 RGB redimensionado** (≈1.2 MB, 4× menos) y hacer el cast a float + normalización mean/std en el Nodo B, pegado a la GPU justo antes de inferir. El resize es la decisión cara/con pérdida y pertenece al Nodo A; el cast a float es trivial y pertenece al lado del modelo. El formato físico se declara en configuración:

```yaml
transport:
  payload_format: uint8_rgb   # uint8_rgb (default) | fp16 | fp32
  # con uint8_rgb: resize en Nodo A; cast a float + normalización en Nodo B
```

A la escala actual del proyecto (una cámara, ~5 fps, LAN gigabit) float32 también funciona; mantener el formato configurable evita cuestionamientos de escalado sin obligar a sobre-diseñar.

### Mecanismo: pull model

Nodo B envía un `REQUEST` cada vez que termina de procesar un frame. Nodo A responde con un frame del buffer según la política activa (`bounded_freshness` en EBE: el más antiguo de los sobrevivientes).

```
Flujo de señales (LAN cableada Ethernet):

  Nodo A                                  Nodo B
      │                                       │
      │  [normaliza continuamente;            │
      │   buffer policy + cap=N]              │
      │                                       │
      │  <─── REQUEST ───────────────────     │  (termina inferencia)
      │                                       │
      │  toma frame del buffer (reciente, no obsoleto)
      │  ─── VisualUnit ─────────────────>    │
      │                                       │  (inferencia en curso...)
      │  [frames nuevos → head drop si lleno] │
      │                                       │
      │  <─── REQUEST ───────────────────     │  (termina inferencia)
      │  ...                                  │
```

### Casos de borde

- **Arranque**: Nodo B envía el primer REQUEST al iniciar. Nodo A no envía nada hasta recibirlo.
- **Nodo B lento por burst** (imagen compleja, modelo cargando): Nodo A sigue normalizando y aplicando head drop. Cuando Nodo B pida, recibirá un frame reciente del buffer.
- **Buffer vacío al REQUEST**: si Nodo B pide antes de que Nodo A tenga un frame listo (arranque, pausa de fuente), el sender espera hasta que haya uno.
- **Heartbeat**: independiente del flujo de frames, ambos nodos intercambian un keep-alive periódico para distinguir Nodo B lento de Nodo B desconectado.

### Protocolo de transporte entre nodos

| Señal | Dirección | Contenido |
|---|---|---|
| `REQUEST` | Nodo B → Nodo A | "listo para el siguiente frame" |
| `VisualUnit` | Nodo A → Nodo B | frame del buffer, en el `payload_format` configurado |
| `HEARTBEAT` | bidireccional | keep-alive periódico |

Protocolo de transporte a definir al implementar (candidatos: ZeroMQ, gRPC). La elección no afecta los contratos ni la lógica conceptual de los componentes.

---

## Qué cambia y qué no entre topologías

**No cambia** (el núcleo defendible):

- Los **contratos semánticos**: el significado de `VisualUnit`, `RawDetection`, `DetectionEvent`.
- La **lógica conceptual** de cada componente.
- El **contrato de salida** del plano: `Normalized perception event`.
- La **política de rate control** y su semántica.

**Sí cambia** (el adaptador de comunicación entre responsabilidades):

- Serialización y transporte (cola en memoria / IPC local / socket de red).
- Protocolo REQUEST/RESPONSE, heartbeat, timeouts, reconexión.
- Representación física del payload sobre el enlace.
- Medición de red y manejo de relojes entre nodos.

> La afirmación correcta no es "la implementación interna no cambia", sino: **la topología no cambia los contratos ni la lógica conceptual; solo cambia el adaptador de comunicación.** El acople productor/consumidor es siempre un "adaptador de transporte" con un mismo contrato y tres backends posibles: cola en memoria, IPC local, socket de red.

---

## Estado de implementación

- **Un host — DBE**: implementado. El productor y consumidor se desacoplan con
  `TransportAdapter(memory)`; `deterministic` aplica backpressure y `RateGate` mantiene
  reproducibilidad con stride fijo.
- **Un host — EBE**: la política `bounded_freshness`, el head-drop y la configuración
  `source.kind=live` ya existen. Falta `LiveSource` para cámara/RTSP y timestamps de captura
  que hagan significativa la métrica de frescura.
- **Dos nodos — DBE**: contratos REQUEST/RESPONSE/HEARTBEAT, `NetworkTransportAdapter` y
  gating de `topology.mode=two_node` existen; falta implementar serialización, red y reconexión.
- **Dos nodos — EBE**: combina los pendientes de fuente viva y red; mantiene prioridad baja.

`ipc`, `network`, `two_node` y `payload_format=fp16` no hacen fallback silencioso: el loader
o el factory fallan explícitamente. La política de rate control y el formato de payload siguen
siendo configurables mediante YAML. El detalle operativo y los límites conocidos viven en
[implementation-status.md](../implementation-status.md).
