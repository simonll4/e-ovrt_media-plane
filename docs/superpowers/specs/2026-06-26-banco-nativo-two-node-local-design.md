# Diseño: banco nativo preliminar para pruebas two-node locales

## Objetivo

Construir una primera versión operativa para ejecutar el plano de medios en
topología de dos nodos dentro de una sola PC, usando procesos nativos en la
misma venv. El objetivo inmediato es acelerar pruebas end-to-end, cambiar de
fuente sin editar YAML duplicado, capturar logs separados y producir un resumen
útil para encontrar brechas, warnings, errores y puntos de optimización.

Este incremento no crea un plano de medios paralelo. Debe reutilizar el contrato
existente: `run-producer`, `run-consumer`, `run_node_a`, `run_node_b`,
`NetworkTransportAdapter`, `RtspSource`, `VideoFileSource`, `ImageFolderSource`,
los schemas actuales y los artefactos de corrida.

## Alcance

La primera versión agrega un comando de banco local, tentativamente
`eovrt-media run-two-node-local`, que genera configuraciones locales auditables y
orquesta dos procesos nativos:

- Nodo A: ingesta, rate control, normalización y servidor ZeroMQ.
- Nodo B: cliente ZeroMQ, inferencia, postproceso y escritura de artefactos.

El comando debe soportar al menos estas fuentes:

- `bench-val`: `configs/datasets/bench_v2_val.yaml`.
- `bench-test`: `configs/datasets/bench_v2_test.yaml`.
- `demo`: `configs/datasets/demo_v2.yaml`.
- `video`: archivo local pasado con `--video`.
- `ezviz`: RTSP pasado con `--rtsp-url` o variable de entorno.

El cambio de fuente en esta etapa ocurre al arrancar la corrida. El hot-swap de
fuente con el módulo ya corriendo queda fuera de alcance hasta que el plano
tenga operación estable y métricas suficientes.

## Fuera De Alcance

- Reescribir el transporte o el runtime two-node.
- Crear un supervisor productivo permanente.
- Hot-swap dinámico de fuentes en caliente.
- Docker Compose como camino principal de prueba.
- Plano de control, UI, alertas o reglas de riesgo.

Docker queda como validación secundaria de empaquetado. El banco preliminar es
nativo para facilitar iteración, depuración y profiling.

## Flujo De Operación

Ejemplos esperados:

```bash
eovrt-media run-two-node-local --source bench-val --codec jpeg --max-units 200
eovrt-media run-two-node-local --source bench-val --codec raw --max-units 200
eovrt-media run-two-node-local --source video --video data/samples/videos/sample.mp4 --codec jpeg
eovrt-media run-two-node-local --source ezviz --rtsp-url "$EZVIZ_RTSP_URL" --skip-probe
```

El comando:

1. Resuelve el perfil de fuente.
2. Selecciona endpoints loopback libres para datos y heartbeat.
3. Genera YAMLs locales en `configs/runs/local/generated/`.
4. Valida ambos YAMLs con el loader existente.
5. Para RTSP, corre una sonda corta salvo `--skip-probe`.
6. Lanza Nodo A y espera que el puerto de datos esté disponible.
7. Lanza Nodo B y espera finalización.
8. Si un nodo falla, termina el otro proceso y reporta logs.
9. Lee los artefactos de Nodo B y muestra un resumen de prueba.

## Configuración Generada

Los YAML generados deben ser explícitos y locales, no versionados. Deben incluir:

- `source` resuelto desde catálogo o inline para video/RTSP.
- `model.ref: yoloe/yoloe-26s` por defecto.
- `model.device: cuda:0` por defecto, con override `--device`.
- `prompts.ref` compatible con la fuente seleccionada.
- `topology.mode: two_node`.
- `transport.backend: network`.
- `transport.endpoint` y `transport.heartbeat_endpoint` en `127.0.0.1`.
- `transport.payload_format` configurable, default `uint8_rgb`.
- `transport.compression.codec` configurable, default `jpeg`.
- `run.max_units` si se pasa por flag.
- `outputs.save_previews` configurable.

Nodo A y Nodo B pueden usar el mismo YAML cuando los endpoints son loopback y la
fuente es local. Si una diferencia futura es necesaria, el generador podrá
escribir `node_a.yaml` y `node_b.yaml`, pero la primera versión debe elegir la
forma más simple que preserve el contrato actual.

## Reporte De Brechas

Al finalizar, el banco debe imprimir:

- Ruta del directorio de corrida.
- Fuente, codec, payload, modelo, device y límites de unidades.
- Unidades procesadas, fallidas y descartadas.
- Detecciones totales y por label.
- Latencia promedio, p95, p99 y FPS efectivo.
- Pico de VRAM si existe.
- Conteo de errores en `errors.jsonl`.
- Warnings detectados en logs de Nodo A y Nodo B.

Los logs separados deben guardarse bajo un directorio local de la sesión, por
ejemplo `runs/local-two-node/20260626-143000/node-a.log` y `node-b.log`.

## Manejo De Errores

- Config inválida: falla antes de lanzar procesos.
- Puerto ocupado o no disponible: selecciona otro puerto si lo eligió
  automáticamente; falla claro si el usuario fijó el puerto.
- Nodo A no abre el endpoint: aborta y muestra el log de Nodo A.
- Nodo B falla: termina Nodo A, conserva logs y reporta el código de salida.
- RTSP sin URL: falla antes de lanzar nodos.
- RTSP con credenciales: nunca imprime la URI completa; usa la redacción ya
  existente en `scripts/probe_rtsp.py`.
- `Ctrl+C`: termina ambos procesos y conserva artefactos parciales.

## Validación

La implementación debe incluir:

- Tests unitarios de resolución de fuentes y generación de config.
- Test de integración con `mock`, imágenes temporales y endpoints loopback.
- Test de fallo para fuente `video` sin `--video`.
- Test de fallo para `ezviz` sin URL.
- Verificación manual con `bench-val` JPEG y RAW.
- Verificación manual con RTSP EZVIZ cuando la cámara esté disponible.

Antes de cerrar el incremento se deben correr:

```bash
pytest -q
ruff check src tests
```

Si se toca documentación o scripts fuera de `src`/`tests`, se debe ampliar la
verificación de ruff a esos archivos.

## Dirección Productiva

Esta primera etapa prepara el camino hacia un módulo productivo que pueda quedar
corriendo y recibir frames de distintas fuentes, pero no intenta resolverlo aún.
Las pruebas del banco local deben alimentar una lista concreta de mejoras:
reconexión, health checks, métricas operacionales, límites de cola, cierre
limpio, manejo de fuentes vivas y criterios para degradar o reiniciar procesos.

Cuando esta versión preliminar revele las brechas reales, el siguiente diseño
debe cubrir el runner productivo persistente con supervisión, health, métricas y
contrato de operación.
