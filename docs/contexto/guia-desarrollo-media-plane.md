# Guía de desarrollo del Media Plane — E-OVRT

## 1. Propósito del Media Plane

El Media Plane es el componente encargado de transformar entradas visuales en evidencia perceptiva normalizada. Su responsabilidad principal es procesar imágenes, videos, datasets, cámaras o streams, ejecutar inferencia open-vocabulary y publicar eventos de percepción consumibles por el plano de control.

El foco del repositorio es el pipeline perceptivo. No se busca implementar un stack completo de distribución multimedia ni un sistema de reproducción de video para usuarios finales. El Media Plane debe operar como una ruta de transformación medible, configurable y trazable:

```text
Fuente visual
→ control de ritmo
→ normalización espacial
→ inferencia OVD
→ postproceso perceptivo
→ PerceptionEvent
→ publicación / persistencia / salidas debug
```

La salida formal del Media Plane es el `PerceptionEvent`.

Ese evento representa evidencia visual primaria: detecciones, bounding boxes, etiquetas, confianza, referencias temporales, modelo utilizado, prompts activos y diagnósticos técnicos. La interpretación de esa evidencia corresponde al Control Plane.

---

## 2. Alcance del repositorio

El repositorio del Media Plane debe centralizar los componentes necesarios para ejecutar el pipeline perceptivo de punta a punta.

Incluye:

* lectura de datasets;
* lectura de imágenes y videos locales;
* consumo de cámara o stream RTSP;
* control de ritmo de procesamiento;
* políticas de frescura para fuentes vivas;
* normalización espacial de frames;
* adaptadores de modelos OVD;
* postproceso de detecciones;
* generación de `PerceptionEvent`;
* publicación de eventos hacia un bus interno o sink equivalente;
* persistencia experimental de eventos, métricas y errores;
* generación opcional de previews o videos anotados para debug y demostración.

Queda fuera del alcance directo:

* distribución de video a usuarios finales;
* media servers como componente obligatorio del Media Plane;
* UI o dashboard;
* reglas de riesgo;
* confirmación de patrones;
* generación de alertas;
* severidad;
* notificaciones;
* geofences;
* tracking multiobjeto obligatorio;
* entrenamiento o fine-tuning dentro del pipeline principal;
* despliegues multi-cámara a escala.

El diseño puede prever extensiones futuras, pero el núcleo validable debe mantenerse simple: procesar frames, detectar entidades o condiciones visuales, normalizar resultados y publicar evidencia perceptiva.

---

## 3. Separación entre Media Plane y Control Plane

La separación de responsabilidades debe quedar explícita en todo el diseño.

El Media Plane produce detecciones normalizadas.

El Control Plane interpreta esas detecciones.

El Media Plane puede publicar evidencia como:

```text
persona detectada
casco detectado
chaleco detectado
vehículo detectado
objeto detectado mediante prompt
bounding box
confianza
timestamp
modelo
prompt
```

El Media Plane no debe publicar como salida final:

```text
riesgo confirmado
alerta confirmada
severidad alta
persona insegura confirmada
incumplimiento
estado de patrón
decisión operativa
```

La lógica de riesgo requiere criterios de persistencia temporal, relaciones espaciales, reglas configuradas, histéresis, severidad y estados de patrón. Esa lógica pertenece al Control Plane.

El Media Plane puede producir evidencia candidata útil para esas reglas, pero no debe resolver la decisión de negocio.

---

## 4. Flujo conceptual del pipeline

El flujo objetivo del Media Plane queda definido así:

```text
BaseSource
→ VisualUnit
→ Rate / Freshness Policy
→ Spatial Normalizer
→ NormalizedUnit
→ Detector Adapter
→ RawDetection[]
→ Postprocess Pipeline
→ Detection[]
→ PerceptionEvent
→ Evidence Publisher
→ Sinks / Bus / Debug Outputs
```

Cada etapa debe tener una responsabilidad clara:

