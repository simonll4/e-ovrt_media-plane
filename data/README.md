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
