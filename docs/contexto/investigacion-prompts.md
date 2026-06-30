# Reporte para Claude Code — Investigación y diseño del módulo experimental de prompts OVD

> **Anotación de adopción (2026-06-26).** Este documento es la **guía de investigación de
> partida**; *no es autoritario*. A continuación se marca, sección por sección, qué se
> incorpora al diseño de la capa de prompts del media-plane, qué se descarta (con
> justificación) y qué corresponde a **otro módulo** de la plataforma. Referencias:
> spec `docs/superpowers/specs/2026-06-25-prompt-layer-design.md` y el alcance fijado en
> `CLAUDE.md` (el media-plane **no** implementa reglas de riesgo, alertas, tracking, zonas
> ni plano de control). El proyecto ya migró a `canonical_v2` (person/helmet/vest/bare_head);
> el framing CR-01…CR-06 del informe se conserva solo como trazabilidad opcional.
>
> **Leyenda:** ✅ TOMADO · 🟡 TOMADO PARCIAL · ⛔ NO TOMADO (justificado) · 🔀 OTRO MÓDULO · 🕓 DIFERIDO
>
> | Elemento del informe | Decisión | Dónde / por qué |
> |---|---|---|
> | Esquema de Prompt (§6.1) | 🟡 | `id`/`canonical`/`role` + `strategy`/`condition_id` como metadato opcional; `text`→`phrasings`; versión por archivo git |
> | PromptVariant versionado (§6.2) | ⛔ | A/B por archivos YAML alternativos en git, no por entidad |
> | ActiveVocabulary entidad (§6.3) | ⛔ | `active_ids` + sets alternativos (isolated = set mínimo) |
> | PromptStrategy (§6.4) | 🟡 / 🔀 | direct/positive/indirect/template/auxiliary = metadato; relational/zone/decomposed = plano de control |
> | ModelPromptAdapter (§6.5) | ✅ / 🕓 | ya existe `BaseDetectorAdapter` (gdino/mm-gdino/yoloe/mock); owlvit/florence2/yolo-world diferidos (sin pesos) |
> | Catálogo de frases (§5) | 🟡 | frases reutilizadas como `phrasings` (cortas→YOLOE, descriptivas→GDINO) |
> | CR-01 / CR-02 (§4.1) | ✅ | ya son `canonical_v2` |
> | CR-03 / CR-04 (§4.2) | 🕓 | exploratorias, sin GT suficiente |
> | CR-05 / CR-06 (§4.2) | 🔀 | reglas relacionales/zonas = plano de control |
> | PerceptionEvent (§7.2) | 🔀 | media-plane emite `Detection`/`DetectionEvent`; evento perceptivo = plano de control |
> | Matriz experimental + métricas (§8) | 🔀 / ✅ ya existe | `evaluate_bench.py` (repo datasets) + `compare-runs` |
> | Estructura de carpetas (§9) | ⛔ | se respeta la estructura actual del media-plane |
> | Validaciones (§10) | 🟡 | solo las aplicables al esquema nuevo |
> | Decisiones no negociables (§13) | ✅ | inglés primario, vocab por corrida, prompt≠alerta, trazabilidad |

## 1. Contexto del proyecto

El proyecto E-OVRT-VDP es una plataforma experimental de detección open-vocabulary en video en tiempo real para monitoreo asistivo de riesgos en construcción civil.

El sistema debe procesar fuentes visuales, ejecutar inferencia OVD, producir evidencia perceptiva normalizada y permitir que el plano de control evalúe patrones de riesgo y genere alertas asistivas. El módulo solicitado en este reporte se concentra exclusivamente en la capa de prompts y vocabulario activo, no en la lógica completa de alertas.

El informe define que el diseño de prompts no es un detalle menor: es una variable experimental que puede modificar falsos positivos, falsos negativos, estabilidad temporal, latencia y comparabilidad entre corridas. Por eso, el módulo debe permitir diseñar, versionar, activar, evaluar y comparar prompts de manera reproducible.