| Etapa                  | Responsabilidad                                                             |
| ---------------------- | --------------------------------------------------------------------------- |
| Fuente visual          | Obtener imágenes, frames o unidades visuales desde dataset, video o stream. |
| Control de ritmo       | Decidir qué unidades se procesan, cuáles se omiten y cuáles se descartan.   |
| Normalización espacial | Adaptar el frame al formato esperado por el modelo.                         |
| Inferencia OVD         | Ejecutar el modelo configurado con los prompts o vocabulario activo.        |
| Postproceso            | Filtrar, reproyectar, normalizar, deduplicar y mapear detecciones.          |
| PerceptionEvent        | Encapsular la evidencia perceptiva de una unidad visual.                    |
| Publicación            | Enviar o persistir eventos para consumo posterior.                          |
| Debug visual           | Generar artefactos inspeccionables como imágenes o videos anotados.         |

---

## 5. Entradas visuales y escenarios

El Media Plane debe soportar dos familias de escenarios.

### DBE — Dataset-Based Evaluation

Escenario basado en datos reproducibles. La fuente puede ser una carpeta de imágenes, un video local o un dataset preparado.

Objetivo principal:

* reproducibilidad;
* comparación entre modelos;
* comparación entre prompts;
* evaluación controlada;
* trazabilidad de corrida.

En DBE, el orden de procesamiento y la política de muestreo deben ser determinísticos siempre que sea posible.

### EBE — Environment-Based Evaluation

Escenario basado en fuente viva o entorno representativo. La fuente puede ser una cámara, un stream RTSP o una simulación de stream.

Objetivo principal:

* observar comportamiento temporal;
* medir latencia;
* analizar frescura de frames;
* validar reconexión;
* evaluar descarte por atraso;
* probar estabilidad del pipeline frente a condiciones variables.

En EBE, el sistema no debe intentar procesar todos los frames si eso genera atraso acumulado. Debe priorizar la frescura temporal según la política configurada.

---

## 6. Contratos principales

Los contratos definen la frontera entre etapas. Deben ser estables, serializables y trazables.

### `VisualUnit`

Representa una unidad visual proveniente de una fuente.

Debe incluir, como mínimo:

* identificador de fuente;
* tipo de fuente;
* identificador de frame o unidad;
* índice de frame si corresponde;
* dimensiones originales;
* referencia al contenido visual;
* timestamps disponibles;
* metadatos básicos de origen.

No debe incluir información del modelo ni resultados de inferencia.

---

### `NormalizedUnit`

Representa una unidad visual preparada para inferencia.

Debe incluir:

* referencia al `VisualUnit` original;
* dimensiones de entrada al modelo;
* transformación espacial aplicada;
* modo de resize;
* payload visual normalizado;
* metadatos necesarios para reproyectar cajas al espacio original.

La transformación espacial es crítica. Toda detección generada en el espacio del modelo debe poder volver correctamente al espacio original de la imagen o frame.

---

### `RawDetection`

Representa una salida cruda del modelo antes de normalización completa.

Debe incluir:

* caja en el espacio de entrada del modelo;
* score o confianza;
* label, frase, clase o salida textual cruda;
* identificador de prompt si el modelo lo provee;
* información específica del modelo cuando sea necesaria.

Este contrato debe aceptar diferencias entre modelos. YOLOE y Grounding DINO pueden expresar sus salidas de manera distinta, por lo que el postproceso debe normalizarlas sin perder trazabilidad.

---

### `Detection`

Representa una detección normalizada.

Debe incluir:

* etiqueta canónica;
* label cruda original;
* `prompt_id` asociado cuando corresponda;
* confianza normalizada;
* bounding box en píxeles originales;
* bounding box normalizada entre 0 y 1;
* área;
* referencia al modelo y prompt;
* metadatos mínimos de postproceso.

`Detection` describe evidencia visual. No describe una alerta ni una condición de riesgo confirmada.

---

### `PerceptionEvent`

Es la salida formal del Media Plane.

