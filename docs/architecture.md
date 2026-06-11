# Arquitectura del Plano de Medios

## Qué es el plano de medios

El plano de medios es el componente de E-OVRT-VDP responsable de la **percepción visual**. Su función es transformar fuentes visuales (imágenes, video) en **evidencia perceptiva normalizada**: detecciones con bounding boxes, labels y confianza.

## Qué entra y qué sale

### Entrada
- **Fuente visual**: carpeta de imágenes (DBE) o video local.
- **Configuración YAML**: modelo a usar, prompts activos, thresholds, rutas.
- **Prompts**: lista de entidades visuales a detectar (e.g., "person", "safety helmet").

### Salida
- **`detections.jsonl`**: un evento por unidad visual procesada, con todas las detecciones normalizadas.
- **`summary.json`**: resumen de la corrida (latencia, conteos, errores).
- **`metrics.jsonl`**: métricas por unidad visual.
- **`previews/`**: imágenes anotadas con bounding boxes.
- **`effective_config.yaml`**: configuración efectiva utilizada.

## Flujo del pipeline

```
RunConfig YAML
    ↓
Source (ImageFolderSource)
    ↓
VisualUnit (imagen + metadata)
    ↓
ModelAdapter.predict(image, prompts)
    ↓
RawDetection → Detection normalizado
    ↓
Sinks (JSONL, Summary, Previews)
```

## Por qué DBE primero

El escenario **Dataset-Based Evaluation (DBE)** usa archivos locales. Esto permite:
- Eliminar ruido de red, cámaras y streaming.
- Obtener resultados reproducibles.
- Comparar modelos sobre los mismos datos.
- Iterar rápido sobre prompts y thresholds.

## Por qué adaptadores de modelo

Cada modelo OVD (Grounding DINO, YOLOE, etc.) tiene su propia API. Los adaptadores:
- Implementan una interfaz común (`BaseDetectorAdapter`).
- Aíslan las dependencias de cada framework.
- Permiten intercambiar modelos desde configuración YAML.

## Qué queda fuera de este repo

- **Plano de control**: patrones de riesgo (CR-01, CR-02), alertas, persistencia de episodios, motor de estados.
- **UI / Dashboard**.
- **Streaming real / MediaMTX**.
- **Edge Node / despliegue**.
- **MOT formal / tracking multi-objeto**.
- **Fine-tuning / entrenamiento** (los checkpoints finetuneados se entrenan fuera de este repo; acá solo se catalogan como pesos en `models/<familia>/finetuned/` con su entrada en `configs/models/`).
- **Zonas o reglas espaciales**.

Estos componentes se implementarán en repositorios o módulos separados que consumirán la evidencia perceptiva normalizada generada por el plano de medios.
