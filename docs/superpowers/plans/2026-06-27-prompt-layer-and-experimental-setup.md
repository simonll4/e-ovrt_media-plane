# Prompt Layer + Experimental-Setup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rediseñar la capa de prompts del media-plane (fraseo por backend, `PromptPlan`, binding por construcción) y relocalizar la declaración de experimentos (prompt sets + run configs) al repo hermano `e-ovrt_experimental-setup`, con resolución de referencias de dos raíces.

**Architecture:** Dos fases. **Fase A** (interna al media-plane): un esquema de prompts único con `phrasings` por backend, una estructura resuelta `PromptPlan` que cada adaptador consume para ligar detecciones por construcción (sin heurísticos frágiles), y un `DetectionNormalizer` simplificado. **Fase B** (relocalización): el loader resuelve refs del plano (`model`/`source`) contra el catálogo del media-plane y refs del experimento (`prompts`) contra la raíz del repo de experimentos; los prompt sets y manifiestos se mudan a `e-ovrt_experimental-setup`; el test suite del plano queda self-contained con fixtures locales.

**Tech Stack:** Python 3.11, Pydantic v2, dataclasses, pytest, ruff, typer (CLI), PyYAML.

## Global Constraints

- **Specs fuente:** `docs/superpowers/specs/2026-06-25-prompt-layer-design.md` y `docs/superpowers/specs/2026-06-27-experimental-setup-config-design.md`. Ante conflicto, los specs mandan.
- **Corte limpio:** se elimina el formato legacy de prompts (`version`+`items`), los campos `PromptItem.text` y `PromptItem.aliases`, y el validador dual-format. No se mantiene compatibilidad hacia atrás del formato YAML.
- **Vocabulario canónico:** `canonical_v2` = `person`, `helmet`, `vest`, `bare_head`. Los `id` de las clases de prompt deben preservarse en la migración (los `active_ids` de los run configs los referencian).
- **Reproducibilidad BENCH:** las frases migradas de los sets congelados deben ser **byte-equivalentes** a los `text` actuales (una frase por clase en `phrasings.default`).
- **Sin commits automáticos:** el usuario ejecuta todos los commits. Los pasos "Commit" del plan indican el mensaje sugerido, pero **NO** se commitea sin pedido explícito del usuario. NO agregar trailer `Co-Authored-By`.
- **Verificación:** cada tarea cierra con `make test` (pytest -q) y `make lint` (ruff check src tests) en verde para los módulos tocados.
- **Tests sin pesos:** los adaptadores reales (GDINO/YOLOE) se testean con stubs; solo `MockDetector` corre end-to-end.

## File Structure

**Fase A — media-plane (`src/eovrt_media/`):**
- `config/prompt_plan.py` — **CREAR**. `PromptPhrase`, `PromptPlan`, helper `from_texts`.
- `config/schemas.py` — **MODIFICAR**. Reemplazar clases de prompt; `RunConfig` API; (Fase B) `ExperimentSection`.
- `config/loader.py` — **MODIFICAR**. `load_prompts_file` (formato nuevo); (Fase B) dos raíces.
- `config/__init__.py` — **MODIFICAR**. Exports (`PromptItem` deja de exportarse; agregar `PromptPlan`).
- `contracts/detection.py` — **MODIFICAR**. `strategy`/`condition_id` en `RawDetection` y `Detection`.
- `contracts/events.py` — **MODIFICAR** (Fase B). `experiment_id` en `RunSummary`.
- `models/base.py` — **MODIFICAR**. Firma `forward`/`predict` a `PromptPlan`; atributo `PROMPT_BACKEND`.
- `models/mock_detector.py`, `grounding_dino_adapter.py`, `yoloe_adapter.py` — **MODIFICAR**. Binding por construcción + `PROMPT_BACKEND`.
- `postprocessing/detection_normalizer.py` — **MODIFICAR**. Eliminar mapeo por `text`/`aliases`.
- `runtime/pipeline.py`, `runtime/two_node.py`, `runtime/two_node_local.py` — **MODIFICAR**. Construir plan por backend; ajustar firmas.

**Fase B — relocalización:**
- `cli.py` — **MODIFICAR**. Opción `--catalog-root`.
- `e-ovrt_experimental-setup/prompts/*.yaml` — **CREAR** (repo hermano, ya existe en `/home/simonll4/projects/`).
- `e-ovrt_experimental-setup/experiments/*.yaml` — **CREAR**.
- `tests/fixtures/prompts/test_ppe.yaml`, `tests/fixtures/runs/*.yaml` — **CREAR**.

---

# FASE A — Rediseño interno de la capa de prompts

## Task A1: Contratos — metadatos `strategy`/`condition_id`

**Files:**
- Modify: `src/eovrt_media/contracts/detection.py`
- Test: `tests/test_contracts_detection.py` (crear si no existe)

**Interfaces:**
- Produces: `RawDetection(..., strategy: str | None = None, condition_id: str | None = None)`; `Detection(..., strategy: str | None = None, condition_id: str | None = None)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_contracts_detection.py
from eovrt_media.contracts.detection import RawDetection, Detection


def test_raw_detection_carries_prompt_metadata():
    raw = RawDetection(
        label="helmet", score=0.9, box_xyxy=[0, 0, 10, 10],
        prompt_id="helmet", source_prompt="hard hat",
        strategy="positive_evidence", condition_id="CR-01",
    )
    assert raw.strategy == "positive_evidence"
    assert raw.condition_id == "CR-01"


def test_detection_metadata_defaults_none():
    det = Detection(label="helmet", confidence=0.9, bbox_xyxy=[0, 0, 10, 10], bbox_norm_xyxy=[0, 0, 1, 1])
    assert det.strategy is None
    assert det.condition_id is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_contracts_detection.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'strategy'`.

- [ ] **Step 3: Add the fields**

En `contracts/detection.py`, en el dataclass `RawDetection` (después de `prompt_id: str | None = None`, línea 17, antes de `raw`):

```python
    strategy: str | None = None
    condition_id: str | None = None
```

En el modelo `Detection` (después de `prompt_id: str | None = None`, línea 31):

```python
    strategy: str | None = None
    condition_id: str | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_contracts_detection.py -v`
Expected: PASS.

- [ ] **Step 5: Commit** (sugerido — esperar al usuario)

```
feat(contracts): add strategy/condition_id provenance fields to detections
```

---

## Task A2: Módulo `PromptPlan`

**Files:**
- Create: `src/eovrt_media/config/prompt_plan.py`
- Test: `tests/test_prompt_plan.py`

**Interfaces:**
- Produces:
  - `PromptPhrase(index: int, text: str, prompt_id: str, canonical: str, strategy: str | None = None, condition_id: str | None = None)` (frozen dataclass)
  - `PromptPlan(set_id: str, backend: str, phrases: tuple[PromptPhrase, ...])` (frozen dataclass) con `.texts() -> list[str]`, `.by_index() -> list[PromptPhrase]`, `.by_text() -> dict[str, PromptPhrase]`
  - `PromptPlan.from_texts(texts: list[str], backend: str = "default", set_id: str = "adhoc") -> PromptPlan` (classmethod; cada texto → frase con `prompt_id == canonical == text`; usado por warmup y tests)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_prompt_plan.py
