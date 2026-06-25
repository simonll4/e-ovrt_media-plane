# Diseño: cierre funcional del media plane

**Fecha:** 2026-06-24  
**Estado:** implementado y verificado (204 pruebas + Docker FP16 E2E)

## Propósito

Completar todas las capacidades declaradas pero no implementadas del plano de
medios. Tras este trabajo, la única capacidad diferida será `OakDSource` para
OAK-D Pro PoE, que requiere el SDK y hardware DepthAI.

## Alcance

La entrega implementa y prueba cuatro capacidades:

1. `PayloadFormat.FP16` de extremo a extremo: normalización, validación de YAML,
   serialización msgpack y transporte ZeroMQ.
2. Preparación tensorial común aplicada realmente por Grounding DINO y YOLOE.
3. Previews anotados para toda fuente y topología, incluidos vídeo, RTSP y Nodo B.
4. Heartbeat dedicado PUSH/PULL, separado del canal REQ/REP de datos.

No cambia la política de frescura, la topología general producer/consumer, ni
agrega un SDK de OAK-D.

## FP16 de transporte

`normalize_spatial()` conservará el resize y transform existentes y emitirá
`float16` normalizado a `[0, 1]` cuando el YAML seleccione `payload_format: fp16`.
La tabla de dtypes del wire incluirá `np.float16`; el formato raw preserva dtype,
shape y metadata. JPEG continúa aplicándose exclusivamente a `uint8_rgb`; una
configuración JPEG+FP16 usa raw de forma explícita y comprobable.

El loader aceptará FP16 para `network` y `memory`. Los adaptadores convertirán o
consumirán el payload sin recuperar precisión ficticia. Las pruebas cubren
normalización, round-trip raw y productor/consumidor de red.

## Preparación tensorial común

`prepare_model_input()` será el único paso que convierte el payload espacialmente
normalizado a BCHW, aplica escala, mean/std y mueve a device. Cada adaptador
conserva su propia preparación de texto y postproceso:

- Grounding DINO crea los tokens de texto con su processor y recibe el tensor común
  como `pixel_values`.
- YOLOE recibe el tensor BCHW directamente por la ruta de inferencia de Ultralytics,
  sin conversión intermedia a PIL.

La precisión de inferencia existente (`half_precision`) se mantiene como decisión de
runtime CUDA, separada del formato de transporte. Tests verifican que `forward()` no
construye PIL y que CPU conserva la semántica actual.

## Previews autocontenidos

El consumidor ya posee el payload normalizado de cada unidad, incluso cuando no
tiene acceso al path original del edge. Antes de reproyectar las detecciones a la
imagen original, renderiza las detecciones crudas sobre una conversión RGB de ese
payload y persiste el preview.

El renderer acepta arrays RGB además de paths. Sus cajas usan el espacio de modelo;
el resultado es un preview de tamaño objetivo, que preserva el letterbox cuando
corresponda. Esta elección evita enviar una segunda imagen por la red y hace que
vídeo, RTSP, imágenes y Nodo B generen el mismo artefacto sin montar el dataset del
productor.

## Heartbeat dedicado

El canal de datos conserva ZeroMQ REQ/REP. Se agrega un canal de control:

- Nodo A crea un socket PULL y bindea `transport.heartbeat_endpoint`.
- Nodo B crea un socket PUSH, conecta al endpoint de heartbeat y emite `HEARTBEAT`
  cada `heartbeat_interval_ms` en un hilo propio.
- Nodo A actualiza la liveness sólo al recibir esos pulsos; `heartbeat_timeout_ms`
  define el límite de `is_peer_alive()`.

El endpoint es explícito en YAML y por tanto cambia entre el bind del edge
(`tcp://0.0.0.0:5556`) y el connect del GPU (`tcp://edge-host:5556`). Los manifests
publican también TCP/5556 en el modo dos hosts. El apagado cierra sockets e hilos de
forma idempotente.

## Validación y documentación

Cada capacidad parte de pruebas que fallan y termina con pruebas focalizadas. El
cierre incluye suite completa, Ruff, validación de los tres Compose, build de las
imágenes y una corrida Docker E2E con FP16 configurado. La documentación operativa
reflejará la evidencia y dejará sólo OAK-D Pro PoE como diferido.

## Criterios de aceptación

- Un YAML con `payload_format: fp16` se ejecuta en red y conserva `float16` en el
  wire; CPU sigue siendo correcto.
- Ambos adaptadores usan la preparación tensorial común sin conversiones PIL en
  `forward()`.
- Toda corrida con `outputs.save_previews: true` produce previews desde payload,
  aunque `source_path` no exista en el consumidor.
- El productor detecta heartbeat del consumidor por PUSH/PULL y marca peer muerto
  al superar el timeout.
- `pytest -q`, `ruff check src tests`, Compose, build y E2E quedan verdes.
