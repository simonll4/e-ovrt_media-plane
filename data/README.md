# Data

Este directorio contiene datos de entrada para el plano de medios.

## Estructura

```
data/
├── samples/          # Muestras pequeñas para pruebas manuales
│   ├── images/       # Imágenes de prueba (.jpg, .jpeg, .png)
│   └── videos/       # Videos de prueba (futuro)
├── raw/              # Datasets crudos (no versionados)
└── datasets/         # Datasets procesados (no versionados)
```

## Notas

- Solo `samples/` se versiona en Git.
- `raw/` y `datasets/` están en `.gitignore` — usar para datasets pesados locales.
- Las muestras ideales incluyen: personas con/sin casco, con/sin chaleco, escenas de obra, imágenes sin personas.

## Datasets centralizados (repo hermano)

Los datasets de obra (MOCS, CHV, …) viven de forma centralizada en el repo hermano
`e-ovrt_datasets` (en `../e-ovrt_datasets/datasets/raw/`). El media-plane los consume
cross-repo: los catálogos en `configs/datasets/` (p. ej. `chv.yaml`, `mocs.yaml`) usan
un `path` relativo `../e-ovrt_datasets/...`, por lo que **`eovrt-media` debe ejecutarse
desde la raíz del media-plane** para que el path resuelva. `data/raw/` queda para datos
locales puntuales, no como home de los datasets compartidos.
