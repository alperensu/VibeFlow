from core.sieve import parse_source


def test_python_sieve_extracts_signatures_without_bodies() -> None:
    source = """
import os


def helper(value: int) -> int:
    return value + 1


class Service:
    def run(self, value: int) -> int:
        return helper(value)
""".lstrip()

    result = parse_source(source, language="python", file_path="sample.py")

    assert result.parse_ok
    assert "import os" in result.skeleton
    assert "def helper(value: int) -> int: ..." in result.skeleton
    assert "class Service:" in result.skeleton
    assert "def run(self, value: int) -> int: ..." in result.skeleton
    assert "return value + 1" not in result.skeleton
    assert "return helper(value)" not in result.skeleton


def test_python_sieve_tracks_direct_calls_for_dynamic_context() -> None:
    source = """
def helper(value):
    return value + 1


def active(value):
    return helper(value)
""".lstrip()

    result = parse_source(source, language="python", file_path="sample.py")
    active = result.get_function_at_line(4)

    assert active is not None
    assert active.calls == {"helper"}
    assert [function.name for function in result.functions_called_by(active)] == ["helper"]
