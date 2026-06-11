# Memoria de desarrollo — Plano de Medios E-OVRT-VDP

> Documento de contexto para agentes de código trabajando en VS Code/Codex.
> Este archivo describe el **contexto, alcance, estrategia y contratos esperados** del repositorio del **plano de medios** de E-OVRT-VDP.
> No debe interpretarse como una especificación cerrada ni como una lista obligatoria de tecnologías. Su función es orientar el desarrollo sin acoplarlo prematuramente.

---

## 1. Contexto del proyecto

E-OVRT-VDP es un proyecto académico/experimental titulado:

**“Plataforma experimental de detección open-vocabulary en video en tiempo real para monitoreo asistivo de riesgos en construcción”.**

El objetivo general del sistema completo es explorar la viabilidad técnica de una plataforma que procese fuentes visuales, ejecute detección open-vocabulary, produzca evidencia perceptiva trazable, evalúe patrones de riesgo y genere alertas asistivas.

El sistema completo:

* no es un producto industrial terminado;
* no es una herramienta de fiscalización automática;
* no reemplaza al supervisor humano;
* no realiza reconocimiento de identidad personal;
* no toma decisiones normativas, legales ni disciplinarias;
* trabaja con evidencia visual observable y trazable.

El estado actual del proyecto parte del diseño arquitectónico ya definido en la Etapa 3. La implementación debe avanzar de manera incremental, comenzando por un núcleo validable, medible y reproducible.

---

## 2. Rol de este repositorio

Este repositorio corresponde únicamente al **plano de medios**.

El plano de medios es la parte del sistema encargada de transformar una fuente visual en evidencia perceptiva normalizada.

En términos conceptuales:

```text
fuente visual
  -> unidad visual
  -> lectura / normalización
  -> inferencia OVD
  -> postproceso
  -> eventos perceptivos + métricas
```

El producto principal de este repositorio no es una alerta, sino evidencia primaria para que otros módulos puedan consumirla después.

El plano de medios responde preguntas como:

```text
¿Qué se detectó?
¿En qué imagen o frame?
¿Con qué modelo?
¿Con qué prompts?
¿Con qué umbrales?
¿Con qué latencia?
¿Con qué configuración de corrida?
```

No responde preguntas como:

```text
¿Hay una situación de riesgo confirmada?
¿Se debe disparar una alerta?
¿La persona estuvo sin casco durante N segundos?
¿Hay incumplimiento normativo?
```

Ese segundo grupo pertenece al plano de control.

---

## 3. Frontera arquitectónica

### Incluido en este repositorio

El plano de medios debe cubrir, de forma incremental:

* carga de configuración de corrida;
* lectura de fuentes locales para DBE;
* lectura de imágenes desde carpeta;
* lectura de video local en una etapa posterior;
* representación normalizada de unidades visuales;
* carga de prompts versionados;
* ejecución de modelos OVD mediante adaptadores;
* postproceso mínimo de detecciones;
* normalización de bounding boxes;
* medición de latencias por tramo;
* registro de métricas técnicas;
* escritura de artefactos por corrida;
* persistencia simple en archivos locales;
* CLI mínima para ejecutar corridas reproducibles.

### Fuera de alcance inicial

No implementar en este repositorio, salvo pedido explícito:

* plano de control;
* patrones de riesgo;
* severidad;
* persistencia temporal de condiciones;
* confirmación de alertas;
* notificaciones;
* UI;
* dashboards;
* base de datos;
* streaming RTSP/WebRTC/SRT;
* MediaMTX;
* Edge Node;
* Training Node;
* MOT formal;
* zonas espaciales;
* reglas relacionales complejas;
* fine-tuning;
* TensorRT/ONNX como dependencia base;
* arquitectura distribuida;
* colas externas;
* microservicios.

El criterio general es mantener el plano de medios local, simple y medible antes de extenderlo.

---

## 4. Estrategia de implementación

La estrategia acordada es avanzar primero sobre un escenario **DBE — Dataset-Based Evaluation**.

DBE significa trabajar con imágenes o videos locales, reproducibles y controlados. Esto permite estabilizar el pipeline antes de incorporar cámaras, streaming o entornos reales.

