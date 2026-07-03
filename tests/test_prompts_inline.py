from pathlib import Path
import pytest
from eovrt_media.config.loader import load_run_config_data
from eovrt_media.config.schemas import PromptsSection

REPO_ROOT = Path(__file__).resolve().parents[1]
PLANE_ROOT = REPO_ROOT / "configs"
FIXTURE_PROMPTS = REPO_ROOT / "tests" / "fixtures"

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
    with pytest.raises(ValueError, match="set_inline"):
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


# ============================================================================
# Multi-source precedence tests: set_inline > file > ref
# ============================================================================


def test_precedence_set_inline_beats_ref(tmp_path):
    """When set_inline and ref are both present, set_inline takes precedence.

    Verify: resolved set_id matches the inline set (not the ref target).
    """
    raw = {
        "run": {"scenario": "DBE"},
        "source": {"type": "image_folder", "path": str(tmp_path)},
        "model": {"adapter": "mock"},
        "prompts": {
            "set_inline": SET_INLINE,
            "ref": "cr01_cr02_v2_short",  # Real ref that exists in fixtures, different id
            "active_ids": ["person"],
        },
    }
    config = load_run_config_data(
        raw, plane_root=PLANE_ROOT, experiment_root=FIXTURE_PROMPTS
    )
    # Should resolve to inline set's id, NOT the ref's id
    assert config.prompts_file.resolved_set_id() == "inline_test"
    assert config.prompts_file.resolved_set_id() != "cr01_cr02_v2_short"


def test_precedence_set_inline_beats_file(tmp_path):
    """When set_inline and file are both present, set_inline takes precedence.

    Verify: resolved set_id matches the inline set (not the file's content).
    """
    # Create a temporary prompt file with a different set_id
    prompt_file = tmp_path / "other_prompts.yaml"
    prompt_file.write_text("""
prompt_set:
  id: file_based_set
  classes:
    - id: person
      phrasings: { default: ["person"] }
""")

    raw = {
        "run": {"scenario": "DBE"},
        "source": {"type": "image_folder", "path": str(tmp_path)},
        "model": {"adapter": "mock"},
        "prompts": {
            "set_inline": SET_INLINE,
            "file": str(prompt_file),
            "active_ids": ["person"],
        },
    }
    config = load_run_config_data(raw, plane_root=PLANE_ROOT)
    # Should resolve to inline set's id, NOT the file's id
    assert config.prompts_file.resolved_set_id() == "inline_test"
    assert config.prompts_file.resolved_set_id() != "file_based_set"


def test_no_wasted_io_with_set_inline_and_invalid_ref(tmp_path):
    """When set_inline is present, invalid ref is never resolved (no I/O attempt).

    Verify: no FileNotFoundError even if ref points to a non-existent file.
    This confirms the precedence implementation skips ref resolution entirely
    when set_inline is present.
    """
    raw = {
        "run": {"scenario": "DBE"},
        "source": {"type": "image_folder", "path": str(tmp_path)},
        "model": {"adapter": "mock"},
        "prompts": {
            "set_inline": SET_INLINE,
            "ref": "does-not-exist-anywhere-xyz-12345",  # Invalid ref
            "active_ids": ["person"],
        },
    }
    # Should NOT raise FileNotFoundError despite invalid ref
    config = load_run_config_data(
        raw, plane_root=PLANE_ROOT, experiment_root=FIXTURE_PROMPTS
    )
    assert config.prompts_file.resolved_set_id() == "inline_test"


def test_set_inline_with_active_ids_overrides_ref_active_ids(tmp_path):
    """set_inline precedence applies to both set selection AND active_ids."""
    raw = {
        "run": {"scenario": "DBE"},
        "source": {"type": "image_folder", "path": str(tmp_path)},
        "model": {"adapter": "mock"},
        "prompts": {
            "set_inline": SET_INLINE,
            "ref": "cr01_cr02_v2_short",
            "active_ids": ["helmet"],  # Only activate helmet, not person
        },
    }
    config = load_run_config_data(
        raw, plane_root=PLANE_ROOT, experiment_root=FIXTURE_PROMPTS
    )
    assert config.prompts_file.resolved_set_id() == "inline_test"
    plan = config.build_prompt_plan("default")
    # active_ids should work with inline set
    assert [p.prompt_id for p in plan.phrases] == ["helmet"]
