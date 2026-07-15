from pathlib import Path

from codex_axi.guidance import render_skill


def test_committed_skill_is_generated_from_home_guidance():
    path = Path(__file__).parents[1] / "skills" / "codex-axi" / "SKILL.md"
    assert path.read_text() == render_skill()
