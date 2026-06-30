# Diseño — Capa de declaración y consumo de prompts del Media Plane

**Fecha:** 2026-06-25
**Estado:** Propuesto (pendiente de aprobación)
**Ámbito:** `e-ovrt_media-plane` — capa de prompts (declaración YAML, esquema, resolución y consumo por adaptador)
**Orientación:** ejecuciones **experimentales** (no productivo). Prioriza claridad, reproducibilidad y exploración de fraseo, no robustez operacional.

---

## 1. Problema y motivación

La capa de prompts actual tiene tres deficiencias para el trabajo experimental:

1. **Un único texto para ambas arquitecturas.** `config.get_prompt_texts()` devuelve un `list[str]`
   plano e idéntico que se pasa tanto a Grounding DINO (GDINO) como a YOLOE. Pero las dos
   arquitecturas procesan prompts de forma distinta:
   - **GDINO** (grounding por *caption*): une los textos en `"person. helmet. vest."` y hace
     matching de sub-spans. Rinde mejor con frases descriptivas y admite sinónimos en el caption.
   - **YOLOE** (embedding de texto tipo CLIP): `set_classes(prompts)` tokeniza y calcula
     *prompt embeddings*; rinde mejor con etiquetas cortas. El `class_id` devuelto es el índice
     en la lista pasada.

   Forzar el mismo texto impide optimizar por arquitectura.

2. **Binding frágil a la clase canónica.** El campo `prompt_id` de `RawDetection`/`Detection`
   **nunca se rellena** por los adaptadores. GDINO recupera el prompt con un heurístico de
   solapamiento de palabras (`_normalize_label`, frágil), y luego `DetectionNormalizer`
   (`detection_normalizer.py:87-96`) re-mapea por texto/`aliases` con match exacto. Doble
   indirección, y `aliases` está declarado pero ningún adaptador lo usa. Resultado: la alineación
   de detecciones con el vocabulario `canonical_v2` (person/helmet/vest/bare_head) que necesita
   el BENCH no es determinista.

3. **Cruft de esquema.** `PromptsFile` soporta dos formatos (`prompt_set` nuevo + legacy
   `version`+`items`), duplicando caminos de validación y test.

## 2. Objetivos / No-objetivos

**Objetivos**
- Esquema de prompts único y canónico con **fraseo por backend** y **múltiples frases por clase**.
- **Binding por construcción** (sin heurísticos) entre la salida del modelo y la clase canónica.
- Un solo *prompt set* sirve óptimamente a GDINO y YOLOE (sin duplicar archivos por modelo).
- Reproducibilidad: las corridas BENCH existentes alimentan exactamente las mismas frases.

**No-objetivos** (YAGNI para experimental)
- No se añaden reglas de riesgo, scoring, ni lógica de control.
- No se versiona/serializa el plan más allá de la provenance (`resolved_prompts`) que ya existe.
- No se mantiene compatibilidad con el formato legacy (corte limpio).
- No hay override de fraseo por-corrida; el A/B de estrategias se hace con archivos alternativos.
- **No prompt-learning** (CoOp/CoCoOp/DetPro): requieren re-entrenar y los prompts aprendidos
  estáticos generalizan peor que templates manuales en vocabulario abierto
  (`docs/research/prompt_module_research.md` §2.2). Se hace prompt engineering manual.
- **No métricas/runner internos** (NMS-AP, matriz experimental): la evaluación vive en el repo
  `e-ovrt_datasets` (`evaluate_bench.py`) + `compare-runs`. La capa de prompts solo emite
  provenance trazable.
- **No negation-aware / resolución de ausencia** en esta capa: es del plano de control (§3.1).

> **Fundamento de investigación.** Las decisiones de fraseo, ausencia, hard negatives y caché de
> vocabulario están respaldadas por `docs/research/prompt_module_research.md` (barrido de
> CoOp/DetPro/FG-OVD/OVDEval/CLIP/GDINO/YOLO-World/YOLOE/OWL-ViT/Florence-2). Verificación
> parcial: la síntesis se cortó por presupuesto; varios hallazgos están marcados **[LIT]** (a
> re-confirmar). No cambian el diseño, lo refuerzan.

