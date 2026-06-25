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

## 3. Esquema canónico único

Archivo `configs/prompts/<set>.yaml`, formato único:

```yaml
prompt_set:
  id: ppe_v2
  description: "..."
  language: en
  classes:
    - id: helmet                 # identidad estable del prompt -> prompt_id
      canonical: helmet          # clase de evaluación (canonical_v2); opcional, default = id
      role: ppe                  # metadato semántico (entity | ppe | visual_risk_indicator)
      enabled_by_default: true
      phrasings:
        default: ["helmet"]      # fallback para cualquier backend sin entrada propia
        gdino:   ["hard hat", "safety helmet"]
        yoloe:   ["helmet"]
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

**Eliminado**: formato legacy (`version`+`items` top-level), campo `PromptItem.text`, campo
`PromptItem.aliases`. El validador dual-format de `PromptsFile` se elimina.

### Modelos Pydantic (`config/schemas.py`)

```python
class PromptClass(BaseModel):
    id: str
    canonical: str | None = None            # default -> id (resuelto en validator)
    role: str | None = None
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
    index: int        # posición en la lista aplanada == class_id de YOLOE
    text: str         # frase alimentada al modelo, p.ej. "hard hat"
    prompt_id: str    # "helmet"
    canonical: str    # "helmet"

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
   guarda el `prompt_id` (=`class.id`) y `canonical` (=`class.canonical or class.id`).
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
| `mm_grounding_dino`        | `"gdino"`        |
| `yoloe`                    | `"yoloe"`        |
| `mock`                     | `"default"`      |

El pipeline construye el plan con la clave del adaptador instanciado:
`plan = config.build_prompt_plan(adapter.PROMPT_BACKEND)`.

## 6. Binding por construcción (en el adaptador)

Se cambia la firma de `BaseDetectorAdapter`:

```python
def predict(self, image, plan: PromptPlan) -> list[RawDetection]
def forward(self, unit: NormalizedUnit, plan: PromptPlan) -> list[RawDetection]
```

Cada adaptador devuelve `RawDetection` ya ligado:
`RawDetection(label=<canonical>, prompt_id=<id>, source_prompt=<frase exacta matcheada>, score=..., box_xyxy=...)`.

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

**Mock** (`mock_detector.py`)
- Usa `plan.texts()` como universo de etiquetas y devuelve `RawDetection` con `prompt_id`/`canonical`
  del plan (binding trivial). Mantiene los tests end-to-end sin pesos reales.

**`DetectionNormalizer`** (`detection_normalizer.py`)
- Se **simplifica**: elimina el bloque de matching `label→prompt_id` por `text`/`aliases`
  (líneas 87-96). Confía en el binding del adaptador (`raw.prompt_id`, `raw.label=canonical`).
  Su responsabilidad queda en: filtro de confianza, filtro de área, reproyección de caja y
  normalización de coordenadas. Ya no recibe `prompt_items`.

## 7. Contratos (`contracts/detection.py`)

`RawDetection`: se conserva la estructura; se aclara la semántica de campos ya existentes:
- `label` = clase **canónica** (no el texto crudo del modelo).
- `prompt_id` = id de la clase en el set (ahora **sí** lo rellenan los adaptadores).
- `source_prompt` = frase exacta que matcheó el modelo (provenance/debug).

`Detection`: `label`=canonical, `prompt_id`=id. Sin cambios de campos; cambia solo quién los puebla
y su significado (ahora determinista).

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
3. **Archivos de prompts**: migrar `cr01_cr02_v2_short.yaml` y `cr01_cr02_bench_v2.yaml` al formato
   nuevo **preservando las frases exactas actuales** como `phrasings.default` (una frase por clase).
   El BENCH congelado alimenta texto byte-equivalente → reproducibilidad intacta. (Opcionalmente se
   pueden enriquecer las frases `gdino` en un set *nuevo*, no en el congelado.)
4. **Adaptadores**: `base.py` (firma), `grounding_dino_adapter.py`, `yoloe_adapter.py`,
   `mock_detector.py` (binding por construcción + `PROMPT_BACKEND`).
5. **Pipeline**: `runtime/pipeline.py` y `runtime/two_node.py` construyen el plan por backend y
   ajustan la llamada a `normalize()` (sin `prompt_items`).
6. **Normalizer**: simplificación descrita en §6.
7. **Run configs**: **sin cambios** — la interfaz de declaración (`prompts.ref`/`active_ids`) se
   mantiene. (Verificar los ~24 configs que referencian los dos sets migrados.)
8. **Tests** y **docs** (§10).

## 10. Testing

- `schemas`: parseo del formato nuevo; default `canonical`=`id`; fallback `phrasings`; error si
  falta `default` y backend; error de id inexistente en `active_ids`.
- `prompt_plan`: aplanado e índices correctos; colapso de sinónimos al mismo canonical; colisión
  de texto duplicado → error.
- `loader`: `prompts.ref` → archivo nuevo; rechazo del formato legacy.
- `yoloe_adapter`: `class_id → canonical` exacto vía `by_index`; cambio de plan re-ejecuta
  `set_classes`. (con `MockDetector`/stubs donde aplique).
- `grounding_dino_adapter`: construcción del caption desde `plan.texts()`; resolución de span a
  canonical vía `by_text`; desempate por solapamiento.
- `detection_normalizer`: ya no mapea ids (test de que respeta `raw.prompt_id`); filtros intactos.
- End-to-end con `MockDetector`: `detections.jsonl` con `label` canónico y `prompt_id` poblado.
- `make test` (pytest) y `make lint` (ruff) en verde.

## 11. Riesgos

- **Cambio de firma de `BaseDetectorAdapter`** propaga a 3 adaptadores + mock + 2 call sites del
  runtime. Mitigación: cambio mecánico y cubierto por tests existentes adaptados.
- **GDINO con sinónimos en el caption**: captions más largos pueden cambiar el comportamiento de
  matching. Mitigación: los sets *congelados* (BENCH) no añaden sinónimos; solo sets nuevos.
- **Reproducibilidad del BENCH**: garantizada porque las frases migradas son idénticas a las
  actuales (`phrasings.default` = `text` actual).
