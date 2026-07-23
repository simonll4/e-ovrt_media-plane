"""image_size en el adaptador GDINO (mejora #5, docs/operacion/61).

El pipeline infiere sobre el letterbox de input_spec.target_size; a 800x800 el
forward de gdino-tiny fp32 mide ~320 ms y a 560 ~193 ms (-40%). El knob
image_size ya existe en ModelSection (lo consume YOLOE) — acá se cablea a GDINO
para poder declarar variantes de catálogo de baja latencia sin tocar las
existentes (comparabilidad con el BENCH v2 de Sprint 2).
"""

from eovrt_media.models.grounding_dino_adapter import GroundingDinoHFAdapter


def test_default_mantiene_800():
    adapter = GroundingDinoHFAdapter()
    assert adapter.input_spec.target_size == (800, 800)


def test_image_size_ajusta_el_input_spec():
    adapter = GroundingDinoHFAdapter(image_size=560)
    assert adapter.input_spec.target_size == (560, 560)


def test_predict_pasa_image_size_al_processor():
    # predict(PIL) y forward(unit) deben inferir al MISMO tamaño: sin esto una
    # variante de catálogo con image_size=560 correría a 560 en el pipeline
    # pero a 800 en tools/evaluate y en el pre-flight.
    from unittest.mock import MagicMock

    from PIL import Image

    from eovrt_media.config.prompt_plan import PromptPlan

    adapter = GroundingDinoHFAdapter(image_size=560)
    adapter.processor = MagicMock(side_effect=RuntimeError("stop"))
    adapter.model = MagicMock()
    try:
        adapter.predict(Image.new("RGB", (32, 32)), PromptPlan.from_texts(["person"], "gdino"))
    except RuntimeError:
        pass
    size = adapter.processor.call_args.kwargs.get("size")
    assert size == {"shortest_edge": 560, "longest_edge": 560}


def test_predict_sin_image_size_no_toca_el_resize_default():
    from unittest.mock import MagicMock

    from PIL import Image

    from eovrt_media.config.prompt_plan import PromptPlan

    adapter = GroundingDinoHFAdapter()
    adapter.processor = MagicMock(side_effect=RuntimeError("stop"))
    adapter.model = MagicMock()
    try:
        adapter.predict(Image.new("RGB", (32, 32)), PromptPlan.from_texts(["person"], "gdino"))
    except RuntimeError:
        pass
    assert "size" not in adapter.processor.call_args.kwargs


def test_create_adapter_propaga_image_size():
    from eovrt_media.config.schemas import ModelSection
    from eovrt_media.models import create_adapter

    section = ModelSection(adapter="grounding_dino", image_size=560)
    adapter = create_adapter(section)
    assert adapter.input_spec.target_size == (560, 560)