### 2.1 Justificación open-vocabulary

Esta capa **depende** de OVD; no es un detector cerrado con otra fachada. Lo que un modelo
fine-tuned cerrado (cabeza fija de N clases) no da y este diseño sí:

- **Zero-shot, sin datos de entrenamiento.** El detector de `person/helmet/vest/bare_head`
  existe sin un solo ejemplo etiquetado (Sprint 2 evaluó 5 modelos zero-shot). Un modelo cerrado
  exige relabel + reentrenar para llegar a esas mismas clases.
- **Vocabulario portable entre arquitecturas.** Un mismo prompt set alimenta GDINO, MM-GDINO y
  YOLOE vía el adaptador; cambiar de modelo no requiere reentrenar ni una cabeza nueva. El
  **fraseo por backend** (§3) es justamente la adaptación de ese vocabulario a cada arquitectura.
- **Extensión declarativa del vocabulario.** Agregar `gloves` o `safety glasses` es editar YAML,
  no reentrenar.
- **El fraseo como variable experimental.** Sets alternativos (`*_bench_v2.yaml` congelado vs
  `ppe_v2_descriptive.yaml`) permiten A/B de distintas conceptualizaciones del mismo riesgo sin
  tocar pesos ni código — el objeto de estudio del proyecto.

| Capacidad                          | Modelo cerrado (fine-tuned)            | Esta capa (OVD)                          |
|------------------------------------|----------------------------------------|------------------------------------------|
| Puesta en marcha                   | Dataset etiquetado + entrenamiento     | Zero-shot, sin entrenamiento             |
| Cambiar de arquitectura            | Reentrenar cabeza nueva                | Mismo set, otro adaptador                |
| Cambiar / añadir frases            | Reentrenar                             | Editar YAML                              |
| Añadir clase nueva                 | Relabel + reentrenar                   | Editar YAML                              |
| Fraseo como variable de estudio    | No existe                              | Sets alternativos (A/B)                  |
| Vocabulario en evaluación          | Fijo (codificado en los pesos)         | Proyectado a `canonical_v2` (medición)   |
| Salida cruda del modelo            | N/A                                    | Preservada en `source_prompt`            |

La diferencia operativa frente a un detector cerrado **no** está en la columna de evaluación
(ambos terminan en clases fijas), sino en que aquí se llega ahí sin entrenar, con cualquier
arquitectura y reconfigurable por YAML.

**El binding a `canonical_v2` no cierra el vocabulario; es una proyección de medición.** Calcular
AP contra un BENCH de clases fijas obliga a proyectar las detecciones sobre el esquema de GT —
cualquier evaluación OVD lo hace. La apertura vive en la *entrada* (frases, clases activas,
modelo), que se preserva. Además, `source_prompt` (§7) conserva la frase literal que matcheó el
modelo aun en corridas ligadas, de modo que la salida cruda open-vocabulary no se pierde.

**Modo exploración/discovery: no requiere mecanismo nuevo.** Basta un set cuyos `id` sean los
conceptos a sondear (`canonical` hereda de `id` por defecto, §3); esas corridas no se evalúan
contra el BENCH (o usan otro GT). Por eso **no** se añade un modo `canonical: null`: sería
redundante con la convención anterior, y `source_prompt` ya preserva la salida cruda. (Si en el
futuro se quisiera semántica de discovery explícita y autodocumentada en sets mixtos, ese sería
el lugar para reconsiderarlo — hoy es YAGNI, §2.)

## 3. Esquema canónico único

> **Enmienda (2026-06-27).** Los prompt sets se relocalizan al repo externo
> `e-ovrt_experimental-setup/prompts/<set>.yaml` y `prompts.ref` resuelve contra la raíz del
> experimento, no contra `configs/`. El **esquema, el `build_plan`, los adaptadores y el binding
> no cambian** — solo la ubicación del archivo y la raíz de resolución. Ver
> `2026-06-27-experimental-setup-config-design.md` §5 y §7.

Archivo `experimental-setup/prompts/<set>.yaml` (antes `configs/prompts/<set>.yaml`), formato único:

