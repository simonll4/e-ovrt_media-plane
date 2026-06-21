# Arquitectura del Plano de Medios

## Qué es el plano de medios

El plano de medios es el componente de E-OVRT-VDP responsable de la **percepción visual**. Su función es transformar fuentes visuales (imágenes, video) en **evidencia perceptiva normalizada**: detecciones con bounding boxes, labels y confianza.

## Estado operativo

El camino implementado es **DBE en un host**: fuente pulleable, productor en un
hilo, consumidor en el hilo principal y `TransportAdapter` con backend `memory`.
Las combinaciones EBE, IPC y red están declaradas y bloqueadas explícitamente.
Ver [implementation-status.md](implementation-status.md) para la matriz completa.

## Qué entra y qué sale

### Entrada
- **Fuente visual**: carpeta de imágenes (DBE) o video local.
- **Configuración YAML**: modelo a usar, prompts activos, thresholds, rutas.
- **Prompts**: lista de entidades visuales a detectar (e.g., "person", "safety helmet").

### Salida
- **`detections.jsonl`**: un evento por unidad visual procesada, con todas las detecciones normalizadas.
- **`summary.json`**: resumen de la corrida (latencia, conteos, errores).
- **`metrics.jsonl`**: métricas por unidad visual.
- **`previews/`**: directorio reservado para imágenes anotadas; el renderizado desde el
  nuevo payload normalizado sigue pendiente.
- **`effective_config.yaml`**: configuración efectiva utilizada.
- **`run_provenance.json`**: identidad del dataset y fingerprint de la fuente.
- **`run_manifest.json`**: versión de código y lista de artefactos generados.

## Flujo del pipeline

```
RunConfig YAML
    ↓
BaseSource (ImageFolderSource | VideoFileSource)
    ↓
VisualUnit
    ↓
Productor: RateGate → normalize_spatial → NormalizedUnit → TransportAdapter.offer()
                                                   │
                              memory: deterministic | bounded_freshness
                                                   │
Consumidor: TransportAdapter.request() → ModelAdapter.forward() → RawDetection
    ↓
DetectionNormalizer (reproyección con ResizeTransform) → Detection
    ↓
Sinks: detections.jsonl, metrics.jsonl, summary.json, provenance y errores
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
- Declaran `ModelInputSpec` y reciben `NormalizedUnit` mediante `forward()`.
- Aíslan las dependencias de cada framework.
- Permiten intercambiar modelos desde configuración YAML.

## Qué queda fuera de este repo

- **Plano de control**: patrones de riesgo (CR-01, CR-02), alertas, persistencia de episodios, motor de estados.
- **UI / Dashboard**.
- **Fuente viva / streaming real / MediaMTX** (la interfaz `LiveSource` está declarada).
- **Edge Node, IPC y despliegue distribuido** (interfaces declaradas, sin backend).
- **MOT formal / tracking multi-objeto**.
- **Fine-tuning / entrenamiento** (los checkpoints finetuneados se entrenan fuera de este repo; acá solo se catalogan como pesos en `models/<familia>/finetuned/` con su entrada en `configs/models/`).
- **Zonas o reglas espaciales**.

Estos componentes se implementarán en repositorios o módulos separados que consumirán la evidencia perceptiva normalizada generada por el plano de medios.