## 2. Objetivo principal

Diseñar e implementar un módulo robusto y experimental de prompts para modelos OVD, capaz de:

1. Representar un catálogo versionado de prompts candidatos.
2. Asociar cada prompt a una condición de riesgo del proyecto.
3. Diferenciar estrategia directa, indirecta, descompuesta, auxiliar y template.
4. Construir vocabularios activos por corrida.
5. Adaptar la sintaxis del prompt a distintos modelos OVD.
6. Ejecutar matrices experimentales de prompts.
7. Medir desempeño por modelo, condición, prompt y contexto de vocabulario.
8. Registrar resultados reproducibles y trazables.
9. Producir evidencia perceptiva compatible con el resto de la arquitectura.
10. Mantener separación estricta entre prompt, detección, patrón y alerta.

El módulo no debe convertir detecciones en alertas. La alerta corresponde al plano de control y al motor de patrones.

## 3. Investigación requerida

Antes de diseñar la implementación definitiva, realizar una investigación técnica completa sobre los trabajos y proyectos que fundamentan el diseño de prompts para OVD.

### 3.1 Papers y trabajos obligatorios

Investigar como mínimo:

* Zhou et al. — Learning to Prompt for Vision-Language Models.
* Du et al. — Learning to Prompt for Open-Vocabulary Object Detection with Vision-Language Model.
* FG-OVD — benchmark para atributos finos, hard negatives y vocabularios de granularidad fina.
* OVDEval — evaluación de atributos, posición, relaciones y métricas complementarias como NMS-AP.
* CLIP — uso de templates tipo “a photo of a [CLASS]”.
* Grounding DINO — procesamiento texto-imagen, concatenación de categorías y sensibilidad a longitud del prompt.
* YOLO-World — estrategia prompt-then-detect y vocabulario offline.
* YOLOE — prompts textuales, prompts visuales, RepRTA y reparametrización.
* OWL-ViT / OWLv2 — detección basada en embeddings textuales.
* Florence-2 — prompting multitarea y diferencias frente a detectores OVD directos.

### 3.2 Preguntas de investigación

Responder en un documento `docs/research/prompt_module_research.md`:

1. ¿Cómo afecta la formulación textual al desempeño de modelos visión-lenguaje y OVD?
2. ¿Por qué los métodos de prompt learning de clasificación no se transfieren directamente a detección?
3. ¿Qué diferencias prácticas hay entre prompt directo e indirecto para condiciones de ausencia de EPP?
4. ¿Qué problemas aparecen con prompts de atributos finos como casco, chaleco reflectivo, arnés o ropa de alta visibilidad?
5. ¿Cómo impactan los hard negatives y los prompts semánticamente cercanos?
6. ¿Qué diferencias hay entre evaluar un prompt aislado y evaluarlo dentro del vocabulario activo completo?
7. ¿Qué modelos permiten cachear, precomputar o reparametrizar embeddings textuales?
8. ¿Qué limitaciones tiene cada familia de modelos respecto del tamaño del vocabulario activo?
9. ¿Conviene mantener prompts primarios en inglés? ¿Cómo se debería evaluar una variante en español?
10. ¿Cómo debe registrarse una modificación de redacción para que sea comparable y reproducible?

La investigación debe terminar en decisiones concretas de diseño para el módulo.

## 4. Condiciones de riesgo del catálogo

> **CR-01/CR-02 ✅** → ya son `canonical_v2` (person/helmet/vest/bare_head). **CR-03/CR-04 🕓**
> exploratorias (sin GT suficiente; no bloquean). **CR-05/CR-06 🔀** se resuelven con entidades
> componentes + reglas relacionales/zonas en el **plano de control**, no en la capa de prompts.
> `condition_id` solo sobrevive como **metadato opcional** de trazabilidad.

