#!/usr/bin/env python3
"""claude-librarian: CLI that maintains per-folder documents (CLAUDE.md / AGENTS.md).

Each document separates the part written by humans/LLMs (folder role, subfolder table) from
the part written by this script (the index marker block). The index records only
file · function · line and never describes what a function does.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_DIR = ".librarian"
CONFIG_FILE = "config.json"
GUIDE_SKILL = "librarian-guide"
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = PLUGIN_ROOT / "templates" / GUIDE_SKILL

INDEX_START = "<!-- librarian:index:start -->"
INDEX_END = "<!-- librarian:index:end -->"

# Generated document text per library language. Languages without an entry use English
# headings; the role text itself is still written in the configured language.
DOC_STRINGS = {
    "en": {
        "parent": "# Parent: ../{doc}",
        "root_note": "This repository follows the rules of the `librarian-guide` skill.",
        "role": "## What this folder is for",
        "subdirs": "## Subfolders",
        "placeholder": "_(to be written)_",
        "subdir_header": ("Folder", "Role"),
        "index_header": ("File", "Function", "Line"),
    },
    "ko": {
        "parent": "# 상위 문서: ../{doc}",
        "root_note": "이 저장소는 `librarian-guide` 스킬의 규칙을 따릅니다.",
        "role": "## 이 폴더의 역할",
        "subdirs": "## 하위 폴더",
        "placeholder": "_(작성 필요)_",
        "subdir_header": ("폴더", "역할"),
        "index_header": ("파일", "함수", "줄"),
    },
}
ROLE_HEADINGS = {s["role"] for s in DOC_STRINGS.values()}
SUBDIR_HEADINGS = {s["subdirs"] for s in DOC_STRINGS.values()}
PLACEHOLDERS = {s["placeholder"] for s in DOC_STRINGS.values()}
ROOT_NOTES = {s["root_note"] for s in DOC_STRINGS.values()}
SUBDIR_HEADER_CELLS = {s["subdir_header"][0] for s in DOC_STRINGS.values()}
PARENT_RE = re.compile(
    "^(?:" + "|".join(re.escape(s["parent"].split("{doc}")[0]) for s in DOC_STRINGS.values())
    + r")\S+\s*$")

SKILL_TARGETS = {
    "claude": Path(".claude") / "skills",
    "agents": Path(".agents") / "skills",
    "codex": Path(".codex") / "skills",
}
DEFAULT_EXCLUDE = [
    "node_modules", "dist", "build", "out", "target", "vendor",
    "venv", "__pycache__", "coverage",
]
DEFAULT_CONFIG = {
    "language": "en",
    "docName": "CLAUDE.md",
    "targets": ["claude", "agents", "codex"],
    "exclude": [],
    "maxEntries": 60,
    "maxDepth": 6,
}

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


def extract_symbols(path: Path) -> list[tuple[str, int]]:
    """Extract (name, line) pairs from a file. Lines are 1-based."""
    lang = EXT_LANG.get(path.suffix.lower())
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


# ---------------------------------------------------------------- config / paths


@dataclass
class Library:
    root: Path
    config: dict = field(default_factory=dict)

    @property
    def doc_mode(self) -> str:
        return self.config.get("docName", "CLAUDE.md")

    @property
    def primary_doc(self) -> str:
        return "AGENTS.md" if self.doc_mode in ("AGENTS.md", "both") else "CLAUDE.md"

    @property
    def doc_names(self) -> set[str]:
        return {"CLAUDE.md", "AGENTS.md"} if self.doc_mode == "both" else {self.primary_doc}

    def doc_path(self, d: Path) -> Path:
        return d / self.primary_doc

    @property
    def language(self) -> str:
        return str(self.config.get("language") or "en")

    @property
    def strings(self) -> dict:
        return DOC_STRINGS.get(self.language.lower(), DOC_STRINGS["en"])

    def rel(self, p: Path) -> str:
        try:  # try without resolve first so links (junctions) are not followed
            r = Path(os.path.abspath(p)).relative_to(self.root).as_posix()
        except ValueError:
            r = p.resolve().relative_to(self.root).as_posix()
        return "." if r == "" else r


def find_root(start: Path) -> Path | None:
    cur = start.resolve()
    for cand in [cur, *cur.parents]:
        if (cand / CONFIG_DIR / CONFIG_FILE).is_file():
            return cand
    return None


def load_library(start: Path) -> Library | None:
    root = find_root(start)
    if root is None:
        return None
    cfg = dict(DEFAULT_CONFIG)
    cfg.update(json.loads((root / CONFIG_DIR / CONFIG_FILE).read_text(encoding="utf-8")))
    return Library(root=root, config=cfg)


def _is_excluded(lib: Library, rel_parts: tuple[str, ...]) -> bool:
    patterns = DEFAULT_EXCLUDE + list(lib.config.get("exclude", []))
    rel = "/".join(rel_parts)
    for part in rel_parts[:-1] if rel_parts else ():
        if part.startswith("."):
            return True
    for pat in patterns:
        if any(fnmatch.fnmatch(part, pat) for part in rel_parts[:-1]):
            return True
        if fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(rel, pat.rstrip("/") + "/*"):
            return True
    return False


def _git(root: Path, *args: str) -> str | None:
    try:
        res = subprocess.run(["git", *args], cwd=root, capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if res.returncode != 0:
        return None
    return res.stdout.decode("utf-8", "replace")


def list_files(lib: Library) -> list[Path]:
    """Managed files, after exclude patterns and .gitignore are applied."""
    out = _git(lib.root, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
    rels: list[str]
    if out is not None:
        rels = [r for r in out.split("\0") if r]
    else:
        rels = []
        for dirpath, dirnames, filenames in os.walk(lib.root):
            rel_dir = Path(dirpath).relative_to(lib.root)
            dirnames[:] = [
                d for d in dirnames
                if not _is_excluded(lib, tuple((rel_dir / d / "_").parts))
            ]
            rels.extend((rel_dir / f).as_posix() for f in filenames)
    files = []
    for r in rels:
        parts = tuple(Path(r).parts)
        if _is_excluded(lib, parts):
            continue
        p = lib.root / r
        if p.is_file():
            files.append(p)
    return files


def managed_dirs(lib: Library, files: list[Path]) -> set[Path]:
    dirs = {lib.root}
    for f in files:
        for parent in f.parents:
            if parent == lib.root or lib.root not in parent.parents:
                break
            dirs.add(parent)
    return dirs


def _escape(cell: str) -> str:
    return cell.replace("|", "\\|")


# ---------------------------------------------------------------- documents


def _split_sections(text: str) -> dict:
    """Split a document into head / role / subdirs / index / tail."""
    lines = text.splitlines()
    sections = {"head": [], "role": None, "subdirs": None, "index": None, "tail": []}
    cur = "head"
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped == INDEX_START:
            j = i
            while j < len(lines) and lines[j].strip() != INDEX_END:
                j += 1
            sections["index"] = lines[i:j + 1]
            cur = "tail"
            i = j + 1
            continue
        if stripped in ROLE_HEADINGS:
            sections["role"] = []
            cur = "role"
        elif stripped in SUBDIR_HEADINGS:
            sections["subdirs"] = []
            cur = "subdirs"
        elif stripped.startswith("## ") or stripped.startswith("# "):
            if cur in ("role", "subdirs"):
                cur = "tail"
            sections[cur].append(line)
            i += 1
            continue
        else:
            sections[cur].append(line)
        i += 1
    return sections


def _role_is_empty(role_lines: list[str] | None) -> bool:
    if role_lines is None:
        return True
    body = "\n".join(role_lines)
    for ph in PLACEHOLDERS:
        body = body.replace(ph, "")
    return body.strip() == ""


def _parse_subdir_rows(lines: list[str]) -> list[tuple[str, str]]:
    rows = []
    for line in lines:
        s = line.strip()
        if not s.startswith("|") or set(s) <= set("|-: "):
            continue
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", s)[1:-1]]
        if len(cells) < 2 or cells[0] in SUBDIR_HEADER_CELLS:
            continue
        rows.append((cells[0].rstrip("/"), cells[1]))
    return rows


def render_doc(lib: Library, d: Path, role: list[str], subdirs: list[tuple[str, str]],
               index_rows: list[tuple[str, str, str]], head: list[str], tail: list[str]) -> str:
    s = lib.strings
    placeholder = s["placeholder"]
    role_text = "\n".join(role).strip()
    if role_text in PLACEHOLDERS:
        role_text = ""
    parts: list[str] = []
    parts.append("\n".join(head).rstrip())
    parts.append(s["role"] + "\n\n" + (role_text or placeholder))
    if subdirs:
        table = ["| {} | {} |".format(*s["subdir_header"]), "|---|---|"]
        table += [f"| {_escape(n)}/ | {placeholder if r in PLACEHOLDERS or not r else r} |"
                  for n, r in subdirs]
        parts.append(s["subdirs"] + "\n\n" + "\n".join(table))
    extra = "\n".join(tail).strip()
    if extra:
        parts.append(extra)
    if index_rows:
        table = [INDEX_START, "| {} | {} | {} |".format(*s["index_header"]), "|---|---|---|"]
        table += [f"| {_escape(f)} | {_escape(s)} | {ln} |" for f, s, ln in index_rows]
        table.append(INDEX_END)
        parts.append("\n".join(table))
    return "\n\n".join(p for p in parts if p) + "\n"


def default_head(lib: Library, d: Path) -> list[str]:
    if d == lib.root:
        return [f"# {lib.root.name}", "", lib.strings["root_note"]]
    return [lib.strings["parent"].format(doc=lib.primary_doc)]


def normalize_head(lib: Library, d: Path, head: list[str]) -> list[str]:
    """Rewrite the generated lines of the head (parent link, root note) in the current
    language and doc name, keeping everything else the user wrote."""
    if not head or not "".join(head).strip():
        return default_head(lib, d)
    out = []
    for line in head:
        stripped = line.strip()
        if d != lib.root and PARENT_RE.match(stripped):
            out.append(lib.strings["parent"].format(doc=lib.primary_doc))
        elif d == lib.root and stripped in ROOT_NOTES:
            out.append(lib.strings["root_note"])
        else:
            out.append(line)
    return out


@dataclass
class Report:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    drift: list[str] = field(default_factory=list)

    def merge(self, other: "Report") -> None:
        for k in self.__dataclass_fields__:
            getattr(self, k).extend(getattr(other, k))


def build_index_rows(lib: Library, d: Path, files: list[Path], report: Report):
    rows = []
    for f in sorted((f for f in files if f.parent == d), key=lambda p: p.name.lower()):
        if f.name in lib.doc_names or f.suffix.lower() not in EXT_LANG:
            continue
        try:
            symbols = extract_symbols(f)
        except ParserUnavailable:
            raise
        except Exception as exc:  # a parse failure skips only that file
            report.warnings.append(f"{lib.rel(f)}: parse failed ({exc})")
            continue
        if not symbols:
            rows.append((f.name, "-", "-"))
        rows.extend((f.name, name, str(line)) for name, line in symbols)
    return rows


def sync_dir(lib: Library, d: Path, files: list[Path], dirs: set[Path], fix: bool) -> Report:
    """Bring one folder's document in line with the tree. With fix=False, only report."""
    report = Report()
    rel = lib.rel(d)
    doc = lib.doc_path(d)
    existed = doc.is_file()
    original = doc.read_text(encoding="utf-8") if existed else ""
    sec = _split_sections(original) if existed else {
        "head": [], "role": None, "subdirs": None, "index": None, "tail": []}
    sec["head"] = normalize_head(lib, d, sec["head"])

    child_dirs = sorted((c for c in dirs if c.parent == d), key=lambda p: p.name.lower())
    known = dict(_parse_subdir_rows(sec["subdirs"] or []))
    subdirs = [(c.name, known.get(c.name, "")) for c in child_dirs]
    index_rows = build_index_rows(lib, d, files, report)

    rendered = render_doc(lib, d, sec["role"] or [], subdirs, index_rows, sec["head"], sec["tail"])
    if rendered != original:
        if not existed:
            (report.created if fix else report.drift).append(rel)
        else:
            (report.updated if fix else report.drift).append(rel)
        if fix:
            doc.write_text(rendered, encoding="utf-8", newline="\n")
    if fix and lib.doc_mode == "both":
        alias = d / "CLAUDE.md"
        if not alias.is_file():
            alias.write_text("@AGENTS.md\n", encoding="utf-8", newline="\n")

    if _role_is_empty(sec["role"]) or any(not r or r in PLACEHOLDERS for _, r in subdirs):
        report.pending.append(rel)
    depth = 0 if d == lib.root else len(d.relative_to(lib.root).parts)
    if depth > int(lib.config["maxDepth"]):
        report.warnings.append(
            f"{rel}: folder depth {depth} > {lib.config['maxDepth']} (consider restructuring)")
    if len(index_rows) > int(lib.config["maxEntries"]):
        report.warnings.append(
            f"{rel}: {len(index_rows)} index rows > {lib.config['maxEntries']} "
            "(consider splitting into subfolders)")
    return report


