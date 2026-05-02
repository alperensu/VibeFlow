from pathlib import Path

from vibeflow_cli import main, normalize_repo_url, parse_settings


def test_cli_normalizes_github_sources() -> None:
    assert normalize_repo_url("https://github.com/alperensu/VibeFlow") == "https://github.com/alperensu/VibeFlow.git"
    assert normalize_repo_url("https://github.com/alperensu/VibeFlow.git") == "https://github.com/alperensu/VibeFlow.git"
    assert normalize_repo_url("alperensu/VibeFlow") == "https://github.com/alperensu/VibeFlow.git"


def test_cli_parses_setting_overrides() -> None:
    assert parse_settings(["semantic_pruning=false", "max_symbols=24", "similarity_threshold=0.12"]) == {
        "semantic_pruning": False,
        "max_symbols": 24,
        "similarity_threshold": 0.12,
    }


def test_agent_init_writes_only_selected_agent_file(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text("old", encoding="utf-8")
    (tmp_path / "GEMINI.md").write_text("old", encoding="utf-8")

    assert main(["agent", "init", "copilot", "--path", str(tmp_path)]) == 0

    assert not (tmp_path / "CLAUDE.md").exists()
    assert not (tmp_path / "GEMINI.md").exists()
    selected = tmp_path / ".github" / "copilot-instructions.md"
    assert selected.exists()
    assert "Do not add instruction files for other agents" in selected.read_text(encoding="utf-8")
