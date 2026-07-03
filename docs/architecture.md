# Arquitectura del Plano de Medios

## Qué es el plano de medios

El plano de medios es el componente de E-OVRT-VDP responsable de la **percepción visual**. Su función es transformar fuentes visuales (imágenes, video) en **evidencia perceptiva normalizada**: detecciones con bounding boxes, labels y confianza.

## Estado operativo

Desde la **Fase 1 (Spec A)** el plano de medios se expone como un **servicio de inferencia
HTTP/WS** (FastAPI): carga el modelo una vez al startup (`EOVRT_MODEL_REF`), mantiene un único
run activo y dispara el pipeline con `POST /api/runs`. El CLI `eovrt-media` fue eliminado (los
utilitarios viven en `eovrt_media.tools.*`). El servicio **envuelve** el pipeline
productor/consumidor descrito abajo, que no cambió.

Las cuatro combinaciones escenario × topología están implementadas y validadas:
DBE/EBE en un host (`memory`) y en dos nodos (`network`/ZeroMQ, hoy invocado en proceso;
el empaquetado Docker de dos nodos se difiere a Fase 2). Dentro del alcance funcional actual
del plano de medios, `fp16` forma parte del contrato de payload y la única capacidad declarada
para implementación futura es `OAK-D`.
Ver [implementation-status.md](implementation-status.md) para la matriz completa.

El servicio tiene un cliente externo real: la **webconsole**
(`../e-ovrt_experimental-setup/webconsole/`) consume esta API HTTP/WS (`POST /api/runs`,
WS `/api/runs/{id}/stream`) para disparar y observar corridas. El contrato completo
(endpoints REST + eventos WS) vive en [usage.md](usage.md) y en el diseño
[2026-07-01-media-plane-service-design.md](superpowers/specs/2026-07-01-media-plane-service-design.md).

## Qué entra y qué sale

### Entrada
- **Fuente visual**: carpeta de imágenes, video local (DBE) o stream RTSP (EBE), declarada
  en el request como `ingest: {plugin, config}`.
- **Run request** (`POST /api/runs`): fuente de ingesta, prompts y parámetros de corrida
  (`run.stride`, `run.max_units`, outputs). El **modelo es fijo por instancia** (cargado al
  startup), no viaja en el request.
- **Prompts**: lista de entidades visuales a detectar (e.g., "person", "helmet"), embebidas
  (`prompts.set_inline`) o por referencia al catálogo del repo de experimentos.

### Salida
- **`detections.jsonl`**: un evento por unidad visual procesada, con todas las detecciones normalizadas.
- **`summary.json`**: resumen de la corrida (latencia, conteos, errores).
- **`metrics.jsonl`**: métricas por unidad visual.
- **`previews/`**: imágenes anotadas renderizadas desde el payload normalizado; cubren imágenes,
  vídeo, RTSP y la ejecución en Nodo B sin acceso al archivo fuente.
- **`effective_config.yaml`**: configuración efectiva utilizada.
- **`run_provenance.json`**: identidad del dataset y fingerprint de la fuente.
- **`run_manifest.json`**: versión de código y lista de artefactos generados.

## Flujo del pipeline

```
RunConfig YAML
    ↓
BaseSource (ImageFolderSource | VideoFileSource | RtspSource | OakDSource†)
    ↓
VisualUnit (+ pixel_data para fuentes vivas)
    ↓
Productor: RateGate → normalize_spatial → NormalizedUnit → TransportAdapter.offer()
                                                   │
                  memory (un host) | network/ZeroMQ (dos nodos: REQ/REP datos + PUSH/PULL heartbeat)
                                                   │
Consumidor: TransportAdapter.request() → ModelAdapter.forward() → RawDetection
    ↓
DetectionNormalizer (reproyección con ResizeTransform) → Detection
    ↓
Sinks: detections.jsonl, metrics.jsonl, summary.json, provenance y errores

† OakDSource declarado, pendiente SDK DepthAI.
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
- **OAK-D Pro PoE** (`OakDSource` declarado; requiere SDK DepthAI, pendiente).
- **MOT formal / tracking multi-objeto**.
- **Fine-tuning / entrenamiento** (los checkpoints finetuneados se entrenan fuera de este repo; acá solo se catalogan como pesos en `models/<familia>/finetuned/` con su entrada en `configs/models/`).
- **Zonas o reglas espaciales**.

Estos componentes se implementarán en repositorios o módulos separados que consumirán la evidencia perceptiva normalizada generada por el plano de medios.