from eovrt_media.config.prompt_plan import PromptPhrase, PromptPlan


def _plan():
    return PromptPlan(
        set_id="ppe_v2", backend="gdino",
        phrases=(
            PromptPhrase(0, "hard hat", "helmet", "helmet", "positive_evidence", "CR-01"),
            PromptPhrase(1, "safety helmet", "helmet", "helmet", "positive_evidence", "CR-01"),
            PromptPhrase(2, "person", "person", "person"),
        ),
    )


def test_texts_in_order():
    assert _plan().texts() == ["hard hat", "safety helmet", "person"]


def test_by_index_resolves_class_id():
    plan = _plan()
    assert plan.by_index()[1].canonical == "helmet"
    assert plan.by_index()[2].prompt_id == "person"


def test_by_text_exact_lookup():
    plan = _plan()
    assert plan.by_text()["safety helmet"].prompt_id == "helmet"


def test_synonyms_collapse_to_same_canonical():
    plan = _plan()
    assert plan.by_index()[0].canonical == plan.by_index()[1].canonical == "helmet"


def test_from_texts_helper():
    plan = PromptPlan.from_texts(["object"], backend="gdino")
    assert plan.texts() == ["object"]
    assert plan.by_index()[0].prompt_id == "object"
    assert plan.by_index()[0].canonical == "object"
    assert plan.backend == "gdino"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_prompt_plan.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'eovrt_media.config.prompt_plan'`.

- [ ] **Step 3: Implement the module**

```python
# src/eovrt_media/config/prompt_plan.py
"""Estructura resuelta de consumo de prompts: PromptPlan.

Reemplaza el `list[str]` plano que se pasaba a los adaptadores. Aplana las
frases de las clases activas (incluyendo sinónimos) en una lista ordenada,
donde el índice coincide con el `class_id` que devuelve YOLOE.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PromptPhrase:
    """Una frase concreta alimentada al modelo, ligada a su clase canónica."""

    index: int                       # posición en la lista aplanada == class_id de YOLOE
    text: str                        # frase alimentada al modelo, p.ej. "hard hat"
    prompt_id: str                   # id de la clase en el set, p.ej. "helmet"
    canonical: str                   # clase de evaluación (canonical_v2), p.ej. "helmet"
    strategy: str | None = None      # provenance: etiqueta de estrategia de fraseo
    condition_id: str | None = None  # provenance: condición de riesgo (CR-01..06)


@dataclass(frozen=True)
class PromptPlan:
    """Plan resuelto para un backend concreto."""

    set_id: str
    backend: str
    phrases: tuple[PromptPhrase, ...]

    def texts(self) -> list[str]:
        """Lista de frases en orden — entrada al modelo."""
        return [p.text for p in self.phrases]

    def by_index(self) -> list[PromptPhrase]:
        """Resolución O(1) por class_id (YOLOE devuelve el índice)."""
        return list(self.phrases)

    def by_text(self) -> dict[str, PromptPhrase]:
        """Resolución por texto exacto (GDINO devuelve spans de texto)."""
        return {p.text: p for p in self.phrases}

    @classmethod
    def from_texts(
        cls, texts: list[str], backend: str = "default", set_id: str = "adhoc"
    ) -> PromptPlan:
        """Construye un plan trivial desde textos sueltos (warmup, tests).

        Cada texto se vuelve su propia frase con prompt_id == canonical == text.
        """
        phrases = tuple(
            PromptPhrase(index=i, text=t, prompt_id=t, canonical=t)
            for i, t in enumerate(texts)
        )
        return cls(set_id=set_id, backend=backend, phrases=phrases)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_prompt_plan.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Lint + commit** (sugerido)

Run: `ruff check src/eovrt_media/config/prompt_plan.py tests/test_prompt_plan.py`

```
feat(config): add PromptPlan resolved-consumption structure
```

---

## Task A3: Flip núcleo — esquema nuevo, plan, mock, normalizer, pipeline

> Tarea grande pero coherente: cambia el esquema de prompts y conecta `PromptPlan` de punta a punta por el camino del `MockDetector`. Al cerrar, el suite end-to-end (mock) y los tests de schema/normalizer quedan en verde. GDINO/YOLOE se migran en A4/A5 (no se ejercitan en tests sin pesos).

**Files:**
- Modify: `src/eovrt_media/config/schemas.py` (clases de prompt + `RunConfig` API)
- Modify: `src/eovrt_media/config/loader.py:140-147` (`load_prompts_file`)
- Modify: `src/eovrt_media/config/__init__.py` (exports)
- Modify: `src/eovrt_media/models/base.py` (firma + `PROMPT_BACKEND`)
- Modify: `src/eovrt_media/models/mock_detector.py` (binding por construcción)
- Modify: `src/eovrt_media/postprocessing/detection_normalizer.py` (simplificación §6)
- Modify: `src/eovrt_media/runtime/pipeline.py` (construir plan + firmas)
- Modify: `src/eovrt_media/runtime/two_node.py`, `runtime/two_node_local.py` (mismo flip)
- Modify: `configs/prompts/cr01_cr02_v2_short.yaml`, `configs/prompts/cr01_cr02_bench_v2.yaml` (migrar a formato nuevo)
- Test: `tests/test_config.py`, `tests/test_pipeline_mock.py`, `tests/test_detection_normalizer.py` (crear/ajustar)

**Interfaces:**
- Consumes: `PromptPlan`, `PromptPhrase` (Task A2); campos de `RawDetection` (Task A1).
- Produces:
  - `PromptClass(id, canonical=None, role=None, strategy=None, condition_id=None, enabled_by_default=True, phrasings: dict[str, list[str]])` — validator pone `canonical = canonical or id`.
  - `PromptSet(id, description=None, language=None, classes: list[PromptClass])`
  - `PromptsFile(prompt_set: PromptSet)` con `resolved_set_id() -> str`, `get_active_classes(active_ids) -> list[PromptClass]`, `build_plan(backend, active_ids=None) -> PromptPlan`
  - `RunConfig.build_prompt_plan(backend: str) -> PromptPlan`, `RunConfig.get_active_classes() -> list[PromptClass]` (se eliminan `get_prompt_texts`/`get_prompt_items`)
  - `BaseDetectorAdapter.PROMPT_BACKEND: str = "default"`; `forward(unit, plan: PromptPlan)`, `predict(image, plan: PromptPlan)`

### Sub-bloque 1 — Esquema nuevo (schema-first, TDD)

- [ ] **Step 1: Write the failing schema test**

```python
# tests/test_config.py  (reemplazar la sección de prompts; conservar imports al inicio)
import pytest
from eovrt_media.config.schemas import PromptClass, PromptSet, PromptsFile


def _file():
    return PromptsFile(prompt_set=PromptSet(
        id="ppe_v2", language="en",
        classes=[
            PromptClass(id="helmet", role="ppe", strategy="positive_evidence",
                        condition_id="CR-01",
                        phrasings={"default": ["helmet"], "gdino": ["hard hat", "safety helmet"]}),
            PromptClass(id="bare_head", canonical="bare_head", role="visual_risk_indicator",
                        enabled_by_default=False, phrasings={"default": ["bare head"]}),
        ],
    ))


def test_canonical_defaults_to_id():
    assert _file().prompt_set.classes[0].canonical == "helmet"


def test_get_active_classes_default_only_enabled():
    active = _file().get_active_classes(None)
    assert [c.id for c in active] == ["helmet"]


def test_get_active_classes_explicit_order_and_unknown():
    f = _file()
    assert [c.id for c in f.get_active_classes(["bare_head", "helmet"])] == ["bare_head", "helmet"]
    with pytest.raises(ValueError):
        f.get_active_classes(["nope"])


def test_build_plan_gdino_flattens_synonyms():
    plan = _file().build_plan("gdino", active_ids=["helmet"])
    assert plan.texts() == ["hard hat", "safety helmet"]
    assert plan.by_index()[0].prompt_id == "helmet"
    assert plan.by_index()[0].strategy == "positive_evidence"
    assert plan.by_index()[0].condition_id == "CR-01"


def test_build_plan_falls_back_to_default():
    plan = _file().build_plan("yoloe", active_ids=["helmet"])
    assert plan.texts() == ["helmet"]   # no hay phrasings.yoloe → default


def test_build_plan_duplicate_text_errors():
    f = PromptsFile(prompt_set=PromptSet(id="x", classes=[
        PromptClass(id="a", phrasings={"default": ["dup"]}),
        PromptClass(id="b", phrasings={"default": ["dup"]}),
    ]))
    with pytest.raises(ValueError):
        f.build_plan("default")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -v -k "plan or canonical or active_classes"`
Expected: FAIL — `ImportError: cannot import name 'PromptClass'`.

- [ ] **Step 3: Replace the prompt schema classes**

En `config/schemas.py`, reemplazar **todo** el bloque `PromptItem`/`PromptSet`/`PromptsFile` (líneas 16-81) por:

```python
class PromptClass(BaseModel):
    """Una clase de prompt: identidad estable + fraseo por backend."""

    id: str
    canonical: str | None = None
    role: str | None = None
    strategy: str | None = None
    condition_id: str | None = None
    enabled_by_default: bool = True
    phrasings: dict[str, list[str]]

    @model_validator(mode="after")
    def default_canonical(self) -> PromptClass:
        if self.canonical is None:
            self.canonical = self.id
        return self


class PromptSet(BaseModel):
    """Conjunto canónico de clases de prompt."""

    id: str
    description: str | None = None
    language: str | None = None
    classes: list[PromptClass]


class PromptsFile(BaseModel):
    """Archivo de prompts — formato único (sin legacy)."""

    prompt_set: PromptSet

    def resolved_set_id(self) -> str:
        return self.prompt_set.id

    def get_active_classes(self, active_ids: list[str] | None) -> list[PromptClass]:
        all_classes = self.prompt_set.classes
        if active_ids is None:
            return [c for c in all_classes if c.enabled_by_default]
        by_id = {c.id: c for c in all_classes}
        result = []
        for pid in active_ids:
            if pid not in by_id:
                raise ValueError(f"Prompt ID '{pid}' no encontrado en el set.")
            result.append(by_id[pid])
        return result

    def build_plan(self, backend: str, active_ids: list[str] | None = None) -> PromptPlan:
        from eovrt_media.config.prompt_plan import PromptPhrase, PromptPlan

        phrases: list[PromptPhrase] = []
        seen: dict[str, str] = {}
        idx = 0
        for cls_ in self.get_active_classes(active_ids):
            texts = cls_.phrasings.get(backend) or cls_.phrasings.get("default")
            if not texts:
                raise ValueError(
                    f"Clase '{cls_.id}' no tiene phrasings['{backend}'] ni ['default']."
                )
            for text in texts:
                if text in seen:
                    raise ValueError(
                        f"Texto de prompt duplicado '{text}' (clases '{seen[text]}' y '{cls_.id}')."
                    )
                seen[text] = cls_.id
                phrases.append(PromptPhrase(
                    index=idx, text=text, prompt_id=cls_.id, canonical=cls_.canonical,
                    strategy=cls_.strategy, condition_id=cls_.condition_id,
                ))
                idx += 1
        return PromptPlan(set_id=self.resolved_set_id(), backend=backend, phrases=tuple(phrases))
```

- [ ] **Step 4: Update `RunConfig` API**

En `config/schemas.py`, reemplazar `get_prompt_texts` y `get_prompt_items` (líneas 348-358) por:

```python
    def build_prompt_plan(self, backend: str) -> PromptPlan:
        """Construye el PromptPlan resuelto para el backend del adaptador."""
        if self.prompts_file is None:
            raise RuntimeError("Archivo de prompts no cargado. Usar load_run_config().")
        return self.prompts_file.build_plan(backend, self.prompts.active_ids)

    def get_active_classes(self) -> list[PromptClass]:
        """Clases activas del set (metadata para artefactos/provenance)."""
        if self.prompts_file is None:
            raise RuntimeError("Archivo de prompts no cargado. Usar load_run_config().")
        return self.prompts_file.get_active_classes(self.prompts.active_ids)
```

Actualizar `to_effective_dict` (línea 360-365): reemplazar el bloque `resolved_prompts` por provenance backend-agnóstica:

```python
    def to_effective_dict(self) -> dict[str, Any]:
        data = self.model_dump(exclude={"prompts_file", "config_path"})
        if self.prompts_file:
            data["resolved_prompt_set"] = self.prompts_file.resolved_set_id()
            data["resolved_prompt_classes"] = [
                {"id": c.id, "canonical": c.canonical, "strategy": c.strategy,
                 "condition_id": c.condition_id}
                for c in self.get_active_classes()
            ]
        return data
```

Agregar el import de `PromptPlan` para los type hints, al inicio de `schemas.py` (después de la línea 8):

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from eovrt_media.config.prompt_plan import PromptPlan
```

(El `from __future__ import annotations` de la línea 3 ya permite anotar `-> PromptPlan` sin import en runtime; `build_plan` importa `PromptPlan` localmente.)

- [ ] **Step 5: Fix `load_prompts_file` and exports**

`config/loader.py:140-147` ya hace `PromptsFile(**raw)` — sigue válido (el YAML nuevo trae `prompt_set`). Sin cambios de código, pero verificar que no quede ninguna referencia a `PromptItem`.

En `config/__init__.py`: quitar `PromptItem` de imports/exports; agregar `PromptClass` y `PromptPlan`. Ejecutar:

Run: `grep -rn "PromptItem\|get_prompt_texts\|get_prompt_items\|get_active_texts\|get_active_items\|resolved_version" src/`
Expected (al final del sub-bloque): solo referencias ya migradas. Anotar cada hit para corregir en los pasos siguientes.

### Sub-bloque 2 — Adaptador base + Mock (binding por construcción)

- [ ] **Step 6: Update `BaseDetectorAdapter`**

En `models/base.py`: agregar el import bajo `TYPE_CHECKING` (línea 13-14):

```python
if TYPE_CHECKING:
    from eovrt_media.contracts.normalized_unit import NormalizedUnit
    from eovrt_media.config.prompt_plan import PromptPlan
```

Agregar atributo de clase y cambiar firmas (líneas 40-61):

```python
class BaseDetectorAdapter(ABC):
    """Interfaz común para todos los adaptadores de modelo."""

    PROMPT_BACKEND: str = "default"
    """Clave de fraseo del adaptador: 'gdino' | 'yoloe' | 'default'."""

    @abstractmethod
    def load(self) -> None:
        """Cargar el modelo en memoria/GPU."""

    @abstractmethod
    def predict(self, image: Image.Image | Path, plan: PromptPlan) -> list[RawDetection]:
        """Inferencia sobre una imagen; devuelve RawDetection ya ligadas al plan."""

    @abstractmethod
    def forward(self, unit: NormalizedUnit, plan: PromptPlan) -> list[RawDetection]:
        """Inferencia desde una unidad normalizada; devuelve RawDetection ligadas."""
```

- [ ] **Step 7: Write the failing mock binding test**

```python
# tests/test_mock_detector.py
from eovrt_media.config.prompt_plan import PromptPlan, PromptPhrase
from eovrt_media.models.mock_detector import MockDetectorAdapter
from PIL import Image


def test_mock_binds_canonical_and_prompt_id():
    plan = PromptPlan(set_id="s", backend="default", phrases=(
        PromptPhrase(0, "helmet", "helmet", "helmet", "positive_evidence", "CR-01"),
    ))
    out = MockDetectorAdapter(seed=1).predict(Image.new("RGB", (64, 64)), plan)
    for d in out:
        assert d.label == "helmet"          # label = canonical
        assert d.prompt_id == "helmet"
        assert d.source_prompt == "helmet"
        assert d.strategy == "positive_evidence"
        assert d.condition_id == "CR-01"
```

- [ ] **Step 8: Run to verify it fails, then implement mock binding**

Run: `pytest tests/test_mock_detector.py -v`
Expected: FAIL.

En `models/mock_detector.py`, cambiar imports y ambos métodos para iterar `plan.by_index()` en vez de `prompts`. `predict` (líneas 25-53):

```python
    def predict(self, image: Image.Image | Path, plan: PromptPlan) -> list[RawDetection]:
        """Genera detecciones aleatorias para cada frase del plan."""
        if isinstance(image, Path):
            width, height = Image.open(image).size
        else:
            width, height = image.size

        detections = []
        for phrase in plan.by_index():
            for _ in range(self._rng.randint(0, 3)):
                x1 = self._rng.uniform(0, width * 0.7)
                y1 = self._rng.uniform(0, height * 0.7)
                x2 = self._rng.uniform(x1 + 20, min(x1 + width * 0.4, width))
                y2 = self._rng.uniform(y1 + 20, min(y1 + height * 0.4, height))
                detections.append(self._bind(phrase, [x1, y1, x2, y2]))
        return detections

    def forward(self, unit: NormalizedUnit, plan: PromptPlan) -> list[RawDetection]:
        """Genera detecciones en el espacio target_size normalizado."""
        target_h, target_w = unit.target_size
        detections = []
        for phrase in plan.by_index():
            for _ in range(self._rng.randint(0, 3)):
                x1 = self._rng.uniform(0, target_w * 0.7)
                y1 = self._rng.uniform(0, target_h * 0.7)
                x2 = self._rng.uniform(x1 + 20, min(x1 + target_w * 0.4, target_w))
                y2 = self._rng.uniform(y1 + 20, min(y1 + target_h * 0.4, target_h))
                detections.append(self._bind(phrase, [x1, y1, x2, y2]))
        return detections

    def _bind(self, phrase, box):
        return RawDetection(
            label=phrase.canonical, prompt_id=phrase.prompt_id, source_prompt=phrase.text,
            strategy=phrase.strategy, condition_id=phrase.condition_id,
            score=self._rng.uniform(0.3, 0.99), box_xyxy=box,
        )
```

Agregar import al inicio: `from eovrt_media.config.prompt_plan import PromptPlan` (bajo TYPE_CHECKING para la firma) y mantener el de `RawDetection`.

Run: `pytest tests/test_mock_detector.py -v`
Expected: PASS.

### Sub-bloque 3 — Normalizer simplificado

- [ ] **Step 9: Write the failing normalizer test**

```python
# tests/test_detection_normalizer.py
from eovrt_media.contracts.detection import RawDetection
from eovrt_media.postprocessing.detection_normalizer import DetectionNormalizer


def test_normalizer_trusts_adapter_binding():
    raw = [RawDetection(label="helmet", prompt_id="helmet", source_prompt="hard hat",
                        strategy="positive_evidence", condition_id="CR-01",
                        score=0.9, box_xyxy=[0, 0, 50, 50])]
    out = DetectionNormalizer(min_confidence=0.1).normalize(raw, 100, 100, "mock")
    assert out[0].prompt_id == "helmet"
    assert out[0].strategy == "positive_evidence"
    assert out[0].condition_id == "CR-01"
```

- [ ] **Step 10: Run to verify it fails, then simplify the normalizer**

Run: `pytest tests/test_detection_normalizer.py -v`
Expected: FAIL — `normalize()` aún exige/acepta `prompt_items` y no copia `strategy`/`condition_id`.

En `detection_normalizer.py`: quitar el import `from eovrt_media.config import PromptItem` (línea 8). Cambiar la firma de `normalize` (líneas 31-39) — eliminar el parámetro `prompt_items`:

```python
    def normalize(
        self,
        raw_detections: list[RawDetection],
        width: int,
        height: int,
        model_name: str,
        transform: ResizeTransform | None = None,
    ) -> list[Detection]:
```

Eliminar el bloque "5. Mapear etiqueta a prompt_id" (líneas 87-96). Reemplazar la construcción de `Detection` (líneas 101-112) para confiar en el binding y copiar metadatos:

```python
            normalized_detections.append(
                Detection(
                    detection_id=f"det_{idx + 1:06d}",
                    label=raw.label,
                    prompt_id=raw.prompt_id,
                    strategy=raw.strategy,
                    condition_id=raw.condition_id,
                    confidence=round(raw.score, 4),
                    bbox_xyxy=[round(c, 1) for c in box_xyxy],
                    bbox_norm_xyxy=bbox_norm,
                    area_px=round(area, 1),
                    model_name=model_name,
                )
            )
```

Run: `pytest tests/test_detection_normalizer.py -v`
Expected: PASS.

### Sub-bloque 4 — Pipeline + migración de YAML + verde end-to-end

- [ ] **Step 11: Migrate the prompt set YAMLs to the new format**

Migrar `configs/prompts/cr01_cr02_v2_short.yaml` y `cr01_cr02_bench_v2.yaml` al formato nuevo, **preservando los `id` y las frases exactas** (una frase por clase en `phrasings.default`). Ejemplo de la forma resultante (adaptar a las clases/textos reales del archivo actual):

```yaml
prompt_set:
  id: cr01_cr02_v2_short
  language: en
  classes:
    - id: person
      role: entity
      phrasings: { default: ["<texto actual de person>"] }
    - id: helmet
      role: ppe
      condition_id: CR-01
      phrasings: { default: ["<texto actual de helmet>"] }
    - id: vest
      role: ppe
      condition_id: CR-02
      phrasings: { default: ["<texto actual de vest>"] }
    - id: bare_head
      role: visual_risk_indicator
      phrasings: { default: ["<texto actual de bare_head>"] }
```

**Importante:** leer primero el contenido actual de cada archivo y copiar los textos textualmente (reproducibilidad BENCH). Conservar el mismo `enabled_by_default` por clase.

- [ ] **Step 12: Wire the pipeline to build the plan per backend**

En `runtime/pipeline.py`, función `run_pipeline` (líneas 332-341): mover la creación del adaptador **antes** de construir el plan, y reemplazar `get_prompt_texts`/`get_prompt_items`:

```python
        adapter = create_adapter(config.model)
        plan = config.build_prompt_plan(adapter.PROMPT_BACKEND)
        prompt_set_id = config.prompts_file.resolved_set_id() if config.prompts_file else "unknown"

        normalizer = DetectionNormalizer(
            min_confidence=config.postprocess.min_confidence,
            min_box_area_px=config.postprocess.min_box_area_px,
            normalize_boxes=config.postprocess.normalize_boxes,
        )
        reset_gpu_peak_memory()
```

(Eliminar la línea `adapter = create_adapter(config.model)` duplicada que estaba en 341.)

En la llamada a `run_consumer_loop` (líneas 382-397): reemplazar `prompt_texts=prompt_texts, prompt_items=prompt_items,` por `plan=plan,`.

En la firma de `run_consumer_loop` (cerca de línea 140-152) y su cuerpo: reemplazar los parámetros `prompt_texts`/`prompt_items` por `plan: PromptPlan`. En la línea 170 cambiar `adapter.forward(item, prompt_texts)` → `adapter.forward(item, plan)`. Localizar la llamada a `normalizer.normalize(` dentro de `run_consumer_loop` (después de la línea 209) y eliminar el argumento `prompt_items=prompt_items`.

- [ ] **Step 13: Apply the same flip in the two-node runtime**

Run: `grep -rn "get_prompt_texts\|get_prompt_items\|prompt_items\|prompt_texts\|resolved_version" src/eovrt_media/runtime/`
Para cada hit en `two_node.py` y `two_node_local.py`: construir `plan = config.build_prompt_plan(adapter.PROMPT_BACKEND)` donde se crea el adaptador, pasar `plan` a `forward`, quitar `prompt_items` de `normalize`, y usar `resolved_set_id()` en vez de `resolved_version`.

- [ ] **Step 14: Update the pipeline-mock integration test**

En `tests/test_pipeline_mock.py`: el fixture carga `gdino.yaml` (que usa `model.ref` real). Forzar el modelo mock en el override del config para no requerir pesos, y asegurar que `prompts.ref` apunte al set migrado. Verificar que el `detections.jsonl` resultante trae `label` canónico, `prompt_id` poblado y `strategy`/`condition_id` cuando el set los declara:

```python
def test_detections_have_canonical_binding(tmp_path):
    # ... cargar config con model mock + prompts.ref=cr01_cr02_v2_short ...
    # tras run_pipeline, leer detections.jsonl
    import json
    lines = [json.loads(l) for l in (run_dir / "detections.jsonl").read_text().splitlines()]
    assert all("prompt_id" in d for d in lines)
```

- [ ] **Step 15: Run the full suite + lint**

Run: `make test`
Expected: PASS (mock end-to-end, schema, normalizer, prompt_plan, contracts). Los tests de GDINO/YOLOE que pasen `list[str]` quedarán rojos solo si ejercitan `forward/predict` directamente — si los hay, marcarlos `xfail` con referencia a A4/A5 y un TODO, o moverlos a A4/A5.

Run: `make lint`
Expected: clean.

- [ ] **Step 16: Commit** (sugerido)

```
feat(prompts): single canonical schema + PromptPlan binding (mock path); simplify normalizer
```

---

## Task A4: Binding por construcción en GDINO

**Files:**
- Modify: `src/eovrt_media/models/grounding_dino_adapter.py`
- Test: `tests/test_grounding_dino_binding.py`

**Interfaces:**
- Consumes: `PromptPlan` (A2), firma base (A3).
- Produces: `GroundingDinoHFAdapter.PROMPT_BACKEND = "gdino"`; `predict`/`forward` reciben `PromptPlan`; spans no resueltos se descartan + log.

- [ ] **Step 1: Write the failing test (stubbed inference)**

```python
# tests/test_grounding_dino_binding.py
from eovrt_media.config.prompt_plan import PromptPlan, PromptPhrase
from eovrt_media.models.grounding_dino_adapter import GroundingDinoHFAdapter


def _plan():
    return PromptPlan(set_id="s", backend="gdino", phrases=(
        PromptPhrase(0, "hard hat", "helmet", "helmet", "positive_evidence", "CR-01"),
        PromptPhrase(1, "person", "person", "person"),
    ))


def test_backend_key():
    assert GroundingDinoHFAdapter.PROMPT_BACKEND == "gdino"


def test_span_resolves_to_canonical(monkeypatch):
    ad = GroundingDinoHFAdapter()
    # stub: el modelo "devolvió" el span "hard hat"
    out = ad._bind_span("hard hat", 0.9, [0, 0, 10, 10], _plan())
    assert out.label == "helmet" and out.prompt_id == "helmet"
    assert out.source_prompt == "hard hat" and out.condition_id == "CR-01"


def test_unresolved_span_returns_none(monkeypatch):
    ad = GroundingDinoHFAdapter()
    assert ad._bind_span("zzz unrelated", 0.9, [0, 0, 10, 10], _plan()) is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_grounding_dino_binding.py -v`
Expected: FAIL — `_bind_span` no existe; `PROMPT_BACKEND` ausente.

- [ ] **Step 3: Implement GDINO binding**

En `grounding_dino_adapter.py`:
- Agregar `PROMPT_BACKEND = "gdino"` como atributo de clase (dentro de `GroundingDinoHFAdapter`, después del docstring de clase, ~línea 49).
- Cambiar `predict(self, image, prompts)` → `predict(self, image, plan: PromptPlan)`; dentro, `text = ". ".join(plan.texts()) + "."`; pasar `plan` a `_run_inference`.
- Cambiar `forward(self, unit, prompts)` → `forward(self, unit, plan: PromptPlan)`; `text = ". ".join(plan.texts()) + "."`; pasar `plan`.
- Cambiar `_run_inference(self, inputs, prompts, target_size)` → `(self, inputs, plan, target_size)`. Reemplazar el bucle de construcción (líneas 157-165):

```python
        by_text = plan.by_text()
        texts = plan.texts()
        for box, score, label in zip(boxes, scores, raw_labels):
            det = self._bind_span(str(label).strip(), float(score),
                                  [float(c) for c in box], plan, by_text, texts)
            if det is not None:
                detections.append(det)
```

- Agregar el método de binding (resolución contra el plan; `_normalize_label` queda como desempate final, devolviendo un texto del plan que se mapea vía `by_text`):

```python
    def _bind_span(self, detected, score, box, plan, by_text=None, texts=None):
        by_text = by_text if by_text is not None else plan.by_text()
        texts = texts if texts is not None else plan.texts()
        phrase = by_text.get(detected)
        if phrase is None:
            dl = detected.lower()
            match = next((t for t in texts if t.lower() == dl), None) \
                or next((t for t in texts if dl in t.lower()), None) \
                or next((t for t in texts if t.lower() in dl), None)
            if match is None and texts:
                dw = set(dl.split())
                best = max(texts, key=lambda t: len(dw & set(t.lower().split())))
                if dw & set(best.lower().split()):
                    match = best
            phrase = by_text.get(match) if match else None
        if phrase is None:
            logger.warning("GDINO span '%s' no resuelto contra el plan; descartado.", detected)
            return None
        from eovrt_media.contracts.detection import RawDetection
        return RawDetection(
            label=phrase.canonical, prompt_id=phrase.prompt_id, source_prompt=phrase.text,
            strategy=phrase.strategy, condition_id=phrase.condition_id,
            score=score, box_xyxy=box,
        )
```

- Actualizar el warmup (línea 84): `self.predict(dummy, PromptPlan.from_texts(["object"], "gdino"))`. Agregar import `from eovrt_media.config.prompt_plan import PromptPlan` (TYPE_CHECKING para firmas; runtime para warmup → import normal al inicio).
- La función módulo `_normalize_label` (líneas 22-41) puede eliminarse (su lógica vive ahora en `_bind_span`) o conservarse si otros tests la referencian; verificar con grep.

- [ ] **Step 4: Run to verify it passes + lint**

Run: `pytest tests/test_grounding_dino_binding.py -v && ruff check src/eovrt_media/models/grounding_dino_adapter.py`
Expected: PASS, clean.

- [ ] **Step 5: Commit** (sugerido)

```
feat(gdino): bind detections by construction; drop unresolved spans
```

---

## Task A5: Binding por construcción en YOLOE

**Files:**
- Modify: `src/eovrt_media/models/yoloe_adapter.py`
- Test: `tests/test_yoloe_binding.py`

**Interfaces:**
- Produces: `YOLOEUltralyticsAdapter.PROMPT_BACKEND = "yoloe"`; `class_id → plan.by_index()[class_id]` exacto; cache compara `plan.texts()`.

- [ ] **Step 1: Write the failing test (stubbed result)**

```python
# tests/test_yoloe_binding.py
from types import SimpleNamespace
from eovrt_media.config.prompt_plan import PromptPlan, PromptPhrase
from eovrt_media.models.yoloe_adapter import YOLOEUltralyticsAdapter


def _plan():
    return PromptPlan(set_id="s", backend="yoloe", phrases=(
        PromptPhrase(0, "person", "person", "person"),
        PromptPhrase(1, "helmet", "helmet", "helmet", "positive_evidence", "CR-01"),
    ))


def test_backend_key():
    assert YOLOEUltralyticsAdapter.PROMPT_BACKEND == "yoloe"


def test_class_id_maps_to_canonical_exact():
    ad = YOLOEUltralyticsAdapter()
    out = ad._decode_boxes([[0, 0, 10, 10]], [0.9], [1.0], _plan())  # cls_id=1 → helmet
    assert out[0].label == "helmet" and out[0].prompt_id == "helmet"
    assert out[0].condition_id == "CR-01"
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_yoloe_binding.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement YOLOE binding**

En `yoloe_adapter.py`:
- Agregar `PROMPT_BACKEND = "yoloe"` (atributo de clase, ~línea 28).
- `_ensure_classes(self, prompts)` → `_ensure_classes(self, plan: PromptPlan)`; usar `texts = plan.texts()`; comparar `self._prompts_set != texts`; `self.model.set_classes(texts)`; `self._prompts_set = list(texts)`.
- `predict(self, image, prompts)` → `predict(self, image, plan: PromptPlan)`; `self._ensure_classes(plan)`; tras inferencia, reemplazar el bucle (líneas 145-153) por `return self._decode_boxes(boxes, scores, class_ids, plan)`.
- Agregar:

```python
    def _decode_boxes(self, boxes, scores, class_ids, plan):
        from eovrt_media.contracts.detection import RawDetection
        by_index = plan.by_index()
        out = []
        for box, score, cls_id in zip(boxes, scores, class_ids):
            phrase = by_index[int(cls_id)]   # class_id == índice en plan.texts()
            out.append(RawDetection(
                label=phrase.canonical, prompt_id=phrase.prompt_id, source_prompt=phrase.text,
                strategy=phrase.strategy, condition_id=phrase.condition_id,
                score=float(score), box_xyxy=[float(c) for c in box],
            ))
        return out
```

- `forward(self, unit, prompts)` → `forward(self, unit, plan: PromptPlan)`: `return self.predict(prepare_model_input(...), plan)`.
- Warmup (línea 63): `self.predict(dummy, PromptPlan.from_texts(["object"], "yoloe"))`. Import de `PromptPlan` al inicio.

- [ ] **Step 4: Run to verify it passes + lint**

Run: `pytest tests/test_yoloe_binding.py -v && ruff check src/eovrt_media/models/yoloe_adapter.py`
Expected: PASS, clean.

- [ ] **Step 5: Full suite + commit** (sugerido)

Run: `make test && make lint`
Expected: PASS, clean.

```
feat(yoloe): bind detections by construction via class_id index
```

---

# FASE B — Relocalización a experimental-setup

## Task B1: Loader de dos raíces

**Files:**
- Modify: `src/eovrt_media/config/loader.py`
- Test: `tests/test_config_refs.py`

**Interfaces:**
- Produces:
  - `find_plane_catalog_root(override: str | Path | None = None) -> Path` (orden: override → env `EOVRT_MEDIA_CATALOG_ROOT` → repo-relative `Path(__file__).resolve().parents[3] / "configs"`)
  - `find_experiment_root(manifest_path: Path) -> Path` (sube hasta un dir con subdir `prompts/`; fallback: dir del manifiesto)
  - `load_run_config(config_path, catalog_root: str | Path | None = None) -> RunConfig`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config_refs.py  (añadir)
import os
from pathlib import Path
from eovrt_media.config.loader import find_plane_catalog_root, find_experiment_root


def test_plane_catalog_root_repo_relative():
    root = find_plane_catalog_root()
    assert root.name == "configs" and (root / "models").is_dir()


def test_plane_catalog_root_env_override(monkeypatch, tmp_path):
    (tmp_path / "models").mkdir()
    monkeypatch.setenv("EOVRT_MEDIA_CATALOG_ROOT", str(tmp_path))
    assert find_plane_catalog_root() == tmp_path


def test_experiment_root_finds_prompts_dir(tmp_path):
    (tmp_path / "prompts").mkdir()
    (tmp_path / "experiments" / "g").mkdir(parents=True)
    manifest = tmp_path / "experiments" / "g" / "m.yaml"
    manifest.write_text("x: 1")
    assert find_experiment_root(manifest) == tmp_path
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_config_refs.py -v -k "plane_catalog or experiment_root"`
Expected: FAIL — funciones inexistentes.

- [ ] **Step 3: Implement the two-root functions**

En `loader.py`, reemplazar `find_configs_root` (líneas 150-163) por:

```python
def find_plane_catalog_root(override: str | Path | None = None) -> Path:
    """Raíz del catálogo de capacidades del media-plane (``configs/``).

    Orden: override explícito → env EOVRT_MEDIA_CATALOG_ROOT → repo-relative.
    """
    if override is not None:
        return Path(override).resolve()
    env = os.environ.get("EOVRT_MEDIA_CATALOG_ROOT")
    if env:
        return Path(env).resolve()
    # src/eovrt_media/config/loader.py → parents[3] == raíz del repo
    return Path(__file__).resolve().parents[3] / "configs"


def find_experiment_root(manifest_path: Path) -> Path:
    """Raíz del repo de experimentos: ancestro que contiene ``prompts/``."""
    resolved = Path(manifest_path).resolve()
    for parent in [resolved.parent, *resolved.parents]:
        if (parent / "prompts").is_dir():
            return parent
    return resolved.parent
```

Agregar `import os` al inicio (después de `from pathlib import Path`).

- [ ] **Step 4: Rewire `load_run_config` for two roots**

En `load_run_config` (líneas 200-238): aceptar `catalog_root` y resolver por raíz según sección.

```python
def load_run_config(config_path: Path, catalog_root: str | Path | None = None) -> RunConfig:
    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Archivo de configuración no encontrado: {config_path}")
    with open(config_path) as f:
        raw = yaml.safe_load(f) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"Configuración inválida (se esperaba mapping): {config_path}")
    if "sampling" in raw:
        _raise_sampling_migration_error()

    plane_root = find_plane_catalog_root(catalog_root)
    experiment_root = find_experiment_root(config_path)
    _resolve_section_ref(raw, "model", "models", plane_root)
    _resolve_section_ref(raw, "source", "datasets", plane_root)
    _derive_defaults(raw)

    prompts_data = raw.get("prompts")
    if isinstance(prompts_data, dict) and prompts_data.get("ref") and not prompts_data.get("file"):
        prompts_data["file"] = str(experiment_root / "prompts" / f"{prompts_data['ref']}.yaml")

    config = RunConfig(**raw)
    config.config_path = config_path

    prompts_path = Path(config.prompts.file)
    if not prompts_path.is_absolute():
        relative_to_config = config_path.parent / prompts_path
        if relative_to_config.exists():
            prompts_path = relative_to_config

    config.prompts_file = load_prompts_file(prompts_path)
    _validate_deployment(config)
    return config
```

- [ ] **Step 5: Run tests + lint + commit** (sugerido)

Run: `pytest tests/test_config_refs.py -v && make lint`
Expected: PASS, clean.

```
feat(loader): two-root resolution (plane catalog vs experiment root)
```

---

## Task B2: CLI override + `experiment` metadata + RunSummary

**Files:**
- Modify: `src/eovrt_media/cli.py` (comandos `run`, `run-producer`, `run-consumer`)
- Modify: `src/eovrt_media/config/schemas.py` (`ExperimentSection`, `RunConfig.experiment`)
- Modify: `src/eovrt_media/contracts/events.py` (`RunSummary.experiment_id`)
- Modify: el sitio donde se construye `RunSummary` (localizar con grep)
- Test: `tests/test_config.py`, `tests/test_cli.py` (si existe)

**Interfaces:**
- Produces: `ExperimentSection(id: str | None = None)`; `RunConfig.experiment`; `--catalog-root` en CLI; `RunSummary.experiment_id`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py  (añadir)
def test_experiment_section_optional():
    from eovrt_media.config.schemas import RunConfig
    cfg = RunConfig(run={"name": "x"}, source={"path": "p"}, model={"name": "mock"},
                    prompts={"ref": "r"})
    assert cfg.experiment.id is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_config.py -v -k experiment`
Expected: FAIL — `RunConfig` no tiene `experiment`.

- [ ] **Step 3: Add `ExperimentSection` and wire it**

En `schemas.py`, antes de `RunConfig` (~línea 285):

```python
class ExperimentSection(BaseModel):
    """Metadata/provenance del experimento (cross-plano, propagada al run)."""

    id: str | None = None
```

En `RunConfig` (después de `prompts: PromptsSection`, línea 292):

```python
    experiment: ExperimentSection = Field(default_factory=ExperimentSection)
```

En `to_effective_dict`, el `model_dump` ya incluirá `experiment`. (Verificar.)

- [ ] **Step 4: Add `experiment_id` to RunSummary and populate it**

En `contracts/events.py`, en `RunSummary` (junto a `prompt_set_id`): agregar `experiment_id: str | None = None`.

Run: `grep -rn "RunSummary(" src/eovrt_media/`
En cada sitio de construcción (sinks/runtime), agregar `experiment_id=config.experiment.id` (donde `config` esté disponible; si no, pasar el valor por parámetro hasta el sitio).

- [ ] **Step 5: Add `--catalog-root` to the three run commands**

En `cli.py`, en `run`, `run-producer`, `run-consumer`: agregar la opción y pasarla a `load_run_config`:

```python
    catalog_root: Path | None = typer.Option(
        None, "--catalog-root",
        help="Raíz del catálogo del plano (configs/). Default: autodescubierto.",
    ),
```

y `load_run_config(config, catalog_root=catalog_root)` en las tres (líneas 36, 51, 65).

- [ ] **Step 6: Run tests + lint + commit** (sugerido)

Run: `make test && make lint`
Expected: PASS, clean.

```
feat(config): experiment metadata + --catalog-root override; thread experiment_id to summary
```

---

## Task B3: Test suite self-contained (fixtures locales)

**Files:**
- Create: `tests/fixtures/prompts/test_ppe.yaml`
- Create: `tests/fixtures/runs/mock_local.yaml`
- Modify: `tests/test_config.py`, `tests/test_pipeline_mock.py`, `tests/test_two_node_local.py`

**Interfaces:**
- Consumes: loader de dos raíces (B1) — `find_experiment_root` localiza `tests/fixtures/` por su subdir `prompts/`.

- [ ] **Step 1: Create the local test prompt set (new format)**

```yaml
# tests/fixtures/prompts/test_ppe.yaml
prompt_set:
  id: test_ppe
  language: en
  classes:
    - id: person
      role: entity
      phrasings: { default: ["person"] }
    - id: helmet
      role: ppe
      condition_id: CR-01
      phrasings: { default: ["helmet"], gdino: ["hard hat"] }
    - id: vest
      role: ppe
      condition_id: CR-02
      enabled_by_default: false
      phrasings: { default: ["vest"] }
```

- [ ] **Step 2: Create a self-contained mock manifest**

```yaml
# tests/fixtures/runs/mock_local.yaml
run: { scenario: DBE, name: test_mock, max_units: 3 }
source: { type: image_folder, path: tests/fixtures/images }
model: { name: mock }
prompts: { ref: test_ppe, active_ids: [person, helmet] }
```

(Si no existe `tests/fixtures/images`, usar la ruta de imágenes de prueba que ya use el suite; ver `tests/conftest.py`.)

- [ ] **Step 3: Repoint the dependent tests**

- `tests/test_config.py`: cambiar `PROMPTS_PATH` para que apunte a `tests/fixtures/prompts/test_ppe.yaml` y actualizar las aserciones al formato nuevo.
- `tests/test_pipeline_mock.py`: cargar `tests/fixtures/runs/mock_local.yaml` (en vez de `gdino.yaml`).
- `tests/test_two_node_local.py`: usar `prompts_ref="test_ppe"` y, si construye configs, apuntar la raíz de experimento a `tests/fixtures/`.

- [ ] **Step 4: Verify the suite no longer depends on `configs/prompts/`**

Run: `grep -rn "configs/prompts\|cr01_cr02" tests/`
Expected: sin hits (los tests usan solo `tests/fixtures/`).

Run: `make test`
Expected: PASS — suite self-contained.

- [ ] **Step 5: Commit** (sugerido)

```
test: make prompt resolution self-contained via tests/fixtures
```

---

## Task B4: Relocalización física a experimental-setup

**Files:**
- Create (repo hermano): `/home/simonll4/projects/e-ovrt_experimental-setup/prompts/cr01_cr02_v2_short.yaml`, `cr01_cr02_bench_v2.yaml`, `ppe_v2_descriptive.yaml`
- Create (repo hermano): `/home/simonll4/projects/e-ovrt_experimental-setup/experiments/...` (manifiestos migrados)
- Remove (media-plane): `configs/prompts/*.yaml`, los run configs de experimento de `configs/runs/`
- Create (repo hermano): `README.md` documentando layout + convención CWD

**Interfaces:**
- Consumes: B1 (dos raíces), B3 (suite ya no depende de `configs/prompts/`).

- [ ] **Step 1: Move the migrated prompt sets to experimental-setup**

```bash
mkdir -p /home/simonll4/projects/e-ovrt_experimental-setup/prompts
git -C /home/simonll4/projects/e-ovrt_media-plane mv configs/prompts/cr01_cr02_v2_short.yaml \
   /home/simonll4/projects/e-ovrt_experimental-setup/prompts/cr01_cr02_v2_short.yaml
git -C /home/simonll4/projects/e-ovrt_media-plane mv configs/prompts/cr01_cr02_bench_v2.yaml \
   /home/simonll4/projects/e-ovrt_experimental-setup/prompts/cr01_cr02_bench_v2.yaml
```

(`git mv` cross-repo equivale a mover + borrar en origen; el usuario commitea ambos repos.)

- [ ] **Step 2: Create the new descriptive set**

```yaml
# e-ovrt_experimental-setup/prompts/ppe_v2_descriptive.yaml
prompt_set:
  id: ppe_v2_descriptive
  language: en
  classes:
    - id: person
      role: entity
      phrasings: { default: ["person"], gdino: ["person", "worker"], yoloe: ["person"] }
    - id: helmet
      role: ppe
      condition_id: CR-01
      phrasings: { default: ["helmet"], gdino: ["hard hat", "safety helmet"], yoloe: ["helmet"] }
    - id: vest
      role: ppe
      condition_id: CR-02
      phrasings: { default: ["vest"], gdino: ["reflective vest", "high-visibility vest"], yoloe: ["vest"] }
    - id: bare_head
      role: visual_risk_indicator
      phrasings: { default: ["bare head"], gdino: ["bare head", "uncovered head"], yoloe: ["bare head"] }
```

**Acotar el nº de frases activas** (riesgo de longitud de caption en GDINO, spec prompts §11).

- [ ] **Step 3: Move the experiment run configs**

Mover `configs/runs/experiments/`, `configs/runs/gdino.yaml`, `configs/runs/yoloe.yaml`, `configs/runs/yoloe_video.yaml` a `e-ovrt_experimental-setup/experiments/` (con `git mv` cross-repo). Reorganizar por grupo (`experiments/bench_v2/`, etc.). En cada manifiesto: añadir bloque `experiment: { id: <nombre> }` y verificar que `prompts.ref`/`model.ref`/`source.ref` siguen siendo válidos (resuelven por las dos raíces). Dejar en el media-plane solo fixtures (`tests/fixtures/`) — `configs/runs/mock*.yaml` puede borrarse si `tests/fixtures/runs/` ya lo cubre.

- [ ] **Step 4: Write the experimental-setup README**

Documentar: layout (`prompts/`, `experiments/`), cómo correr (`cd e-ovrt_media-plane && eovrt-media run --config ../e-ovrt_experimental-setup/experiments/<grupo>/<m>.yaml`), la convención CWD (correr desde la raíz del media-plane para que `../e-ovrt_datasets/...` y `outputs.base_dir: runs/` resuelvan), y el override `--catalog-root`/`EOVRT_MEDIA_CATALOG_ROOT`.

- [ ] **Step 5: End-to-end verification from an external manifest**

```bash
cd /home/simonll4/projects/e-ovrt_media-plane
# manifiesto mock externo de prueba (model.name=mock) en experimental-setup/experiments/
eovrt-media validate-config --config ../e-ovrt_experimental-setup/experiments/_smoke/mock.yaml
eovrt-media run --config ../e-ovrt_experimental-setup/experiments/_smoke/mock.yaml
```

Expected: resuelve `prompts.ref` contra `experimental-setup/prompts/`, `model.ref`/`source.ref` contra `media-plane/configs/`, y produce `detections.jsonl` con `label` canónico + `prompt_id`. 

Run: `make test`
Expected: PASS (suite sigue self-contained, no depende del repo hermano).

- [ ] **Step 6: Commit** (sugerido — en ambos repos, el usuario decide)

```
refactor: relocate prompt sets + experiment manifests to e-ovrt_experimental-setup
```

---

## Self-Review (cobertura de specs)

**Prompt-layer spec (2026-06-25):**
- §3 esquema único + `phrasings` → A3 (clases nuevas). ✓
- §3.1 `strategy`/`condition_id` metadatos → A1 (contratos) + A3 (clases) + A3 (propagación normalizer). ✓
- §4 `PromptPlan` + `build_plan` → A2 + A3. ✓
- §5 `PROMPT_BACKEND` (gdino/yoloe/default; MM-GDINO usa gdino) → A3 (base/mock) + A4 + A5. ✓
- §6 binding por construcción + normalizer simplificado + span no resuelto descartado → A3 (mock/normalizer) + A4 (gdino) + A5 (yoloe). ✓
- §7 contratos → A1. ✓
- §9 migración (esquema, RunConfig, archivos, adaptadores, pipeline, normalizer, contratos) → A1-A5 + B4. ✓
- §10 testing → tests en cada tarea. ✓

**Experimental-setup spec (2026-06-27):**
- §3-§4 fronteras + manifiesto + `experiment` → B2 (ExperimentSection) + B4 (manifiestos). ✓
- §5 dos raíces → B1. ✓
- §6 cambios media-plane (loader, CLI, schema, RunSummary) → B1 + B2. ✓
- §7 relación con prompts (ubicación + raíz) → B1 + B4. ✓
- §8 migración + fixtures de test (agujero crítico) → B3 + B4. ✓
- §9 puntos de extensión (control/alertas) → no se construyen (documentados en spec). ✓
- §10 testing → tests en B1-B4. ✓

**Gaps conocidos a resolver durante ejecución:**
- Localizar el sitio exacto de `normalizer.normalize(` dentro de `run_consumer_loop` (A3 step 12) y de construcción de `RunSummary` (B2 step 4) vía grep.
- `two_node.py`/`two_node_local.py`: cantidad exacta de call sites a migrar (A3 step 13, grep).
- Textos exactos de los sets congelados (A3 step 11): copiar verbatim del archivo actual.