```yaml
prompt_set:
  id: ppe_v2
  description: "..."
  language: en
  classes:
    - id: helmet                 # identidad estable del prompt -> prompt_id
      canonical: helmet          # clase de evaluación (canonical_v2); opcional, default = id
      role: ppe                  # metadato semántico (entity | ppe | visual_risk_indicator)
      strategy: positive_evidence  # metadato opcional; etiqueta, NO lógica (ver §3.1)
      condition_id: CR-01        # metadato opcional de trazabilidad (CR-01..06)
      enabled_by_default: true
      phrasings:
        default: ["helmet"]      # fallback para cualquier backend sin entrada propia
        gdino:   ["hard hat", "safety helmet"]   # sinónimos descriptivos cortos; acotar long. de caption
        yoloe:   ["helmet"]      # frases nominales cortas; varias frases = ensembling
    - id: bare_head
      canonical: bare_head
      role: visual_risk_indicator
      enabled_by_default: true
      phrasings:
        default: ["bare head"]
```

**Reglas de resolución**
- `id`: único dentro del set. Se propaga como `Detection.prompt_id`.
- `canonical`: clase del vocabulario de evaluación. Default = `id`. Se propaga como `Detection.label`.
  Esto alinea las detecciones con `canonical_v2` de forma determinista (clave para el BENCH).
- `phrasings`: dict `backend -> list[str]`. Cadena de fallback: `phrasings[backend]` →
  `phrasings["default"]`. Si no existe ninguno de los dos para una clase activa, error de validación.
- `role`, `enabled_by_default`: igual que hoy.
- `strategy`, `condition_id`: **metadatos opcionales** (default `None`). Ver §3.1.

### 3.1 Metadatos `strategy` y `condition_id` (etiqueta, no lógica)

Ambos campos son **solo provenance/trazabilidad**: la capa de prompts los propaga al
`detections.jsonl` (vía `PromptPhrase` → `Detection`) pero **no ramifica ninguna lógica sobre
ellos**. La lógica que los consume (resolver ausencia, agrupar por condición de riesgo) vive en
el **plano de control**, fuera del media-plane.

- `strategy` (str | None): etiqueta de la estrategia de fraseo, p.ej. `positive_evidence`
  (detectar el EPP/entidad presente), `direct_absence` (prompt negado "person without helmet"),
  `template` ("a photo of a hard hat"), `auxiliary_diagnostic`. Valor libre validado como string;
  **no** es un enum cerrado (experimental). *Nota de evidencia:* la investigación (ver
  `docs/research/prompt_module_research.md` §2.3) muestra que los OVD tienen **sesgo afirmativo**
  e ignoran la negación, por lo que `positive_evidence` es la estrategia primaria y
  `direct_absence` queda como variante diagnóstica.
- `condition_id` (str | None): trazabilidad a la condición de riesgo (CR-01..CR-06). El esquema
  **no** se estructura por condición (el proyecto usa `canonical_v2`); es un tag opcional.

**Eliminado**: formato legacy (`version`+`items` top-level), campo `PromptItem.text`, campo
`PromptItem.aliases`. El validador dual-format de `PromptsFile` se elimina.

### Modelos Pydantic (`config/schemas.py`)

```python
class PromptClass(BaseModel):
    id: str
    canonical: str | None = None            # default -> id (resuelto en validator)
    role: str | None = None
    strategy: str | None = None             # metadato/provenance; etiqueta, no lógica (§3.1)
    condition_id: str | None = None         # metadato/provenance de trazabilidad (§3.1)
    enabled_by_default: bool = True
    phrasings: dict[str, list[str]]         # backend -> frases; requiere "default" o el backend pedido

class PromptSet(BaseModel):
    id: str
    description: str | None = None
    language: str | None = None
    classes: list[PromptClass]

class PromptsFile(BaseModel):
    prompt_set: PromptSet
    # API:
    def resolved_set_id(self) -> str
    def get_active_classes(self, active_ids: list[str] | None) -> list[PromptClass]
    def build_plan(self, backend: str, active_ids: list[str] | None) -> PromptPlan
```

