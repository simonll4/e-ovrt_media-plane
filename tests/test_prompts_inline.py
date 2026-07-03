from pathlib import Path
import pytest
from eovrt_media.config.loader import load_run_config_data
from eovrt_media.config.schemas import PromptsSection

REPO_ROOT = Path(__file__).resolve().parents[1]
PLANE_ROOT = REPO_ROOT / "configs"

SET_INLINE = {
    "id": "inline_test",
    "classes": [
        {"id": "person", "phrasings": {"default": ["person"]}},
        {"id": "helmet", "phrasings": {"default": ["helmet"]}},
    ],
}


def test_prompts_section_acepta_set_inline():
    section = PromptsSection(set_inline=SET_INLINE)
    assert section.set_inline.id == "inline_test"


def test_prompts_section_requiere_alguna_fuente():
    with pytest.raises(ValueError, match="ref.*file.*set_inline|set_inline"):
        PromptsSection()


def test_run_config_con_prompts_inline(tmp_path):
    raw = {
        "run": {"scenario": "DBE"},
        "source": {"type": "image_folder", "path": str(tmp_path)},
        "model": {"adapter": "mock"},
        "prompts": {"set_inline": SET_INLINE, "active_ids": ["person"]},
    }
    config = load_run_config_data(raw, plane_root=PLANE_ROOT)
    assert config.prompts_file.resolved_set_id() == "inline_test"
    plan = config.build_prompt_plan("default")
    assert [p.prompt_id for p in plan.phrases] == ["person"]