def sync_dirs(lib: Library, targets: set[Path] | None, fix: bool) -> Report:
    files = list_files(lib)
    dirs = managed_dirs(lib, files)
    report = Report()
    if targets is None:
        todo = dirs
    else:
        todo = set()
        for t in targets:
            # a folder that no longer exists is replaced by its nearest existing ancestor
            if t != lib.root and lib.root not in t.parents:
                continue
            cur = t
            while cur != lib.root and cur not in dirs:
                cur = cur.parent
            todo.add(cur)
            if cur != lib.root:
                todo.add(cur.parent)
            # for a new folder, also create documents for ancestors that lack one
            for anc in cur.parents:
                if anc in dirs and not lib.doc_path(anc).is_file():
                    todo.add(anc)
                if anc == lib.root:
                    break
    for d in sorted(todo, key=lambda p: len(p.parts), reverse=True):
        report.merge(sync_dir(lib, d, files, dirs, fix))
    return report


def changed_dirs(lib: Library) -> set[Path] | None:
    out = _git(lib.root, "status", "--porcelain", "-z", "--untracked-files=all")
    if out is None:
        return None
    paths: set[Path] = set()
    entries = out.split("\0")
    i = 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if len(entry) < 4:
            continue
        status, rel = entry[:2], entry[3:]
        paths.add((lib.root / rel).parent)
        if "R" in status or "C" in status:  # rename: the next entry is the original path
            if i < len(entries) and entries[i]:
                paths.add((lib.root / entries[i]).parent)
            i += 1
    return paths