`get_active_classes` mantiene la semántica actual: `active_ids=None` → clases con
`enabled_by_default=true`; lista → ese subconjunto en orden, error si un id no existe.

## 4. Estructura resuelta de consumo: `PromptPlan`

Nuevo módulo `config/prompt_plan.py` (o junto a schemas). Reemplaza el `list[str]` plano:

```python
@dataclass(frozen=True)
class PromptPhrase:
    index: int                    # posición en la lista aplanada == class_id de YOLOE
    text: str                     # frase alimentada al modelo, p.ej. "hard hat"
    prompt_id: str                # "helmet"
    canonical: str                # "helmet"
    strategy: str | None = None   # metadato propagado a Detection (provenance)
    condition_id: str | None = None  # metadato propagado a Detection (provenance)

@dataclass(frozen=True)
class PromptPlan:
    set_id: str
    backend: str
    phrases: tuple[PromptPhrase, ...]          # aplanado y ordenado (incluye sinónimos)

    def texts(self) -> list[str]               # [p.text for p in phrases] -> entrada al modelo
    def by_index(self) -> list[PromptPhrase]    # resolución O(1) por class_id (YOLOE)
    def by_text(self) -> dict[str, PromptPhrase] # resolución por texto exacto (GDINO)
```

**Construcción** (`PromptsFile.build_plan(backend, active_ids)`):
1. Resolver clases activas con `get_active_classes(active_ids)`.
2. Para cada clase, tomar `phrasings[backend]` o `phrasings["default"]`.
3. Aplanar a una lista ordenada de `PromptPhrase`, asignando `index` incremental; cada frase
   guarda el `prompt_id` (=`class.id`), `canonical` (=`class.canonical or class.id`) y los
   metadatos `strategy`/`condition_id` de la clase (provenance).
4. Si dos frases iguales colisionan (mismo texto de dos clases distintas) → error de validación
   (evita ambigüedad de binding).

**API de `RunConfig`** (reemplaza `get_prompt_texts`/`get_prompt_items`):
```python
def build_prompt_plan(self, backend: str) -> PromptPlan
def get_active_classes(self) -> list[PromptClass]   # metadata para artefactos
```

## 5. Backend del adaptador

Cada adaptador declara su clave de fraseo como atributo de clase:

| Familia / adaptador        | `PROMPT_BACKEND` |
|----------------------------|------------------|
| `grounding_dino`           | `"gdino"`        |
| `yoloe`                    | `"yoloe"`        |
| `mock`                     | `"default"`      |

> **Nota (verificado en `models/__init__.py:create_adapter`).** Solo existen **3 clases** de
> adaptador: `GroundingDinoHFAdapter`, `YOLOEUltralyticsAdapter`, `MockDetectorAdapter`. **No hay
> clase MM-GDINO**: los modelos MM-Grounding-DINO corren por el adaptador `grounding_dino` (mismo
> backend `"gdino"`), seleccionados vía `model.adapter`/`model.name`. El `PROMPT_BACKEND` es atributo
> de la **clase**, así que MM-GDINO hereda `"gdino"` automáticamente.

El pipeline construye el plan con la clave del adaptador instanciado:
`plan = config.build_prompt_plan(adapter.PROMPT_BACKEND)`.

## 6. Binding por construcción (en el adaptador)

Se cambia la firma de `BaseDetectorAdapter`:

```python
def predict(self, image, plan: PromptPlan) -> list[RawDetection]
def forward(self, unit: NormalizedUnit, plan: PromptPlan) -> list[RawDetection]
```

Cada adaptador devuelve `RawDetection` ya ligado, copiando los campos de la `PromptPhrase`:
`RawDetection(label=<canonical>, prompt_id=<id>, source_prompt=<frase exacta>, strategy=<phrase.strategy>, condition_id=<phrase.condition_id>, score=..., box_xyxy=...)`.

**YOLOE** (`yoloe_adapter.py`)
- `set_classes(plan.texts())`. El `class_id` devuelto es índice directo: `plan.by_index()[class_id]`
  → `prompt_id`/`canonical` **exactos**. Sin matching difuso.