El módulo debe soportar las seis condiciones metodológicas del informe, pero debe distinguir el núcleo obligatorio de las extensiones condicionadas.

### 4.1 Núcleo obligatorio

Estas condiciones deben tener soporte completo desde el inicio:

* CR-01 — Persona sin casco.
* CR-02 — Persona sin chaleco reflectivo.

Ambas deben permitir evaluación directa e indirecta.

### 4.2 Condiciones exploratorias o condicionadas

Estas condiciones deben estar representadas en el catálogo, pero no deben bloquear la aceptación inicial del módulo:

* CR-03 — Persona en posición elevada sin sistema anticaídas visible.
* CR-04 — Borde elevado desprotegido con personas próximas.
* CR-05 — Maquinaria en operación cerca de peatones.
* CR-06 — Persona dentro de zona restringida.

Para CR-03 y CR-04, permitir prompts compuestos y descompuestos, pero marcar su evaluación como parcial si no hay ground truth suficiente.

Para CR-05 y CR-06, no formular la condición completa como un único prompt OVD. Deben usarse prompts de entidades componentes y dejar la evaluación completa al módulo relacional, tracking, zonas o motor de patrones.

## 5. Catálogo inicial de prompts

> 🟡 **TOMADO PARCIAL.** Las frases sirven de insumo para `phrasings` (cortas→YOLOE,
> descriptivas→GDINO; ver `ppe_v2_descriptive.yaml`). El separador `;` (estrategia indirecta)
> **no** se interpreta como texto en la capa de prompts: la combinación persona+EPP es 🔀 del
> plano de control.

El módulo debe cargar un catálogo inicial equivalente al siguiente.

### CR-01 — Persona sin casco

* `person without hard hat`
* `construction worker without safety helmet`
* `person with bare head on construction site`
* `a photo of a hard hat`
* `hard hat`
* `safety helmet`
* `person`
* `worker`
* estrategia indirecta: `hard hat ; person`

### CR-02 — Persona sin chaleco reflectivo

* `person without reflective vest`
* `worker without high-visibility vest`
* `person without bright colored safety clothing`
* `a photo of a reflective safety vest`
* `reflective vest`
* `safety vest`
* `high visibility vest`
* `person`
* `worker`
* estrategia indirecta: `reflective vest ; person`

### CR-03 — Trabajo en altura sin anticaídas visible

* `person on scaffolding without harness`
* `worker at height without fall protection equipment`
* `person on scaffolding`
* `person on elevated platform`
* `safety harness`
* `fall arrest harness`
* `unprotected worker on elevated platform`

### CR-04 — Borde elevado desprotegido

* `unprotected edge with person nearby`
* `elevated platform without guardrail near workers`
* `platform edge`
* `guardrail`
* `safety railing`
* `person at height`

### CR-05 — Maquinaria cerca de peatones

Entidades maquinaria:

* `excavator`
* `backhoe loader`
* `dump truck`
* `crane`
* `heavy machinery`

Entidades humanas:

* `person`
* `construction worker`
* `pedestrian`

### CR-06 — Persona en zona restringida

Entidad principal:

* `person`
* `worker`
* `pedestrian`

Elementos auxiliares:

* `restricted area sign`
* `caution tape`
* `warning tape`
* `barrier`
* `safety cone`

Los prompts con separador `;` no deben interpretarse como una cadena textual única salvo que el adaptador del modelo lo requiera. Deben tratarse como consultas independientes cuya combinación pertenece a una estrategia de detección.

## 6. Modelo conceptual del módulo

Diseñar el módulo alrededor de estos conceptos:

### 6.1 Prompt

> 🟡 **TOMADO PARCIAL.** El spec usa `id`/`canonical`/`role`; se suman `strategy` y
> `condition_id` como **metadato opcional** (etiquetas, sin lógica de ramificación). `text` se
> reemplaza por `phrasings` por backend; `version` se maneja por **archivo en git**, no por campo.