El primer núcleo defendible debe permitir:

```text
Dado un RunConfig,
leer una fuente visual local,
ejecutar un modelo OVD configurado,
normalizar detecciones,
medir latencias,
guardar eventos y métricas en una carpeta de corrida.
```

El foco inicial no es maximizar precisión ni optimizar rendimiento extremo, sino construir un flujo claro, verificable y comparable.

---

## 5. Condiciones núcleo del TFG

El sistema completo estudia varias condiciones de riesgo. Para el primer núcleo del plano de medios se consideran solo dos:

### CR-01 — Persona sin casco

Concepto de riesgo del sistema completo:

```text
Persona sin casco de seguridad en zona de obra.
```

En el plano de medios esto no debe implementarse como una conclusión de “sin casco”.

El plano de medios solo debe detectar entidades observables, por ejemplo:

```text
person
helmet
safety helmet
```

La interpretación de ausencia, asociación persona-casco, persistencia temporal o alerta corresponde al plano de control.

### CR-02 — Persona sin chaleco reflectivo

Concepto de riesgo del sistema completo:

```text
Persona sin chaleco reflectivo en zona de tráfico o maquinaria.
```

En el plano de medios esto se traduce en entidades observables como:

```text
person
safety vest
reflective vest
high visibility vest
```

También pueden existir entidades auxiliares futuras, como vehículos o maquinaria, pero no forman parte obligatoria del primer núcleo.

---

## 6. Principios de diseño

### 6.1 Configuración antes que hardcode

Todo parámetro relevante debe venir desde archivos de configuración:

* modelo;
* dispositivo;
* fuente visual;
* prompts;
* umbrales;
* política de muestreo;
* outputs;
* flags de depuración.

Evitar rutas absolutas, prompts hardcodeados y constantes ocultas dentro del código.

### 6.2 Modelos reemplazables

El pipeline no debe depender directamente de una librería o modelo específico.

Los modelos deben integrarse mediante adaptadores.

La lógica específica de cada modelo debe quedar encapsulada dentro de su adaptador.

El resto del pipeline debe trabajar con contratos internos comunes.

### 6.3 Evidencia antes que alerta

El plano de medios produce evidencia perceptiva.

No debe producir alertas ni estados de riesgo.

### 6.4 Trazabilidad de corrida

Cada ejecución debe dejar suficientes artefactos para entender:

* qué se ejecutó;
* sobre qué datos;
* con qué configuración;
* con qué modelo;
* con qué prompts;
* con qué resultados;
* con qué tiempos;
* con qué errores.

### 6.5 Simplicidad incremental

No incorporar infraestructura distribuida ni optimizaciones avanzadas antes de tener un pipeline local estable.

Primero debe funcionar el flujo mínimo. Después se comparan modelos, fuentes y variantes.

---

## 7. Adaptadores de modelos

El repositorio debe contemplar una arquitectura donde los modelos OVD sean intercambiables.

Los adaptadores iniciales previstos son:

```text
mock
grounding_dino
yoloe
```

Estos nombres representan familias de integración, no una obligación rígida sobre una versión exacta de pesos o librería.

### MockDetector

Debe existir un detector mock para validar el pipeline sin depender de GPU, descargas ni librerías pesadas.

Su objetivo es probar:

* configuración;
* lectura de fuentes;
* generación de VisualUnit;
* escritura de JSONL;
* métricas;
* estructura de outputs;
* tests automatizados;
* ejecución end-to-end.

El mock no busca simular precisión real. Solo debe devolver detecciones estructuralmente válidas.

### Grounding DINO

Grounding DINO se contempla como una alternativa OVD de mayor expresividad semántica.

El adaptador debe encapsular:

* carga del modelo;
* carga del processor/tokenizer si aplica;
* preparación del prompt;
* inferencia;
* postproceso específico;
* conversión a `RawDetection`.

El pipeline general no debe importar objetos internos de Transformers, Hugging Face u otra implementación concreta.

### YOLOE

YOLOE se contempla como alternativa OVD orientada a velocidad.