Representa el evento completo de percepción asociado a una unidad visual procesada.

Debe incluir:

* versión de esquema;
* identificador de evento;
* identificador de corrida;
* fuente;
* frame o unidad visual;
* timestamps relevantes;
* modelo utilizado;
* prompts o vocabulario activo;
* configuración relevante de inferencia;
* lista de detecciones normalizadas;
* diagnósticos de postproceso;
* métricas temporales del frame;
* información de descartes o anomalías asociadas.

El `PerceptionEvent` debe ser suficiente para que el Control Plane pueda evaluar patrones sin acceder al frame crudo ni conocer detalles internos del modelo.

---

### `MetricSample`

Representa una muestra técnica por unidad procesada o por tramo del pipeline.

Debe permitir medir:

* latencia de lectura o captura;
* tiempo en cola;
* latencia de normalización;
* latencia de inferencia;
* latencia de postproceso;
* latencia de publicación;
* edad del frame procesado;
* FPS efectivo;
* uso básico de recursos cuando esté disponible.

---

### `ErrorEvent`

Representa errores o anomalías detectadas durante una corrida.

Debe incluir:

* etapa donde ocurrió;
* fuente afectada;
* mensaje;
* tipo de error;
* recuperabilidad;
* impacto sobre la corrida;
* timestamp;
* contexto mínimo para diagnóstico.

---

### `RunSummary`

Representa el resumen final de una corrida.

Debe incluir:

* estado final de la corrida;
* configuración efectiva;
* fuente utilizada;
* modelo utilizado;
* prompts activos;
* cantidad de unidades vistas;
* cantidad de unidades procesadas;
* cantidad de unidades descartadas;
* latencias agregadas;
* FPS efectivo;
* errores;
* advertencias;
* artefactos generados;
* limitaciones observadas.

---

## 7. Publicación de evidencia

El Media Plane debe publicar `PerceptionEvent` mediante una frontera desacoplada.

El componente conceptual recomendado es:

```text
EvidencePublisher
```

Su responsabilidad es enviar eventos a uno o más destinos sin acoplar el pipeline a un mecanismo específico.

Destinos posibles:

* archivo JSONL;
* bus interno;
* endpoint HTTP;
* cola o stream de mensajes;
* salida de debug;
* sink de pruebas.

Para el prototipo, la persistencia en archivos es suficiente como salida experimental, siempre que el contrato sea el mismo que luego consumirá el Control Plane.

El nombre recomendado para el archivo principal de eventos es:

```text
perception_events.jsonl
```

---

## 8. Control de ritmo y frescura temporal

El control de ritmo debe distinguir entre fuentes reproducibles y fuentes vivas.

Para datasets o videos procesados como corrida reproducible, se prioriza determinismo:

```text
procesar todos los frames
procesar 1 de cada N frames
mantener orden
registrar omisiones
```

Para streams o cámaras, se prioriza frescura:

```text
mantener buffer acotado
descartar frames viejos
evitar atraso acumulado
procesar el frame más reciente cuando corresponda
registrar descartes
```

La política debe ser configurable. El modo “último frame disponible” debe poder expresarse con una cola de tamaño uno o una política equivalente de reemplazo.

El objetivo en fuentes vivas no es procesar todo, sino procesar evidencia suficientemente fresca para sostener evaluación temporal posterior.

Métricas importantes:

* frames recibidos;
* frames aceptados;
* frames procesados;
* frames omitidos;
* frames descartados por cola;
* frames descartados por staleness;
* edad del frame al procesarse;
* edad del frame al publicarse;
* FPS efectivo.

---

## 9. Manejo temporal y latencia

El manejo temporal debe ser tratado como una prioridad del Media Plane.

Cada `PerceptionEvent` debe transportar referencias temporales suficientes para reconstruir el recorrido de una unidad visual desde su captura o lectura hasta su publicación.

Se deben distinguir dos tipos de tiempo:

| Tipo de tiempo    | Uso                                                       |
| ----------------- | --------------------------------------------------------- |
| Tiempo UTC        | Correlación externa, auditoría, logs, eventos publicados. |
| Tiempo monotónico | Cálculo confiable de latencias internas.                  |

Para DBE, el tiempo se usa principalmente para reproducibilidad y análisis de rendimiento.

Para EBE, el tiempo se usa para medir frescura, atraso, latencia y comportamiento bajo carga.

Tramos relevantes:

* lectura o captura;
* entrada a cola;
* salida de cola;
* normalización;
* inferencia;
* postproceso;
* publicación;
* render debug si está habilitado.

El renderizado debug y la generación de video anotado deben medirse aparte para no contaminar las métricas principales del pipeline perceptivo.

---

## 10. Postproceso perceptivo

El postproceso debe convertirse en un módulo explícito del Media Plane.

Su responsabilidad es transformar salidas crudas de modelos OVD en detecciones comparables, válidas y trazables.

Debe contemplar:

* validación de cajas;
* clipping contra dimensiones de imagen;
* filtro por confianza;
* filtro por área;
* reproyección al espacio original;
* cálculo de coordenadas normalizadas;
* mapeo de labels o frases a etiquetas canónicas;
* asociación con `prompt_id`;
* deduplicación;
* NMS cuando corresponda;
* registro de descartes;
* preservación de información cruda útil para diagnóstico.

Debe estar pensado para soportar como mínimo:

* YOLOE;
* Grounding DINO.

YOLOE tiende a producir salidas más cercanas a clases o vocabulario configurado. Grounding DINO puede producir frases, scores textuales y asociaciones más dependientes del prompt. El postproceso debe normalizar ambos casos sin ocultar esas diferencias.

El resultado final del postproceso es una lista de `Detection[]` lista para incluirse en un `PerceptionEvent`.

---

## 11. Prompts, etiquetas y vocabulario

El Media Plane debe tratar los prompts como parte central de la corrida experimental.

Cada detección debe poder asociarse, cuando corresponda, a:

* prompt original;
* conjunto de prompts;
* versión del prompt set;
* etiqueta canónica;
* label o frase cruda producida por el modelo.

Debe existir una normalización semántica mínima para que distintas formulaciones equivalentes puedan mapearse a una misma etiqueta canónica.

Ejemplo conceptual:

```text
"helmet"
"hard hat"
"safety helmet"
→ helmet
```

Esto no debe confundirse con lógica de riesgo. La normalización semántica solo ordena la evidencia perceptiva para que sea comparable y consumible.

---

## 12. Adaptadores de modelo

Los modelos deben integrarse mediante adaptadores.

El objetivo es poder cambiar de modelo sin modificar el resto del pipeline.

La interfaz del adaptador debe permitir:

* cargar el modelo;
* preparar prompts o vocabulario;
* declarar capacidades relevantes;
* ejecutar inferencia sobre una unidad normalizada;
* devolver detecciones crudas;
* liberar recursos si corresponde.

La interfaz debe contemplar que no todos los modelos operan igual:

* algunos aceptan prompts dinámicos;
* algunos trabajan mejor con vocabulario fijo;
* algunos permiten cachear embeddings textuales;
* algunos pueden usar reparametrización;
* algunos exponen scores textuales o frases;
* otros devuelven clases y scores más tradicionales.

No hace falta que el pipeline exponga todos los detalles internos del modelo, pero sí debe registrar el modo de ejecución para que la corrida sea interpretable.

---

## 13. RTSP y fuentes vivas

El soporte RTSP debe documentarse con claridad porque puede afectar de manera fuerte la latencia real.

La fuente RTSP debe declarar:

* backend de lectura o decodificación utilizado;
* protocolo de transporte si aplica;
* resolución esperada;
* FPS esperado;
* política de timeout;
* política de reconexión;
* manejo de pérdida de frames;
* forma de asignar timestamps;
* existencia de buffers internos relevantes.

