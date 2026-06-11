# Mini-dataset DBE — videos

Colocar aquí los videos locales de prueba.

La config de video por defecto (`configs/runs/yoloe_video.yaml`) espera `sample.mp4` en este directorio; para otro nombre, ajustar la entrada del catálogo `configs/datasets/video_sample.yaml`.

Recomendaciones:

- Para un smoke test, usar un montaje corto (45-60 s) con los cuatro casos:
  casco+chaleco, sin casco, sin chaleco y sin ambos.
- Para evaluacion, mantener clips separados y cubrir la matriz definida en
  `docs/relevamiento/2026-06-11-datasets-video-construccion.md`.
- El muestreo se controla en `sampling.every_n` / `sampling.target_fps` / `sampling.max_units`.
- Congelar y documentar origen, licencia, fecha de descarga y SHA-256.
- Los videos de terceros no se versionan en git. Guardarlos bajo
  `data/raw/video_benchmark_v1/` y versionar solo el manifiesto.
- No marcar casco o chaleco como ausente cuando el elemento no es observable;
  usar `unknown`.

## Origen de los videos

El manifiesto debe incluir, como minimo:

| Campo | Descripcion |
|---|---|
| `clip_id` | Identificador estable, por ejemplo `V01_001` |
| `local_filename` | Nombre local del archivo |
| `source_url` | Pagina original del clip |
| `creator` | Autor publicado por la fuente |
| `license` | Licencia aplicable al descargar |
| `downloaded_at` | Fecha de descarga |
| `sha256` | Hash del archivo original |
| `scenario` | `V01` a `V08` segun el relevamiento |
| `helmet_state` | `present`, `absent`, `mixed` o `unknown` |
| `vest_state` | `present`, `absent`, `mixed` o `unknown` |
| `notes` | Visibilidad, maquinaria, oclusiones y otras dificultades |
