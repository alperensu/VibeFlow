from pathlib import Path

from core.context_builder import ContextBuilder, ContextRequest
from core.indexer import ProjectIndex
from core.settings import resolve_settings


def test_context_reports_settings_and_optimization_effects(tmp_path: Path) -> None:
    service = tmp_path / "service.py"
    service.write_text(
        """
from helpers import normalize


def run(value: str) -> str:
    return normalize(value)
""".lstrip(),
        encoding="utf-8",
    )
    helpers = tmp_path / "helpers.py"
    helpers.write_text(
        """
def normalize(value: str) -> str:
    return value.strip().lower()
""".lstrip(),
        encoding="utf-8",
    )

    index = ProjectIndex(root=tmp_path)
    index.index_project()

    package = ContextBuilder(index).build(
        ContextRequest(
            project_root=tmp_path,
            current_file=Path("service.py"),
            cursor_line=4,
            intent="Make run safer",
            settings=resolve_settings("maximum_savings", {"max_symbols": 8}),
        )
    )

    assert package.stats["settings"]["semantic_pruning"] is True
    assert package.stats["symbols_indexed"] >= 2
    assert package.stats["optimization_effects"]
    assert "static_project_context" in package.context_string
    assert "cross-file called bodies" in package.context_string
    assert "def normalize(value: str) -> str:" in package.context_string


def test_context_can_disable_prompt_cache_and_diff_contract(tmp_path: Path) -> None:
    app = tmp_path / "app.py"
    app.write_text(
        """
def run():
    return 1
""".lstrip(),
        encoding="utf-8",
    )

    index = ProjectIndex(root=tmp_path)
    index.index_project()
    settings = resolve_settings(
        "maximum_savings",
        {
            "prompt_caching": False,
            "diff_only_output": False,
            "semantic_pruning": False,
        },
    )

    package = ContextBuilder(index).build(
        ContextRequest(
            project_root=tmp_path,
            current_file=Path("app.py"),
            cursor_line=1,
            intent="Inspect",
            settings=settings,
        )
    )

    assert "cache_control='ephemeral'" not in package.context_string
    assert "response_contract" not in package.prompt
    assert "anthropic-beta" not in package.prompt["headers"]