- Sinónimos: varias frases → varios `index` que colapsan al mismo `canonical`.
- El caché `_prompts_set` se compara contra `plan.texts()` (igual que hoy, pero desde el plan).

**GDINO** (`grounding_dino_adapter.py`)
- Caption = `". ".join(plan.texts()) + "."`.
- El `text_labels`/span devuelto se resuelve contra `plan.by_text()`:
  exacto → substring contenido → (último recurso) solapamiento de palabras, pero el resultado
  siempre se mapea a `(prompt_id, canonical)` del plan, no a un string suelto.
- El heurístico `_normalize_label` actual se conserva **solo** como desempate final dentro de la
  resolución contra el plan.
- Si **ninguna** vía resuelve el span contra el plan, la detección se **descarta** y se registra en
  `errors.jsonl` (no se emite un binding nulo): preserva el determinismo del vocabulario de salida.

**Mock** (`mock_detector.py`)
- Usa `plan.texts()` como universo de etiquetas y devuelve `RawDetection` con `prompt_id`/`canonical`
  del plan (binding trivial). Mantiene los tests end-to-end sin pesos reales.

**`DetectionNormalizer`** (`detection_normalizer.py`)
- Se **simplifica**: elimina el bloque de matching `label→prompt_id` por `text`/`aliases`
  (líneas 87-96). Confía en el binding del adaptador (`raw.prompt_id`, `raw.label=canonical`).
  Su responsabilidad queda en: filtro de confianza, filtro de área, reproyección de caja y
  normalización de coordenadas. Ya no recibe `prompt_items`.

## 7. Contratos (`contracts/detection.py`)

`RawDetection`: se aclara la semántica de campos ya existentes y se añaden los dos metadatos:
- `label` = clase **canónica** (no el texto crudo del modelo).
- `prompt_id` = id de la clase en el set (ahora **sí** lo rellenan los adaptadores).
- `source_prompt` = frase exacta que matcheó el modelo (provenance/debug).
- **(nuevos)** `strategy: str | None`, `condition_id: str | None`: copiados por el adaptador
  desde la `PromptPhrase` ligada en el momento del binding.

`Detection`: `label`=canonical, `prompt_id`=id. **Se añaden** los mismos dos campos opcionales
`strategy`/`condition_id`, que el normalizer **copia tal cual** desde `RawDetection` (sin
re-derivar). Permiten que el plano de control filtre/agrupe por estrategia o condición. El resto
de campos no cambia; cambia quién los puebla y su significado (ahora determinista).

## 8. Flujo de datos (resumen)

```
prompts.ref ─► loader ─► PromptsFile(prompt_set)
                              │
runtime: adapter = create_adapter(model)
         plan = config.build_prompt_plan(adapter.PROMPT_BACKEND)   # per-backend
                              │
         raw = adapter.forward(unit, plan)    # binding por construcción
                              │  RawDetection(label=canonical, prompt_id=id, source_prompt=frase)
         dets = normalizer.normalize(raw, w, h, model_name, transform)   # solo filtra+normaliza
                              │
         RunArtifactWriter ─► detections.jsonl (label canónico, prompt_id estable)
```

## 9. Migración (corte limpio)

1. **Esquema** (`config/schemas.py`): nuevos `PromptClass`/`PromptSet`/`PromptsFile`; borrar
   dual-format, `text`, `aliases`. Nuevo `config/prompt_plan.py`.
2. **`RunConfig`**: `get_prompt_texts`/`get_prompt_items` → `build_prompt_plan(backend)` +
   `get_active_classes()`. `to_effective_dict.resolved_prompts` pasa a registrar las frases del
   plan de la corrida (provenance por backend).
3. **Archivos de prompts** (aterrizan en `e-ovrt_experimental-setup/prompts/`, no en el media-plane;
   ver `2026-06-27-experimental-setup-config-design.md` §7-§8):
   a. Migrar `cr01_cr02_v2_short.yaml` y `cr01_cr02_bench_v2.yaml` al formato nuevo
      **preservando las frases exactas actuales** como `phrasings.default` (una frase por clase).
      El BENCH congelado alimenta texto byte-equivalente → reproducibilidad intacta.
   b. **Crear `ppe_v2_descriptive.yaml`** (set *nuevo*, no congelado): mismas clases canónicas,
      con `phrasings.gdino` enriquecido con sinónimos descriptivos cortos (p.ej. helmet →
      `["hard hat", "safety helmet"]`; vest → `["reflective vest", "high-visibility vest"]`) y
      `phrasings.yoloe` con etiquetas/nominales cortas (varias frases = ensembling). Sirve para
      A/B contra el BENCH congelado. **No** se enriquecen los sets congelados (riesgo §11).