En fuentes vivas, el sistema debe evitar procesar frames acumulados y viejos. Para eso, la lectura o captura debe estar alineada con la política de frescura configurada.

Escenarios mínimos a validar:

* stream estable;
* stream cortado;
* reconexión;
* consumidor lento;
* cola llena;
* descarte por staleness;
* procesamiento del último frame disponible.

La prioridad no es construir una infraestructura multimedia industrial, sino asegurar que el pipeline mida correctamente frescura, descarte y latencia.

---

## 14. Transporte de frames y limitaciones actuales

El transporte de frames crudos es aceptable para el alcance experimental del proyecto.

Este enfoque prioriza:

* simplicidad;
* control del pipeline;
* trazabilidad;
* facilidad de depuración;
* integración rápida entre etapas.

Limitaciones:

* no está optimizado para muchas cámaras;
* aumenta el uso de memoria;
* puede generar copias costosas;
* puede consumir ancho de banda significativo;
* no aprovecha compresión de video;
* no está pensado para WAN;
* no reemplaza un protocolo de streaming;
* puede escalar mal si aumentan resolución, FPS o cantidad de cámaras.

El alcance actual debe documentarse como orientado a una cámara principal y, eventualmente, dos cámaras en entorno local o red controlada.

Para más cámaras, mayor resolución o despliegue distribuido real, sería necesario evaluar otros mecanismos de transporte o integración multimedia. Esa evolución queda fuera del núcleo actual.

---

## 15. Artefactos de salida

Cada corrida debe producir artefactos suficientes para inspección, trazabilidad y evaluación.

Artefactos recomendados:

| Artefacto                   | Propósito                                                     |
| --------------------------- | ------------------------------------------------------------- |
| `perception_events.jsonl`   | Eventos de percepción publicados o persistidos.               |
| `metrics.jsonl`             | Métricas técnicas por unidad o tramo.                         |
| `errors.jsonl`              | Errores y anomalías recuperables o no recuperables.           |
| `summary.json`              | Resumen final de la corrida.                                  |
| `effective_config.yaml`     | Configuración efectiva con defaults resueltos.                |
| `run_config.yaml`           | Configuración original de la corrida.                         |
| `run_manifest.json`         | Archivos generados y metadatos de ejecución.                  |
| `run_provenance.json`       | Fuente, dataset, prompts, modelo y trazabilidad experimental. |
| `previews/`                 | Imágenes anotadas para inspección rápida.                     |
| `debug/annotated_video.mp4` | Video anotado opcional para demo o depuración.                |

Los artefactos visuales son auxiliares. La salida formal del Media Plane sigue siendo el `PerceptionEvent`.

---

## 16. Videos anotados para debug y demostración

El Media Plane debe poder generar videos anotados de forma opcional.

Este recurso es importante para:

* demostrar el sistema funcionando;
* inspeccionar visualmente una corrida;
* validar detecciones;
* comparar comportamiento entre modelos;
* detectar falsos positivos o falsos negativos;
* mostrar evidencia en la defensa o demo.

El video anotado debe derivarse de los mismos `PerceptionEvent` que se publican o persisten. No debe usar una lógica paralela distinta.

Debe poder mostrar:

* bounding boxes;
* etiqueta canónica;
* confianza;
* prompt asociado si corresponde;
* frame index;
* fuente;
* modelo;
* latencia de inferencia;
* edad del frame en fuentes vivas.

La generación de video anotado debe ser configurable y opcional, porque puede agregar carga de CPU, escritura a disco y latencia adicional.

El costo del renderizado debug debe medirse por separado.

La existencia de videos anotados no modifica el contrato principal del Media Plane.

---

## 17. Estado de corrida y errores

El sistema debe distinguir entre una corrida exitosa, degradada o fallida.

Estados recomendados:

