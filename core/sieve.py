"""
AST-based sieve for VibeFlow.

The sieve turns full source files into cheap structural context:
- imports
- class/type headers
- function and method signatures
- selected bodies only when the current task points at them

Token saving:
- Signature skeletons remove implementation bodies from the static cache.
- Call-aware lookup lets the dynamic context include only the active function
  and directly referenced functions instead of the whole file.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from tree_sitter import Language, Node, Parser

logger = logging.getLogger("vibeflow.sieve")

_LANGUAGE_CACHE: dict[str, Language] = {}


def _get_language(lang_name: str) -> Language:
    if lang_name in _LANGUAGE_CACHE:
        return _LANGUAGE_CACHE[lang_name]

    if lang_name == "python":
        import tree_sitter_python as tspython

        raw_language = tspython.language()
    elif lang_name == "javascript":
        import tree_sitter_javascript as tsjavascript

        raw_language = tsjavascript.language()
    else:
        raise ValueError(f"Unsupported language: {lang_name}")

    try:
        language = Language(raw_language)
    except TypeError:
        language = raw_language

    _LANGUAGE_CACHE[lang_name] = language
    return language


def _make_parser(lang_name: str) -> Parser:
    language = _get_language(lang_name)
    parser = Parser()
    if hasattr(parser, "set_language"):
        parser.set_language(language)
    else:
        parser.language = language
    return parser


@dataclass(slots=True)
class FunctionInfo:
    name: str
    signature: str
    body: str
    start_line: int
    end_line: int
    is_method: bool = False
    decorators: list[str] = field(default_factory=list)
    calls: set[str] = field(default_factory=set)

    @property
    def skeleton(self) -> str:
        prefix = "\n".join(self.decorators)
        value = f"{self.signature} ..."
        return f"{prefix}\n{value}" if prefix else value


@dataclass(slots=True)
class TypeInfo:
    name: str
    header: str
    body: str
    start_line: int
    end_line: int
    methods: list[FunctionInfo] = field(default_factory=list)
    decorators: list[str] = field(default_factory=list)

    @property
    def skeleton(self) -> str:
        lines: list[str] = []
        if self.decorators:
            lines.extend(self.decorators)
        lines.append(self.header)
        for method in self.methods:
            for line in method.skeleton.splitlines():
                lines.append(f"    {line}")
        return "\n".join(lines)


@dataclass(slots=True)
class SieveResult:
    file_path: str
    language: str
    functions: list[FunctionInfo] = field(default_factory=list)
    types: list[TypeInfo] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    parse_ok: bool = True

    @property
    def skeleton(self) -> str:
        sections: list[str] = []
        if self.imports:
            sections.append("\n".join(self.imports))

        sections.extend(type_info.skeleton for type_info in self.types)

        method_ranges = {(m.start_line, m.end_line) for t in self.types for m in t.methods}
        for function in self.functions:
            if (function.start_line, function.end_line) not in method_ranges:
                sections.append(function.skeleton)

        return "\n\n".join(section for section in sections if section.strip()).strip()

    def get_function_at_line(self, line: int) -> FunctionInfo | None:
        for function in self.functions:
            if function.start_line <= line <= function.end_line:
                return function
        return None

    def functions_called_by(self, function: FunctionInfo) -> list[FunctionInfo]:
        names = function.calls
        return [candidate for candidate in self.functions if candidate.name in names]


def _node_text(node: Node | None, source: bytes) -> str:
    if node is None:
        return ""
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _children(node: Node) -> Iterable[Node]:
    for child in node.children:
        yield child


def _walk(node: Node) -> Iterable[Node]:
    yield node
    for child in node.children:
        yield from _walk(child)


def _unwrap_decorated(node: Node) -> Node:
    if node.type != "decorated_definition":
        return node
    for child in node.children:
        if child.type in {"function_definition", "class_definition"}:
            return child
    return node


def _decorators_for(node: Node, source: bytes) -> list[str]:
    parent = node.parent
    if not parent or parent.type != "decorated_definition":
        return []
    return [_node_text(child, source) for child in parent.children if child.type == "decorator"]


def _signature_before_body(node: Node, source: bytes) -> tuple[str, str]:
    body_node = node.child_by_field_name("body")
    if body_node is None:
        first_line = _node_text(node, source).splitlines()[0] if _node_text(node, source) else ""
        return first_line.strip(), ""

    signature = source[node.start_byte : body_node.start_byte].decode("utf-8", errors="replace").strip()
    body = _node_text(body_node, source)
    return signature, body


def _extract_calls_python(node: Node, source: bytes) -> set[str]:
    calls: set[str] = set()
    for child in _walk(node):
        if child.type != "call":
            continue
        function_node = child.child_by_field_name("function")
        if function_node is None:
            continue
        if function_node.type == "identifier":
            calls.add(_node_text(function_node, source))
        elif function_node.type == "attribute":
            attribute = function_node.child_by_field_name("attribute")
            if attribute is not None:
                calls.add(_node_text(attribute, source))
    return calls


def _extract_function_python(node: Node, source: bytes, is_method: bool = False) -> FunctionInfo:
    name = _node_text(node.child_by_field_name("name"), source) or "<anonymous>"
    signature, body = _signature_before_body(node, source)
    return FunctionInfo(
        name=name,
        signature=signature,
        body=body,
        start_line=node.start_point[0],
        end_line=node.end_point[0],
        is_method=is_method,
        decorators=_decorators_for(node, source),
        calls=_extract_calls_python(node, source),
    )


def _extract_class_python(node: Node, source: bytes) -> TypeInfo:
    name = _node_text(node.child_by_field_name("name"), source) or "<anonymous>"
    header, body = _signature_before_body(node, source)
    methods: list[FunctionInfo] = []

    body_node = node.child_by_field_name("body")
    if body_node is not None:
        for child in _children(body_node):
            actual = _unwrap_decorated(child)
            if actual.type == "function_definition":
                methods.append(_extract_function_python(actual, source, is_method=True))

    return TypeInfo(
        name=name,
        header=header,
        body=body,
        start_line=node.start_point[0],
        end_line=node.end_point[0],
        methods=methods,
        decorators=_decorators_for(node, source),
    )


def _extract_imports_python(root: Node, source: bytes) -> list[str]:
    return [
        _node_text(child, source)
        for child in root.children
        if child.type in {"import_statement", "import_from_statement"}
    ]


def _walk_python(root: Node, source: bytes, result: SieveResult) -> None:
    for child in root.children:
        actual = _unwrap_decorated(child)
        if actual.type == "function_definition":
            result.functions.append(_extract_function_python(actual, source))
        elif actual.type == "class_definition":
            type_info = _extract_class_python(actual, source)
            result.types.append(type_info)
            result.functions.extend(type_info.methods)


def _parse_bytes(source: bytes, language: str, file_path: str) -> SieveResult:
    result = SieveResult(file_path=file_path, language=language)
    try:
        parser = _make_parser(language)
        tree = parser.parse(source)
    except Exception as exc:  # pragma: no cover - depends on native grammar install
        result.parse_ok = False
        result.warnings.append(f"nonsense: AST parse failed ({exc}); using smart chunking fallback")
        return result

    root = tree.root_node
    if root.has_error:
        result.parse_ok = False
        result.warnings.append("nonsense: syntax errors detected; using smart chunking fallback")
        return result

    if language == "python":
        result.imports = _extract_imports_python(root, source)
        _walk_python(root, source, result)
    else:
        result.parse_ok = False
        result.warnings.append(f"nonsense: extractor for {language!r} is not implemented")

    return result


def parse_file(file_path: str | Path, language: str = "python") -> SieveResult:
    path = Path(file_path)
    result = SieveResult(file_path=str(path), language=language)
    if not path.exists():
        result.parse_ok = False
        result.warnings.append(f"nonsense: file not found: {path}")
        return result

    source = path.read_bytes()
    from config import MAX_FILE_SIZE

    if len(source) > MAX_FILE_SIZE:
        result.parse_ok = False
        result.warnings.append(
            f"nonsense: file too large ({len(source)} bytes > {MAX_FILE_SIZE}); using smart chunking fallback"
        )
        return result

    return _parse_bytes(source, language, str(path))


def parse_source(source: str, language: str = "python", file_path: str = "<string>") -> SieveResult:
    return _parse_bytes(source.encode("utf-8"), language, file_path)