4. **Adaptadores**: `base.py` (firma), `grounding_dino_adapter.py`, `yoloe_adapter.py`,
   `mock_detector.py` (binding por construcción + `PROMPT_BACKEND`).
5. **Pipeline**: `runtime/pipeline.py` y `runtime/two_node.py` construyen el plan por backend y
   ajustan la llamada a `normalize()` (sin `prompt_items`).
6. **Normalizer**: simplificación descrita en §6.
7. **Contratos** (`contracts/detection.py`): añadir `strategy`/`condition_id` opcionales a
   `Detection` (y que el normalizer los copie desde la `PromptPhrase`/`RawDetection`). El
   `RunArtifactWriter` los serializa en `detections.jsonl` si están presentes.
8. **Run configs**: **sin cambios** — la interfaz de declaración (`prompts.ref`/`active_ids`) se
   mantiene. (Verificar en el plan todos los configs que referencian los sets migrados: raíz de
   `configs/runs/`, `experiments/bench_v2/` y `local/`; el conteo exacto se resuelve ahí.)
9. **Tests** y **docs** (§10).

## 10. Testing

- `schemas`: parseo del formato nuevo; default `canonical`=`id`; `strategy`/`condition_id`
  opcionales (default `None`); fallback `phrasings`; error si falta `default` y backend; error de
  id inexistente en `active_ids`.
- `prompt_plan`: aplanado e índices correctos; colapso de sinónimos al mismo canonical; colisión
  de texto duplicado → error; `strategy`/`condition_id` se propagan a cada `PromptPhrase`.
- `loader`: `prompts.ref` → archivo nuevo; rechazo del formato legacy.
- `yoloe_adapter`: `class_id → canonical` exacto vía `by_index`; cambio de plan re-ejecuta
  `set_classes`. (con `MockDetector`/stubs donde aplique).
- `grounding_dino_adapter`: construcción del caption desde `plan.texts()`; resolución de span a
  canonical vía `by_text`; desempate por solapamiento; span no resuelto → descartado + log (sin
  binding nulo).
- `detection_normalizer`: ya no mapea ids (test de que respeta `raw.prompt_id`); filtros intactos.
- End-to-end con `MockDetector`: `detections.jsonl` con `label` canónico, `prompt_id` poblado y
  `strategy`/`condition_id` presentes cuando el set los declara.
- `make test` (pytest) y `make lint` (ruff) en verde.

## 11. Riesgos

- **Cambio de firma de `BaseDetectorAdapter`** propaga a las **3 clases** de adaptador
  (`grounding_dino`, `yoloe`, `mock`) + los call sites del runtime (`pipeline.py:170`, compartido por
  single-host y two-node vía `two_node.py`). Mitigación: cambio mecánico y cubierto por tests
  existentes adaptados.
- **GDINO con sinónimos en el caption**: captions más largos pueden cambiar el comportamiento de
  matching y diluir el grounding (sensibilidad a longitud, ver investigación §2.1/§2.6).
  Mitigación: los sets *congelados* (BENCH) no añaden sinónimos; en `ppe_v2_descriptive.yaml` se
  **acota el nº de frases activas** y se vigila la longitud del caption (no sinónimos ilimitados).
- **Atributos finos (helmet/vest/bare_head) + hard negatives**: el desempeño cae al agregar
  distractores semánticamente cercanos (FG-OVD, investigación §2.4). No es un riesgo del diseño
  de la capa, pero condiciona la **evaluación**: medir con/sin negativos (en el repo `datasets`).
- **Reproducibilidad del BENCH**: garantizada porque las frases migradas son idénticas a las
  actuales (`phrasings.default` = `text` actual).