El adaptador debe encapsular:

* carga del modelo;
* configuración de clases/prompts;
* inferencia;
* extracción de boxes;
* conversión a `RawDetection`.

Aunque el modelo pueda soportar segmentación, el primer núcleo puede trabajar únicamente con bounding boxes.

---

## 8. Prompts

Los prompts deben tratarse como artefactos versionados.

No hardcodear prompts en código.

Un conjunto de prompts debe tener al menos:

```text
id
descripción
idioma
lista de items
```

Cada item debería poder representar:

```text
prompt_id
texto
rol conceptual
estado habilitado/deshabilitado
```

Ejemplo conceptual:

```yaml
prompt_set:
  id: cr01_cr02_v1
  description: "Prompts iniciales para entidades perceptivas asociadas a CR-01 y CR-02"
  language: en
  items:
    - id: person
      text: "person"
      role: entity
      enabled: true

    - id: helmet
      text: "safety helmet"
      role: ppe
      enabled: true

    - id: vest
      text: "high visibility safety vest"
      role: ppe
      enabled: true

    - id: reflective_vest
      text: "reflective vest"
      role: ppe
      enabled: true
```

La forma exacta en que se pasan los prompts al modelo puede variar por adaptador.

El contrato importante es que el evento final preserve qué prompt set y qué prompts participaron en la corrida.

---

## 9. Contratos internos

Los contratos son más importantes que cualquier implementación concreta.

El objetivo es que las piezas del pipeline puedan evolucionar sin romper el formato de evidencia.

### 9.1 RunConfig

Representa la configuración declarativa de una corrida.

Debe incluir, como mínimo:

```text
run
source
sampling
model
prompts
postprocess
outputs
logging
```

Ejemplo conceptual:

```yaml
run:
  id: null
  scenario: DBE
  description: "Corrida DBE inicial para CR-01/CR-02"
  seed: 42

source:
  type: image_folder
  path: data/samples/images

sampling:
  mode: all
  max_units: null

model:
  name: mock
  model_id: mock-v1
  device: cpu

prompts:
  file: configs/prompts/cr01_cr02_v1.yaml

postprocess:
  min_confidence: 0.25
  min_box_area_px: 100
  normalize_boxes: true

outputs:
  run_dir: runs
  save_previews: false

logging:
  level: INFO
```

### 9.2 VisualUnit

Representa una unidad visual procesable.

Puede ser una imagen o un frame extraído de video.

Campos esperados:

```text
run_id
unit_id
source_id
source_type
frame_index
timestamp_ms
width
height
path o referencia de origen
```

### 9.3 RawDetection

Salida intermedia de un adaptador de modelo.

Debe tener un formato común para que el postproceso no dependa del modelo.

Campos esperados:

```text
label
score
bbox_xyxy
source_prompt
prompt_id
raw opcional
```

El campo `raw` no debe persistirse por defecto si contiene objetos grandes o no serializables.

### 9.4 DetectionEvent

Evento persistible producido por el plano de medios.

Debe contener:

```text
schema_version
event_type
run_id
unit_id
source
model
prompts
detections
timing
```

Cada detección normalizada debe incluir:

```text
detection_id
label
prompt_id
confidence
bbox_xyxy
bbox_norm_xyxy
area_px
```

### 9.5 MetricSample

Muestra métrica asociada a una unidad visual o tramo de ejecución.

Debe contener, como mínimo:

```text
schema_version
event_type
run_id
unit_id
fps_effective
latency_total_ms
latency_inference_ms
detections_count
dropped_units
device
gpu_memory_allocated_mb opcional
```

### 9.6 ErrorEvent

Evento para errores recuperables o advertencias importantes.

Debe contener:

```text
schema_version
event_type
run_id
unit_id opcional
stage
severity
message
recoverable
```

---

## 10. Artefactos de salida por corrida

Cada corrida debe generar una carpeta propia dentro de `runs/`.

Ejemplo:

```text
runs/
└── run_YYYYMMDD_HHMMSS_model/
    ├── run_config.yaml
    ├── effective_config.yaml
    ├── run_manifest.json
    ├── detections.jsonl
    ├── metrics.jsonl
    ├── errors.jsonl
    ├── summary.json
    └── previews/
```