# ---------------------------------------------------------------- skill links


def _same_tree(a: Path, b: Path) -> bool:
    if not a.is_dir() or not b.is_dir():
        return False
    fa = sorted(p.relative_to(a).as_posix() for p in a.rglob("*") if p.is_file())
    fb = sorted(p.relative_to(b).as_posix() for p in b.rglob("*") if p.is_file())
    return fa == fb and all((a / f).read_bytes() == (b / f).read_bytes() for f in fa)


def _is_link(p: Path) -> bool:
    if p.is_symlink():
        return True
    isjunction = getattr(os.path, "isjunction", None)
    if isjunction is not None:
        return isjunction(p)
    try:
        os.readlink(p)
        return True
    except (OSError, ValueError):
        return False


def _remove(p: Path) -> None:
    if _is_link(p):
        try:
            os.unlink(p)
        except OSError:
            os.rmdir(p)  # Windows junction
    elif p.is_dir():
        shutil.rmtree(p)
    elif p.exists():
        p.unlink()


def _link_dir(src: Path, dest: Path) -> str:
    """Link a directory, falling back to a copy. Returns the method used."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        try:
            import _winapi
            _winapi.CreateJunction(str(src), str(dest))
            return "junction"
        except Exception:
            pass
    else:
        try:
            os.symlink(os.path.relpath(src, dest.parent), dest, target_is_directory=True)
            return "symlink"
        except OSError:
            pass
    shutil.copytree(src, dest)
    return "copy"


def skill_source(lib: Library) -> Path:
    return lib.root / CONFIG_DIR / "skills" / GUIDE_SKILL


def check_skills(lib: Library, fix: bool) -> Report:
    report = Report()
    src = skill_source(lib)
    if not src.is_dir():
        if not fix:
            report.drift.append(f"{lib.rel(src)} is missing")
            return report
        shutil.copytree(TEMPLATE_DIR, src)
        report.created.append(lib.rel(src))
    for target in lib.config.get("targets", []):
        if target not in SKILL_TARGETS:
            report.warnings.append(f"unknown skill target: {target}")
            continue
        dest = lib.root / SKILL_TARGETS[target] / GUIDE_SKILL
        ok = False
        if _is_link(dest):
            ok = dest.resolve() == src.resolve()
        elif dest.is_dir():
            ok = _same_tree(src, dest)
        if ok:
            continue
        if not fix:
            report.drift.append(f"{lib.rel(dest)} link is broken or content differs")
            continue
        if dest.exists() or _is_link(dest):
            _remove(dest)
        how = _link_dir(src, dest)
        report.updated.append(f"{lib.rel(dest)} ({how})")
    return report


def _ensure_gitignore(lib: Library) -> None:
    lines = [f"/{(SKILL_TARGETS[t] / GUIDE_SKILL).as_posix()}"
             for t in lib.config.get("targets", []) if t in SKILL_TARGETS]
    gi = lib.root / ".gitignore"
    current = gi.read_text(encoding="utf-8").splitlines() if gi.is_file() else []
    missing = [l for l in lines if l not in current]
    if not missing:
        return
    comment = "# claude-librarian: skill links (restored automatically by check)"
    block = ["", comment] if current else [comment]
    gi.write_text("\n".join(current + block + missing) + "\n", encoding="utf-8", newline="\n")


# ---------------------------------------------------------------- hooks


def _paths_from_hook(payload: dict, cwd: Path) -> list[Path]:
    tool_input = payload.get("tool_input") or {}
    paths: list[str] = []
    for key in ("file_path", "path"):
        if isinstance(tool_input.get(key), str):
            paths.append(tool_input[key])
    for edit in tool_input.get("edits", []) if isinstance(tool_input.get("edits"), list) else []:
        if isinstance(edit, dict) and isinstance(edit.get("file_path"), str):
            paths.append(edit["file_path"])
    patch = tool_input.get("command") or tool_input.get("patch") or tool_input.get("input")
    if isinstance(patch, list):
        patch = "\n".join(str(x) for x in patch)
    if isinstance(patch, str):
        for m in re.finditer(r"^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+?)\s*$",
                             patch, re.MULTILINE):
            paths.append(m.group(1))
    return [(cwd / p).resolve() if not Path(p).is_absolute() else Path(p).resolve()
            for p in paths]


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=True) + "\n")


def hook_post_edit(payload: dict) -> None:
    cwd = Path(payload.get("cwd") or os.getcwd())
    lib = load_library(cwd)
    if lib is None:
        return
    targets = set()
    for p in _paths_from_hook(payload, cwd):
        if lib.root not in p.parents or p.name in lib.doc_names:
            continue
        rel_parts = p.relative_to(lib.root).parts
        if _is_excluded(lib, tuple(rel_parts)):
            continue
        targets.add(p.parent)
    if not targets:
        return
    report = sync_dirs(lib, targets, fix=True)
    msgs = []
    if report.created:
        msgs.append(
            f"librarian: new folder documents were created: {', '.join(report.created)}. "
            f"Fill in '{lib.strings['role']}' in each of them and the role cell in the parent "
            f"document's subfolder table. Write in the library language ({lib.language}). "
            "Do not describe functions.")
    if report.warnings:
        msgs.append("librarian warning: " + "; ".join(report.warnings))
    if msgs:
        _emit({"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                      "additionalContext": "\n".join(msgs)}})


def hook_stop(payload: dict) -> None:
    cwd = Path(payload.get("cwd") or os.getcwd())
    lib = load_library(cwd)
    if lib is None:
        _emit({})
        return
    report = check_skills(lib, fix=True)
    changed = changed_dirs(lib)
    report.merge(sync_dirs(lib, changed, fix=True))
    out: dict = {}
    if report.warnings:
        out["systemMessage"] = "librarian: " + "; ".join(report.warnings)
    if report.pending and not payload.get("stop_hook_active"):
        out["decision"] = "block"
        out["reason"] = (
            f"librarian: these folder documents have an empty '{lib.strings['role']}' section "
            f"or empty role cells in the subfolder table: {', '.join(report.pending)}. "
            f"Read the code and fill them in, in the library language ({lib.language}). "
            "Do not describe functions or files, and do not edit the index marker block.")
    _emit(out)


# ---------------------------------------------------------------- CLI


def _require(start: Path) -> Library:
    lib = load_library(start)
    if lib is None:
        sys.exit(f"{CONFIG_DIR}/{CONFIG_FILE} not found. Run init first.")
    return lib


def _print_report(report: Report) -> None:
    for label, items in (("created", report.created), ("updated", report.updated),
                         ("drift", report.drift), ("role needed", report.pending),
                         ("warning", report.warnings), ("error", report.errors)):
        for item in items:
            print(f"[{label}] {item}")


def cmd_init(args) -> None:
    root = Path(args.root).resolve()
    cfg_path = root / CONFIG_DIR / CONFIG_FILE
    cfg = dict(DEFAULT_CONFIG)
    if cfg_path.is_file():
        cfg.update(json.loads(cfg_path.read_text(encoding="utf-8")))
    cfg["docName"] = args.doc
    if args.language:
        cfg["language"] = args.language
    if args.targets is not None:
        cfg["targets"] = [t for t in args.targets.split(",") if t]
    if args.exclude:
        cfg["exclude"] = sorted(set(cfg.get("exclude", [])) | set(args.exclude))
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lib = Library(root=root, config=cfg)
    report = check_skills(lib, fix=True)
    _ensure_gitignore(lib)
    print(f"[config] {lib.rel(cfg_path)}")
    _print_report(report)


def cmd_sync_skills(args) -> None:
    _print_report(check_skills(_require(Path(args.root)), fix=True))


def cmd_scaffold(args) -> None:
    lib = _require(Path(args.root))
    files = list_files(lib)
    dirs = managed_dirs(lib, files)
    report = Report()
    for d in sorted(dirs, key=lambda p: len(p.parts), reverse=True):
        if not lib.doc_path(d).is_file():
            report.merge(sync_dir(lib, d, files, dirs, fix=True))
    _print_report(Report(created=report.created, warnings=report.warnings))


def cmd_index(args) -> None:
    lib = _require(Path(args.root))
    targets = None if args.all else {Path(p).resolve() for p in args.dirs}
    if targets is not None and not targets:
        sys.exit("Specify folders or use --all.")
    report = sync_dirs(lib, targets, fix=True)
    _print_report(Report(created=report.created, updated=report.updated,
                         warnings=report.warnings))


def cmd_check(args) -> None:
    lib = _require(Path(args.root))
    report = check_skills(lib, fix=args.fix)
    targets = changed_dirs(lib) if args.changed else None
    report.merge(sync_dirs(lib, targets, fix=args.fix))
    _print_report(report)
    if report.drift or report.pending:
        sys.exit(1)


def cmd_pending(args) -> None:
    lib = _require(Path(args.root))
    report = sync_dirs(lib, None, fix=False)
    for rel in sorted(report.pending, key=lambda r: (-len(Path(r).parts), r)):
        print(rel)


def cmd_hook(args) -> None:
    raw = sys.stdin.buffer.read().decode("utf-8", "replace")
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        payload = {}
    try:
        if args.event == "post-edit":
            hook_post_edit(payload)
        else:
            hook_stop(payload)
    except ParserUnavailable as exc:
        print(f"librarian: {exc}", file=sys.stderr)
        if args.event == "stop":
            _emit({})
    except Exception as exc:  # hooks never block the editing flow
        print(f"librarian hook error: {exc!r}", file=sys.stderr)
        if args.event == "stop":
            _emit({})


def main(argv: list[str] | None = None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="librarian")
    parser.add_argument("--root", default=".", help="project root or any path inside it")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init")
    p.add_argument("--language", help="library language, e.g. en, ko (default: en)")
    p.add_argument("--doc", choices=["CLAUDE.md", "AGENTS.md", "both"], default="CLAUDE.md")
    p.add_argument("--targets", help="comma-separated: claude,agents,codex")
    p.add_argument("--exclude", nargs="*", default=[])
    p.set_defaults(func=cmd_init)

    sub.add_parser("sync-skills").set_defaults(func=cmd_sync_skills)
    sub.add_parser("scaffold").set_defaults(func=cmd_scaffold)

    p = sub.add_parser("index")
    p.add_argument("dirs", nargs="*")
    p.add_argument("--all", action="store_true")
    p.set_defaults(func=cmd_index)

    p = sub.add_parser("check")
    p.add_argument("--fix", action="store_true")
    p.add_argument("--changed", action="store_true")
    p.set_defaults(func=cmd_check)

    sub.add_parser("pending").set_defaults(func=cmd_pending)

    p = sub.add_parser("hook")
    p.add_argument("event", choices=["post-edit", "stop"])
    p.set_defaults(func=cmd_hook)

    args = parser.parse_args(argv)
    try:
        args.func(args)
    except ParserUnavailable as exc:
        sys.exit(str(exc))


if __name__ == "__main__":
    main()
