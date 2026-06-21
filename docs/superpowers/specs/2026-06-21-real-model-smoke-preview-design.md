# Diseño — smoke test con modelos reales y previews

**Objetivo:** validar el pipeline completo con un dataset real y una imagen anotada por
modelo, ejecutando Grounding DINO tiny y YOLOE-26s en CPU.

## Alcance

- Fuente única: `construction_site_safety/valid/images` del repositorio hermano
  `e-ovrt_datasets`.
- Dos corridas independientes, una por modelo, con `run.max_units: 1`.
- Pesos locales ya disponibles; no se descargan modelos ni datos.
- Reparar la salida de previews para que una detección producida por el pipeline se
  renderice sobre la imagen original.

## Diseño

El pipeline conservará en `NormalizedUnit` la ruta de origen necesaria solo para la
visualización o la recibirá de forma explícita en la etapa de escritura. Cuando haya
detecciones y `outputs.save_previews` esté habilitado, el consumidor invocará
`draw_detections()` con las cajas ya reproyectadas al espacio original y escribirá
`previews/<unit_id>.preview.jpg`.

Se añadirá una prueba de integración que verifica la creación de una preview no vacía.
Las pruebas existentes seguirán validando la ruta sin previews. No se altera el contrato
de detección ni la política de transporte.

Para cada modelo se generará un YAML temporal, fuera del repositorio: referencia al
dataset `bench_v2_val`, modelo correspondiente, prompts existentes, CPU, una unidad y
previews activadas. La validación de cada run comprobará `summary.json`,
`detections.jsonl`, `metrics.jsonl`, `run_provenance.json` y el archivo anotado si hay
detecciones. Si un modelo no produce detecciones en la única imagen, la corrida se
considera técnicamente válida, pero se informará que no fue posible verificar el dibujo
de cajas con ese modelo.

## Riesgos y límites

- No hay GPU disponible; GDINO-tiny puede tardar considerablemente incluso para una
  imagen, por lo que la corrida queda limitada a una unidad.
- El smoke test confirma integración y artefactos; no mide precisión ni compara modelos.
- La fuente de dataset se lee sin modificar `e-ovrt_datasets`.

## Criterios de aceptación

1. La prueba de previews falla antes de conectar el renderizado y pasa después.
2. La suite completa permanece verde.
3. Ambos YAML temporales validan y ejecutan con pesos locales.
4. Cada run deja artefactos versionados; las previews se inspeccionan visualmente cuando
   existen detecciones.