Unidad semántica textual. Representa una consulta que puede ser entregada a un modelo OVD.

Campos mínimos:

* `prompt_id`
* `condition_id`
* `text`
* `language`
* `strategy`
* `variant_axis`
* `version`
* `enabled`
* `role`
* `notes`

### 6.2 PromptVariant

> ⛔ **NO TOMADO.** El versionado de variantes se hace por **archivos YAML alternativos en git**
> (A/B = otro archivo), más simple y trazable para trabajo experimental que una entidad
> `PromptVariant` con `status/rationale/source`.

Variante experimental de un prompt. Toda modificación de redacción debe crear una nueva variante, no sobrescribir la anterior.

Campos mínimos:

* `variant_id`
* `base_prompt_id`
* `text`
* `axis`
* `created_at`
* `rationale`
* `source`
* `status`

Ejes sugeridos:

* `syntactic`
* `specificity`
* `observable_state`
* `template`
* `direct`
* `indirect`
* `decomposed`
* `auxiliary`
* `visual_reference`
* `spanish`
* `translated`

### 6.3 ActiveVocabulary

> ⛔ **NO TOMADO como entidad.** Se cubre con `active_ids` + sets alternativos. "isolated" = set
> mínimo; "full_context" = set completo; "hard_negatives"/"diagnostic" = otro archivo. Sin objeto
> versionado nuevo.

Conjunto de prompts habilitados en una corrida.

Debe poder representar:

* vocabulario mínimo del núcleo validable;
* vocabulario por condición;
* vocabulario completo;
* vocabulario diagnóstico;
* vocabulario aislado para evaluación;
* vocabulario con hard negatives;
* vocabulario específico por modelo.

Campos mínimos:

* `vocabulary_id`
* `name`
* `version`
* `prompt_ids`
* `model_family`
* `purpose`
* `max_size`
* `created_from`
* `notes`

### 6.4 PromptStrategy

> 🟡 / 🔀 **TOMADO como metadato:** `direct_absence`/`positive_evidence`/`indirect_absence`/
> `template`/`auxiliary_diagnostic` como etiqueta de clase (se propaga a `detections.jsonl`). La
> capa de prompts **no** ramifica lógica sobre ella. `relational_component`/`zone_reference`/
> `decomposed_context` 🔀 pertenecen al **plano de control**.

Define cómo se usa un prompt o conjunto de prompts.

Estrategias mínimas:

* `direct_absence`: intenta detectar la condición completa, por ejemplo `person without hard hat`.
* `positive_evidence`: detecta entidad o EPP presente, por ejemplo `hard hat`.
* `indirect_absence`: detecta persona y EPP por separado; la ausencia se evalúa fuera del modelo.
* `decomposed_context`: detecta entidades componentes para reglas espaciales.
* `template`: usa estructura tipo CLIP, por ejemplo `a photo of a hard hat`.
* `auxiliary_diagnostic`: no alimenta alerta; sirve para diagnóstico de falsos positivos o falsos negativos.
* `relational_component`: prompt de entidad usado por reglas relacionales.
* `zone_reference`: prompt de elemento auxiliar de zona, sin reemplazar polígonos externos.

### 6.5 ModelPromptAdapter

> ✅ / 🕓 **TOMADO:** ya existe `BaseDetectorAdapter` (gdino/mm-gdino/yoloe/mock) y el spec añade
> binding por construcción + `PROMPT_BACKEND`. OWL-ViT/Florence-2/YOLO-World 🕓 **diferidos** (sin
> pesos en el proyecto; Sprint 2 evaluó GDINO/MM-GDINO/YOLOE).

Adaptador específico por familia de modelo OVD.

Debe resolver:

* cómo se entrega el prompt al modelo;
* cómo se separan múltiples clases;
* cómo se cachean o precomputan embeddings;
* cómo se representa el vocabulario activo;
* cómo se mapean etiquetas de salida a `prompt_id`;
* cómo se conservan scores, cajas y metadatos.

Adaptadores iniciales deseables:

* `GroundingDinoPromptAdapter`
* `YoloWorldPromptAdapter`
* `YoloEPromptAdapter`
* `OwlVitPromptAdapter`
* `Florence2PromptAdapter`

El diseño debe permitir implementar primero adaptadores mock o stubs y luego integrar modelos reales.

## 7. Integración con la arquitectura del sistema

El módulo de prompts debe integrarse con la configuración de corrida y con la salida perceptiva del plano de medios.

### 7.1 Entrada

Debe consumir:

* configuración de corrida;
* modelo OVD seleccionado;
* catálogo de prompts;
* vocabulario activo;
* umbrales por modelo o por prompt;
* fuente visual;
* estrategia experimental.

### 7.2 Salida

> 🔀 **OTRO MÓDULO.** El media-plane emite `Detection`/`DetectionEvent`; `PerceptionEvent` y su
> semántica de evidencia pertenecen al **plano de control**. La trazabilidad
> (`prompt_id`/`canonical`/`source_prompt`, + `strategy`/`condition_id` opcionales) ya viaja en
> `detections.jsonl`, lista para que el plano de control la consuma.

Debe producir evidencia perceptiva normalizada compatible con `PerceptionEvent`.

Cada detección o evidencia publicada debe conservar:

* `run_id`
* `source_id`
* `frame_id` o referencia temporal equivalente
* `model_id`
* `model_version`
* `prompt_id`
* `prompt_text`
* `prompt_version`
* `condition_id`
* `strategy`
* `vocabulary_id`
* `confidence`
* `bbox`
* `label`
* `timestamp`
* `postprocess_status`
* `raw_model_output_ref`

La salida no debe llamarse `DetectionEvent` si el proyecto ya decidió usar `PerceptionEvent`.

### 7.3 Separación de responsabilidades

El módulo de prompts:

* define consultas;
* versiona variantes;
* arma vocabularios;
* adapta prompts a modelos;
* registra evidencia;
* habilita evaluación experimental.

El módulo de prompts no debe:

* confirmar patrones;
* generar alertas;
* aplicar severidad;
* tomar decisiones normativas;
* resolver por sí solo relaciones espaciales persistentes;
* reemplazar el motor de patrones.

## 8. Evaluación experimental

> 🔀 / ✅ **YA EXISTE.** La evaluación BENCH vive en el repo `e-ovrt_datasets`
> (`evaluate_bench.py`: AP@0.5 por clase, recall CR-01) y el media-plane ya tiene `compare-runs`.
> **No** se construye un runner de matriz nuevo dentro de la capa de prompts: el A/B se arma con
> sets + `active_ids` + corridas, y la matriz `(modelo × set × vocabulario)` se barre por configs.
> Las métricas avanzadas (NMS-AP, hard-negative recall) se evalúan con el tooling de datasets.

El módulo debe incluir una herramienta o pipeline de evaluación de prompts.

### 8.1 Matriz experimental

Cada corrida de evaluación debe representar una tupla:

`(modelo OVD, condición de riesgo, variante de prompt, contexto de vocabulario, dataset, umbrales, resolución, preprocesamiento)`

Debe soportar al menos dos contextos de vocabulario:

* `isolated`: el prompt se evalúa solo o con el conjunto mínimo requerido.
* `full_context`: el prompt se evalúa junto con el vocabulario activo completo.

Debe permitir agregar:

* contexto con hard negatives;
* variantes en español;
* variantes traducidas;
* distintas resoluciones;
* distintos thresholds;
* distintos modelos.

### 8.2 Métricas mínimas

Calcular por combinación:

* AP@0.5 cuando exista ground truth compatible;
* precision;
* recall;
* F1;
* falsos positivos;
* falsos negativos;
* confianza media de verdaderos positivos;
* cantidad de detecciones por imagen/frame;
* latencia de inferencia;
* costo de postproceso;
* diferencia entre evaluación aislada y evaluación con vocabulario completo.

Para estrategias indirectas o descompuestas, calcular métricas por entidad componente antes de evaluar la condición completa.

### 8.3 Reproducibilidad

Cada experimento debe guardar:

* configuración completa;
* versión del catálogo de prompts;
* versión del código;
* modelo y checkpoint;
* dataset y partición;
* hardware;
* parámetros de inferencia;
* resultados crudos;
* resultados normalizados;
* resumen agregado;
* errores y descartes.

Formatos sugeridos:

* `prompt_catalog.yaml`
* `active_vocabulary.yaml`
* `run_config.yaml`
* `detections_raw.jsonl`
* `perception_events.jsonl`
* `metrics_by_prompt.csv`
* `summary.json`
* `prompt_eval_report.md`

## 9. Diseño recomendado de carpetas

> ⛔ **NO TOMADO tal cual.** Se respeta la estructura existente del media-plane
> (`configs/prompts/`, `src/eovrt_media/{config,models,contracts,runtime}`). No se crea
> `src/prompts/` ni `experiments/prompt_eval/`: la capa de prompts vive en `config/` (schema +
> `PromptPlan`) y los adaptadores en `models/`.

Proponer una estructura similar a:

```text
configs/
  prompts/
    prompt_catalog.yaml
    active_vocabularies/
      core_cr01_cr02.yaml
      full_catalog.yaml
      diagnostic.yaml
      hard_negatives.yaml

src/
  prompts/
    catalog.py
    schemas.py
    vocabulary.py
    strategies.py
    validators.py
    adapters/
      base.py
      grounding_dino.py
      yolo_world.py
      yoloe.py
      owlvit.py
      florence2.py

  experiments/
    prompt_eval/
      matrix_builder.py
      runner.py
      metrics.py
      report_writer.py

docs/
  research/
    prompt_module_research.md
  architecture/
    prompt_module_design.md

tests/
  prompts/
    test_catalog_validation.py
    test_vocabulary_builder.py
    test_prompt_versioning.py
    test_model_adapters.py
    test_prompt_eval_matrix.py
```

La estructura exacta debe adaptarse al repositorio real luego de inspeccionarlo.

## 10. Validaciones obligatorias

> 🟡 **TOMADO PARCIAL.** Se aplican las relevantes al esquema nuevo: set/clase válidos, fallback
> de `phrasings` (`backend`→`default`, error si falta), colisión de texto duplicado, `active_ids`
> inexistente, vocabulario activo vacío. Las ligadas a variantes/vocabularios-entidad/matriz no
> aplican; las de CR-05/CR-06 y "salida sin trazabilidad a alerta" son 🔀 del plano de control.

El módulo debe impedir o advertir:

1. Prompt sin `condition_id`.
2. Prompt sin versión.
3. Prompt activo sin estrategia declarada.
4. Vocabulario activo vacío.
5. Vocabulario activo incompatible con el modelo.
6. Estrategia indirecta sin entidades mínimas.
7. Prompt de CR-05 o CR-06 formulado como alerta completa sin regla relacional.
8. Modificación de texto que sobrescriba una variante previa.
9. Corrida experimental sin modelo, dataset, umbrales o configuración de preprocesamiento.
10. Métricas calculadas sin ground truth suficiente.
11. Prompts auxiliares usados como evidencia principal sin estar declarados.
12. Salidas perceptivas sin trazabilidad hacia `prompt_id`, `condition_id` y `vocabulary_id`.

## 11. Criterios de aceptación

La tarea se considera correctamente resuelta cuando existan:

1. Documento de investigación sobre papers y proyectos relevantes.
2. Diseño del módulo de prompts.
3. Catálogo inicial versionado.
4. Constructor de vocabulario activo.
5. Esquema de estrategias de prompts.
6. Adaptador base para modelos OVD.
7. Al menos un adaptador mock funcional.
8. Pipeline de matriz experimental.
9. Métricas por prompt y por condición.
10. Exportación reproducible de resultados.
11. Tests unitarios de validación del catálogo.
12. Tests de construcción de vocabulario aislado y completo.
13. Tests de trazabilidad entre prompt, condición, vocabulario y evento perceptivo.
14. Documentación clara para agregar nuevos prompts, modelos y estrategias.
15. Integración preparada para producir `PerceptionEvent`.

## 12. Prioridades de implementación

### Fase 1 — Investigación y diseño

* Inspeccionar el repositorio.
* Leer arquitectura existente.
* Identificar contratos actuales.
* Redactar `prompt_module_research.md`.
* Redactar `prompt_module_design.md`.

### Fase 2 — Catálogo y configuración

* Implementar schemas.
* Implementar catálogo YAML/JSON.
* Implementar validadores.
* Implementar versionado de variantes.
* Implementar vocabulario activo.

### Fase 3 — Adaptadores

* Implementar interfaz base.
* Implementar adaptador mock.
* Diseñar adaptadores para Grounding DINO, YOLOE, YOLO-World, OWL-ViT y Florence-2.
* No forzar integración real si todavía no existe runtime de modelos.

### Fase 4 — Evaluación experimental

* Implementar matriz experimental.
* Ejecutar sobre resultados mock o sobre detecciones existentes si el repositorio ya las tiene.
* Calcular métricas.
* Exportar reportes.

### Fase 5 — Integración

* Conectar el módulo con `RunConfig`.
* Asegurar que la salida pueda mapearse a `PerceptionEvent`.
* Mantener separación con motor de patrones y alertas.

## 13. Decisiones de diseño no negociables

> ✅ **TOMADO.** Inglés primario, vocabulario declarado por corrida, prompt≠alerta,
> detección≠patrón, evidencia trazable, diseño desacoplado del modelo OVD. Matiz: "comparar
> prompt aislado vs vocabulario completo" se logra con **sets + `active_ids`**, no con un runner
> interno; "toda variante versionada" se cumple por **archivos en git**.

* Los prompts primarios deben estar en inglés.
* Toda variante debe ser versionada.
* El vocabulario activo debe declararse por corrida.
* El módulo debe comparar prompt aislado vs prompt en vocabulario completo.
* CR-01 y CR-02 son el núcleo obligatorio.
* CR-03 y CR-04 son exploratorias o condicionadas.
* CR-05 y CR-06 deben resolverse mediante entidades componentes más reglas externas.
* Un prompt no es una alerta.
* Una detección no confirma por sí sola un patrón.
* La evidencia perceptiva debe ser trazable.
* El diseño debe ser modular y desacoplado del modelo OVD específico.
* El módulo debe permitir investigación experimental, no solo configuración estática.
* El resultado debe ser reproducible por corrida.

## 14. Resultado esperado final

Entregar un módulo que permita responder experimentalmente preguntas como:

* ¿Qué prompt funciona mejor para detectar persona sin casco?
* ¿La formulación directa supera a la indirecta?
* ¿Un template tipo CLIP mejora o empeora el resultado?
* ¿Un vocabulario completo degrada el desempeño frente a una evaluación aislada?
* ¿Qué modelo es más sensible a cambios de redacción?
* ¿Qué prompts son más robustos frente a hard negatives?
* ¿Qué costo de latencia introduce aumentar el vocabulario activo?
* ¿Qué configuración de prompts debe quedar como primaria para el núcleo validable?

El objetivo final no es encontrar “el prompt perfecto”, sino construir una capa experimental que permita medir, comparar, justificar y congelar prompts de forma trazable dentro del prototipo E-OVRT-VDP.