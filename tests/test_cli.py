from vibeflow_cli import normalize_repo_url, parse_settings


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
