import pytest

from eovrt_media.config.schemas import ModelSection
from eovrt_media.models import create_adapter


def test_model_runtime_defaults():
    m = ModelSection(adapter="yoloe")
    assert m.runtime.half_precision is True
    assert m.runtime.warmup is True


def test_factory_passes_runtime_to_yoloe():
    m = ModelSection(adapter="yoloe", device="cpu", runtime={"half_precision": False, "warmup": False})
    adapter = create_adapter(m)
    assert adapter.half_precision is False
    assert adapter.warmup is False


# Contrato D-FT-08 (aprobado 2026-08-15): el único vocabulario fijo admisible.
CANONICAL_V2_FIXED_VOCABULARY = [
    {"id": "person", "text": "person"},
    {"id": "helmet", "text": "helmet"},
    {"id": "vest", "text": "vest"},
    {"id": "bare_head", "text": "bare head"},
]


def test_factory_passes_ordered_fixed_vocabulary_to_yoloe():
    model = ModelSection(adapter="yoloe", fixed_vocabulary=CANONICAL_V2_FIXED_VOCABULARY)

    adapter = create_adapter(model)

    assert adapter.fixed_vocabulary == (
        ("person", "person"),
        ("helmet", "helmet"),
        ("vest", "vest"),
        ("bare_head", "bare head"),
    )


@pytest.mark.parametrize(
    "mutation",
    [
        # orden cambiado
        [CANONICAL_V2_FIXED_VOCABULARY[1], CANONICAL_V2_FIXED_VOCABULARY[0]]
        + CANONICAL_V2_FIXED_VOCABULARY[2:],
        # subset (clase faltante)
        CANONICAL_V2_FIXED_VOCABULARY[:3],
        # id no canónico
        CANONICAL_V2_FIXED_VOCABULARY[:3] + [{"id": "no_helmet", "text": "bare head"}],
        # text distinto del nombre exacto del checkpoint
        CANONICAL_V2_FIXED_VOCABULARY[:3] + [{"id": "bare_head", "text": "bare_head"}],
        # superset (clase extra)
        CANONICAL_V2_FIXED_VOCABULARY + [{"id": "machinery", "text": "machinery"}],
    ],
    ids=("reordered", "subset", "wrong-id", "wrong-text", "superset"),
)
def test_model_section_enforces_canonical_v2_fixed_vocabulary(mutation):
    """D-FT-08: cualquier diferencia de ids, nombres u orden se rechaza en config."""
    with pytest.raises(ValueError, match="D-FT-08"):
        ModelSection(adapter="yoloe", fixed_vocabulary=mutation)


def test_model_section_accepts_exact_canonical_v2_fixed_vocabulary():
    model = ModelSection(adapter="yoloe", fixed_vocabulary=CANONICAL_V2_FIXED_VOCABULARY)
    assert [(e.id, e.text) for e in model.fixed_vocabulary or []] == [
        ("person", "person"),
        ("helmet", "helmet"),
        ("vest", "vest"),
        ("bare_head", "bare head"),
    ]


def test_fixed_vocabulary_none_keeps_dynamic_binding():
    """None conserva el binding dinámico histórico — el enforcement no lo toca."""
    model = ModelSection(adapter="yoloe")
    assert model.fixed_vocabulary is None


@pytest.mark.parametrize(
    "fixed_vocabulary",
    [
        [],
        [{"id": "person", "text": "person"}, {"id": "person", "text": "worker"}],
        [{"id": "person", "text": "person"}, {"id": "worker", "text": "person"}],
        [{"id": " person", "text": "person"}],
    ],
    ids=("empty", "duplicate-id", "duplicate-text", "surrounding-space"),
)
def test_model_section_rejects_invalid_fixed_vocabulary(fixed_vocabulary):
    with pytest.raises(ValueError, match="fixed_vocabulary"):
        ModelSection(adapter="yoloe", fixed_vocabulary=fixed_vocabulary)


def test_model_section_rejects_fixed_vocabulary_for_non_yoloe_adapter():
    with pytest.raises(ValueError, match="sólo es válido para el adapter YOLOE"):
        ModelSection(
            adapter="grounding_dino",
            fixed_vocabulary=[{"id": "person", "text": "person"}],
        )


def test_factory_passes_runtime_to_gdino():
    m = ModelSection(adapter="grounding_dino", device="cpu", runtime={"half_precision": True, "warmup": True})
    adapter = create_adapter(m)
    assert adapter.half_precision is True
    assert adapter.warmup is True
