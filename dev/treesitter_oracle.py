"""Development-only oracle: the original tree-sitter based extractor.

Used by dev/compare.py and QA to measure the built-in extractor (scripts/extract.py).
Not used at runtime. Requires: pip install tree-sitter-language-pack
"""
from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------- parsing rules

EXT_LANG = {
    ".py": "python",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript", ".jsx": "javascript",
    ".ts": "typescript", ".mts": "typescript", ".cts": "typescript",
    ".tsx": "tsx",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".c": "c", ".h": "c",
    ".cc": "cpp", ".cpp": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp", ".hxx": "cpp",
    ".cs": "csharp",
}

_JS_CONTAINERS = {"class_declaration", "abstract_class_declaration", "class"}
_JS_FUNCS = {"function_declaration", "generator_function_declaration", "method_definition"}
_JS_LEAVES = {"interface_declaration", "enum_declaration"}

# containers: recorded as a row, then members are visited (the name becomes a scope prefix)
# funcs: recorded as a row; the body is not visited
# leaves: recorded as a row only
LANG_RULES = {
    "python": {
        "containers": {"class_definition"},
        "funcs": {"function_definition"},
        "leaves": set(),
    },
    "javascript": {"containers": _JS_CONTAINERS, "funcs": _JS_FUNCS, "leaves": set()},
    "typescript": {"containers": _JS_CONTAINERS, "funcs": _JS_FUNCS, "leaves": _JS_LEAVES},
    "tsx": {"containers": _JS_CONTAINERS, "funcs": _JS_FUNCS, "leaves": _JS_LEAVES},
    "go": {
        "containers": set(),
        "funcs": {"function_declaration", "method_declaration"},
        "leaves": {"type_spec"},
    },
    "rust": {
        "containers": {"impl_item", "trait_item", "mod_item"},
        "funcs": {"function_item", "function_signature_item"},
        "leaves": {"struct_item", "enum_item"},
    },
    "java": {
        "containers": {"class_declaration", "interface_declaration", "enum_declaration",
                       "record_declaration"},
        "funcs": {"method_declaration", "constructor_declaration"},
        "leaves": set(),
    },
    "c": {"containers": set(), "funcs": {"function_definition"}, "leaves": set()},
    "cpp": {
        "containers": {"class_specifier", "struct_specifier"},
        "funcs": {"function_definition"},
        "leaves": set(),
    },
    "csharp": {
        "containers": {"class_declaration", "struct_declaration", "interface_declaration",
                       "record_declaration"},
        "funcs": {"method_declaration", "constructor_declaration"},
        "leaves": {"enum_declaration"},
    },
}
_JS_FUNC_VALUES = {"arrow_function", "function_expression", "function", "generator_function"}
_C_DECLARATOR_WRAPPERS = {"pointer_declarator", "reference_declarator", "function_declarator",
                          "parenthesized_declarator"}


class ParserUnavailable(RuntimeError):
    pass


_parser_cache: dict = {}


def _get_parser(lang: str):
    if lang not in _parser_cache:
        try:
            import tree_sitter_language_pack as tslp
        except ImportError as exc:
            raise ParserUnavailable(
                "tree-sitter-language-pack is not installed: "
                "pip install tree-sitter-language-pack") from exc
        _parser_cache[lang] = tslp.get_parser(lang)
    return _parser_cache[lang]


def _text(node, src: bytes) -> str:
    return src[node.start_byte():node.end_byte()].decode("utf-8", "replace")


def _children(node):
    return [node.child(i) for i in range(node.child_count())]


def _node_name(node, lang: str, src: bytes) -> str | None:
    kind = node.kind()
    if lang in ("c", "cpp") and kind == "function_definition":
        decl = node.child_by_field_name("declarator")
        while decl is not None and decl.kind() in _C_DECLARATOR_WRAPPERS:
            decl = decl.child_by_field_name("declarator")
        return _text(decl, src) if decl is not None else None
    if lang == "rust" and kind == "impl_item":
        typ = node.child_by_field_name("type")
        trait = node.child_by_field_name("trait")
        if typ is None:
            return None
        return f"{_text(typ, src)}<{_text(trait, src)}>" if trait is not None else _text(typ, src)
    if lang == "go" and kind == "method_declaration":
        name = node.child_by_field_name("name")
        recv = node.child_by_field_name("receiver")
        recv_type = None
        if recv is not None:
            stack = [recv]
            while stack:
                cur = stack.pop()
                if cur.kind() == "type_identifier":
                    recv_type = _text(cur, src)
                    break
                stack.extend(reversed(_children(cur)))
        if name is None:
            return None
        return f"{recv_type}.{_text(name, src)}" if recv_type else _text(name, src)
    name = node.child_by_field_name("name")
    return _text(name, src) if name is not None else None


def extract_symbols(path: Path, lang: str | None = None) -> list[tuple[str, int]]:
    """Extract (name, line) pairs from a file. Lines are 1-based."""
    lang = lang or EXT_LANG.get(path.suffix.lower())
    if lang is None:
        return []
    src_text = path.read_text(encoding="utf-8", errors="replace")
    src = src_text.encode("utf-8")
    tree = _get_parser(lang).parse(src_text)
    rules = LANG_RULES[lang]
    out: list[tuple[str, int]] = []

    def emit(name: str, node, scope: list[str]) -> None:
        out.append((".".join(scope + [name]), node.start_position().row + 1))

    def visit(node, scope: list[str]) -> None:
        kind = node.kind()
        if kind in rules["containers"]:
            name = _node_name(node, lang, src)
            if name:
                emit(name, node, scope)
                scope = scope + [name]
            for child in _children(node):
                visit(child, scope)
            return
        if kind in rules["funcs"] or kind in rules["leaves"]:
            name = _node_name(node, lang, src)
            if name:
                emit(name, node, scope)
            return
        if lang in ("javascript", "typescript", "tsx") and kind == "variable_declarator":
            value = node.child_by_field_name("value")
            name = node.child_by_field_name("name")
            if value is not None and name is not None and value.kind() in _JS_FUNC_VALUES:
                emit(_text(name, src), node, scope)
            return
        if kind in _JS_FUNC_VALUES:
            return
        for child in _children(node):
            visit(child, scope)

    visit(tree.root_node(), [])
    return out