### run_config.yaml

Copia de la configuración original recibida por la corrida.

### effective_config.yaml

Configuración realmente usada luego de resolver defaults.

Este archivo es importante para reproducibilidad.

### run_manifest.json

Metadatos generales de la corrida.

Puede incluir:

```text
run_id
fecha de inicio
versión del código si está disponible
directorio de salida
archivos generados
```

### detections.jsonl

Una línea JSON por unidad visual procesada.

Cada línea debe ser parseable de forma independiente.

### metrics.jsonl

Muestras técnicas del pipeline.

### errors.jsonl

Errores recuperables, warnings o unidades fallidas.

### summary.json

Resumen final de la corrida.

Debe permitir inspeccionar rápidamente:

```text
modelo usado
fuente procesada
cantidad de unidades procesadas
cantidad de errores
cantidad total de detecciones
FPS efectivo
latencia promedio
latencia p95
prompts usados
configuración efectiva
```

---

## 11. Flujo de ejecución esperado

El pipeline debe ser lineal y fácil de leer.

Pseudoflujo:

```text
1. Cargar RunConfig
2. Crear RunContext
3. Crear directorio de corrida
4. Guardar configuración original y efectiva
5. Cargar PromptSet
6. Crear Source
7. Crear ModelAdapter
8. Cargar modelo
9. Iterar VisualUnits
10. Leer imagen/frame
11. Ejecutar inferencia
12. Convertir salida del modelo a RawDetection
13. Normalizar detecciones
14. Construir DetectionEvent
15. Construir MetricSample
16. Escribir JSONL
17. Registrar errores recuperables
18. Generar summary.json
19. Liberar recursos
```

Reglas importantes:

* no mezclar lógica de riesgo con inferencia;
* no generar alertas;
* no bloquear la corrida por una preview;
* si una unidad visual falla y el error es recuperable, registrar y continuar;
* no acoplar el pipeline a una librería concreta de modelo;
* no hacer postproceso semántico complejo en esta etapa.

---

## 12. Estructura sugerida del repositorio

La estructura puede evolucionar, pero conviene partir de algo simple:

```text
eovrt-media-plane/
│
├── README.md
├── pyproject.toml
├── .gitignore
├── .env.example
├── Makefile
│
├── configs/
│   ├── dbe_cr01_cr02_mock.yaml
│   ├── dbe_cr01_cr02_grounding_dino.yaml
│   ├── dbe_cr01_cr02_yoloe.yaml
│   └── prompts/
│       └── cr01_cr02_v1.yaml
│
├── data/
│   ├── samples/
│   │   └── README.md
│   └── README.md
│
├── runs/
│   └── .gitkeep
│
├── models/
│   └── README.md
│
├── docs/
│   ├── MEMORY_MEDIA_PLANE.md
│   ├── architecture.md
│   ├── contracts.md
│   └── metrics.md
│
├── scripts/
│   └── README.md
│
├── src/
│   └── eovrt_media/
│       ├── __init__.py
│       ├── cli.py
│       ├── app.py
│       │
│       ├── config/
│       ├── contracts/
│       ├── sources/
│       ├── preprocessing/
│       ├── models/
│       ├── postprocessing/
│       ├── sinks/
│       ├── metrics/
│       └── runtime/
│
└── tests/
```

No agregar carpetas o servicios antes de necesitarlos.

---

## 13. CLI esperada

El repositorio debe exponer una CLI mínima.

Comandos prioritarios:

```bash
eovrt-media run --config configs/dbe_cr01_cr02_mock.yaml
eovrt-media validate-config configs/dbe_cr01_cr02_mock.yaml
```

Comandos posteriores:

```bash
eovrt-media inspect-run runs/<run_id>
eovrt-media download-models --model <name>
```

Prioridad de implementación:

```text
1. run
2. validate-config
3. inspect-run
4. download-models
```

---

## 14. Métricas mínimas

Desde el primer núcleo deben medirse métricas técnicas simples.

Métricas por unidad visual:

```text
latencia de lectura
latencia de preprocesamiento
latencia de inferencia
latencia de postproceso
latencia de escritura
latencia total
cantidad de detecciones
```

Métricas agregadas por corrida:

```text
unidades procesadas
unidades fallidas
detecciones totales
FPS efectivo
latencia promedio
latencia p95
errores por etapa
VRAM usada si está disponible
```

No calcular todavía:

```text
AP
mAP
precision
recall
F1
HOTA
MOTA
IDF1
latencia de alerta
TTFD
SDR
```

Esas métricas requieren ground truth, tracking, plano de control o eventos anotados.

---

## 15. Testing

La primera capa de tests no debe depender de modelos reales.

Tests mínimos esperados:

```text
config loader
prompt loader
image folder source
visual unit
detection normalizer
jsonl sink
run artifact writer
mock pipeline end-to-end
```

Criterios de aceptación del pipeline mock:

```text
- carga una config válida;
- lee imágenes de una carpeta;
- genera VisualUnits;
- produce detecciones mock;
- normaliza bounding boxes;
- escribe detections.jsonl;
- escribe metrics.jsonl;
- escribe summary.json;
- registra errores si corresponde;
- termina sin depender de CUDA.
```

Los tests con modelos reales deben quedar separados como integración o GPU.

---

## 16. Roadmap incremental

### Hito 1 — Bootstrap

Objetivo:

```text
Crear la estructura mínima del repositorio y validar que la CLI existe.
```

Aceptación:

```bash
pip install -e .
eovrt-media --help
pytest
```

### Hito 2 — Pipeline mock

Objetivo:

```text
Tener una corrida DBE local funcionando de punta a punta sin modelos reales.
```

Aceptación:

```bash
eovrt-media run --config configs/dbe_cr01_cr02_mock.yaml
```

Debe generar una carpeta en `runs/` con:

```text
effective_config.yaml
detections.jsonl
metrics.jsonl
summary.json
```

### Hito 3 — Primer modelo OVD real

Objetivo:

```text
Integrar un adaptador real manteniendo intacto el contrato del pipeline.
```

El modelo concreto puede ser Grounding DINO, YOLOE u otro candidato compatible con la estrategia definida.

Aceptación:

```text
La corrida produce DetectionEvent y MetricSample con el mismo contrato que el mock.
```

### Hito 4 — Segundo modelo OVD real

Objetivo:

```text
Agregar un segundo adaptador para comparar comportamiento, latencia y calidad perceptiva.
```

Aceptación:

```text
Dos modelos distintos pueden ejecutarse sobre la misma fuente y generar artefactos comparables.
```

### Hito 5 — Video local

Objetivo:

```text
Procesar archivos de video locales como secuencia de VisualUnits.
```

Aceptación:

```text
El pipeline registra frame_index, timestamp_ms y métricas por frame procesado.
```

### Hito 6 — Inspección de corridas

Objetivo:

```text
Poder resumir rápidamente los resultados de una corrida.
```

Aceptación:

```bash
eovrt-media inspect-run runs/<run_id>
```

Debe mostrar:

```text
modelo
fuente
unidades procesadas
detecciones
FPS efectivo
latencia promedio
latencia p95
errores
```

---

## 17. Decisiones que deben preservarse

### DBE primero

La primera versión debe estabilizar fuentes locales antes de incorporar streaming.

### Separación de planos

El plano de medios no implementa patrones, alertas ni lógica de riesgo.

### Adaptadores de modelo

Cada modelo debe quedar encapsulado detrás de una interfaz común.

### Configuración como artefacto central

Toda corrida debe poder reproducirse a partir de su configuración efectiva.

### JSONL como salida inicial

Para el MVP, JSONL es suficiente y simple para registrar eventos y métricas.

### No sobre-ingeniería

Evitar introducir infraestructura antes de que el núcleo local esté funcionando.

---

## 18. Acuerdos de trabajo para agentes de código

Los agentes que trabajen en este repositorio deben seguir estos criterios:

1. Mantener el código simple y legible.
2. Priorizar contratos estables sobre optimizaciones.
3. No introducir servicios externos sin pedido explícito.
4. No implementar plano de control.
5. No implementar alertas.
6. No implementar patrones de riesgo.
7. No hardcodear prompts.
8. No hardcodear rutas absolutas.
9. No mezclar lógica específica de modelo con lógica general del pipeline.
10. No guardar outputs fuera de `runs/`.
11. No versionar pesos de modelos.
12. No versionar datasets pesados.
13. Registrar errores recuperables en vez de abortar toda la corrida cuando sea razonable.
14. Implementar primero el flujo mock.
15. Agregar modelos reales recién cuando el pipeline base esté estable.
16. Mantener CPU como fallback funcional, aunque sea lento.
17. Usar GPU solo si está configurada y disponible.
18. Documentar cambios relevantes en `docs/` o README.
19. Evitar dependencias pesadas si no son necesarias para el hito actual.
20. En caso de duda, preservar la frontera del plano de medios.

---

## 19. Qué no asumir

No asumir que:

```text
- Grounding DINO será siempre el modelo principal;
- YOLOE será siempre el modelo más rápido;
- las etiquetas del modelo coinciden exactamente con los prompt_id;
- una detección de casco implica automáticamente que una persona tiene casco;
- ausencia de detección equivale a ausencia real del objeto;
- el pipeline debe operar en streaming desde el primer sprint;
- los resultados frame-a-frame son alertas;
- una baja latencia de inferencia implica baja latencia del sistema completo;
- una corrida sin errores implica buen desempeño semántico.
```

---

## 20. Integración futura

Este repositorio se integrará posteriormente con otros módulos.

### Plano de control

Consumirá `DetectionEvent` y evaluará:

```text
persistencia
histéresis
estado de patrón
confirmación
resolución
alerta interna
```

### Evaluación experimental

Consumirá:

```text
effective_config.yaml
detections.jsonl
metrics.jsonl
errors.jsonl
summary.json
```

Permitirá comparar:

```text
modelos
prompts
umbrales
fuentes
políticas de muestreo
hardware
```

### Streaming / EBE

En una etapa posterior podrán agregarse fuentes como:

```text
webcam
RTSP
MediaMTX
GStreamer
WebRTC
SRT
```

Pero DBE local debe quedar estable primero.

---

## 21. Glosario mínimo

### DBE

Dataset-Based Evaluation. Evaluación con imágenes o videos locales, reproducibles y controlados.

### EBE

Environment-Based Evaluation. Evaluación con cámara, stream o entorno controlado representativo.

### OVD

Open-Vocabulary Detection. Detección guiada por texto o prompts abiertos.

### Plano de medios

Ruta crítica de procesamiento visual. Produce evidencia perceptiva normalizada y métricas.

### Plano de control

Módulo que consume evidencia, evalúa patrones, maneja estados y genera alertas asistivas.

### VisualUnit

Unidad visual procesable: imagen o frame.

### PromptSet

Conjunto versionado de prompts usados en una corrida.

### RawDetection

Salida intermedia de un adaptador de modelo.

### DetectionEvent

Evento perceptivo normalizado producido por el plano de medios.

### MetricSample

Muestra técnica de rendimiento o latencia.

### RunConfig

Configuración declarativa de una corrida experimental.

### Adapter

Capa que encapsula un modelo específico detrás de una interfaz común.

---

## 22. Resumen operativo

El repositorio `eovrt-media-plane` debe implementar el primer núcleo del plano de medios de E-OVRT-VDP.

Debe permitir ejecutar corridas DBE locales con imágenes y luego video.

Debe producir evidencia perceptiva normalizada, trazable y medible.

Debe soportar modelos mediante adaptadores, comenzando por un mock y luego modelos OVD reales.

Debe guardar artefactos por corrida en `runs/`.

Debe mantener una frontera estricta:

```text
sí: detecciones, métricas, configuración, evidencia perceptiva
no: patrones, alertas, severidad, plano de control, streaming inicial
```

El éxito del MVP se alcanza cuando una carpeta local de imágenes puede procesarse de punta a punta y generar una corrida reproducible con detecciones normalizadas, métricas y resumen final.
