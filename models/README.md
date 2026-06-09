# Models

Este directorio contiene pesos de modelos descargados localmente.

## Estructura

```
models/
├── grounding-dino/
│   └── grounding-dino-tiny/    # IDEA-Research/grounding-dino-tiny
└── yoloe/
    └── yoloe-26s-seg.pt        # YOLOE small segmentation
```

## Descarga

```bash
make download-models
# o directamente:
./scripts/download_models.sh
```

## Notas

- Los pesos **no se versionan** en Git (ver `.gitignore`).
- Cada desarrollador debe descargar los modelos localmente.
- Los modelos se referencian desde los archivos de configuración YAML.