| Estado     | Significado                                                                                           |
| ---------- | ----------------------------------------------------------------------------------------------------- |
| `success`  | La corrida finalizó con resultados válidos.                                                           |
| `degraded` | La corrida finalizó, pero con errores, descartes excesivos, staleness alto o reconexiones relevantes. |
| `failed`   | La corrida no produjo resultados válidos o falló una etapa crítica.                                   |
| `aborted`  | La corrida fue interrumpida manual o externamente.                                                    |

El resumen final debe explicar por qué una corrida quedó degradada o fallida.

Esto es importante para no interpretar como equivalente una corrida limpia y una corrida que terminó pero perdió evidencia, procesó frames viejos o sufrió fallas de fuente.

---

## 18. Testing y validación mínima

El desarrollo debe incluir pruebas que validen el comportamiento del pipeline completo, no solo funciones aisladas.

Áreas mínimas de testing:

### Contratos

* serialización y deserialización;
* campos obligatorios;
* compatibilidad entre etapas;
* validez de `PerceptionEvent`;
* detecciones con bounding boxes consistentes.

### Pipeline DBE

* procesamiento reproducible;
* stride determinístico;
* generación de eventos;
* generación de métricas;
* resumen final;
* previews o video anotado si está habilitado.

### Pipeline EBE

* fuente viva estable;
* consumidor lento;
* cola acotada;
* descarte de frames viejos;
* medición de frame age;
* reconexión;
* corrida degradada cuando corresponda.

### Postproceso

* salida YOLOE normalizada;
* salida Grounding DINO normalizada;
* reproyección correcta;
* filtros por confianza y área;
* deduplicación;
* mapeo a etiquetas canónicas;
* conteo de descartes.

### Publicación

* generación de `PerceptionEvent`;
* persistencia en JSONL;
* publicación desacoplada;
* errores de publicación registrados;
* consistencia entre evento publicado y video anotado.

---

## 19. Prioridades de desarrollo

### Prioridad alta

1. Formalizar `PerceptionEvent` como contrato de salida del Media Plane.
2. Separar claramente detección, patrón y alerta.
3. Implementar una frontera de publicación desacoplada.
4. Fortalecer timestamps y métricas de latencia por tramo.
5. Mejorar la política de ritmo y frescura para fuentes vivas.
6. Consolidar el postproceso común para YOLOE y Grounding DINO.
7. Documentar la fuente RTSP y su comportamiento real.
8. Documentar límites del transporte de frames crudos.
9. Agregar salida opcional de video anotado para debug y demo.

### Prioridad media

1. Registrar capacidades y modo de ejecución de cada modelo.
2. Mejorar normalización de prompts y etiquetas canónicas.
3. Agregar estado de corrida.
4. Ampliar tests de EBE con consumidor lento y reconexión.
5. Medir costo separado de renderizado debug.
6. Mejorar documentación de configuración efectiva.

### Prioridad futura

1. Evaluar transporte más eficiente si aumenta la cantidad de cámaras.
2. Evaluar optimizaciones de inferencia.
3. Incorporar tracking como módulo opcional.
4. Incorporar geofences como entrada al Control Plane.
5. Integrar media server solo si el alcance experimental lo requiere.
6. Evaluar despliegues multi-cámara fuera del núcleo validable.

---

## 20. Criterio de cierre del núcleo validable

El núcleo del Media Plane se considera validable cuando puede:

1. leer una fuente visual reproducible o viva;
2. controlar el ritmo de procesamiento;
3. normalizar frames para inferencia;
4. ejecutar al menos YOLOE y Grounding DINO mediante adaptadores;
5. postprocesar detecciones de forma comparable;
6. generar `PerceptionEvent` correctamente estructurados;
7. publicar o persistir esos eventos;
8. registrar métricas de latencia y descartes;
9. registrar errores y estado de corrida;
10. generar artefactos de trazabilidad;
11. producir videos anotados opcionales para debug o demostración;
12. dejar claro que la lógica de patrones y alertas pertenece al Control Plane.

La meta del Media Plane no es resolver toda la plataforma, sino producir evidencia perceptiva confiable, trazable y medible para que el resto del sistema pueda interpretarla.
