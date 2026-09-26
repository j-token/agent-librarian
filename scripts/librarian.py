#!/usr/bin/env python3
"""claude-librarian: 폴더별 문서(CLAUDE.md / AGENTS.md)를 관리하는 CLI.

사람/LLM이 쓰는 영역(폴더 역할, 하위 폴더 표)과 스크립트가 쓰는 영역(인덱스 마커 블록)을
분리한다. 인덱스에는 파일 · 함수 · 줄만 기록하며 함수 설명은 기록하지 않는다.
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
ROLE_HEADING = "## 이 폴더의 역할"
SUBDIR_HEADING = "## 하위 폴더"
PLACEHOLDER = "_(작성 필요)_"
ROOT_NOTE = "이 저장소는 `librarian-guide` 스킬의 규칙을 따릅니다."

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
    "docName": "CLAUDE.md",
    "targets": ["claude", "agents", "codex"],
    "exclude": [],
    "maxEntries": 60,
    "maxDepth": 6,
}

# ---------------------------------------------------------------- 언어 규칙

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

# containers: 행으로 기록하고 내부 멤버까지 내려간다 (이름이 범위 접두어가 됨)
# funcs: 행으로 기록하고 본문으로는 내려가지 않는다
# leaves: 행으로만 기록한다
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
                "tree-sitter-language-pack이 설치되어 있지 않습니다: "
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
    """파일에서 (이름, 줄 번호) 목록을 추출한다. 줄 번호는 1부터 센다."""
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


# ---------------------------------------------------------------- 설정 / 경로


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

    def rel(self, p: Path) -> str:
        try:  # 링크(정션)를 따라가지 않도록 resolve 없이 먼저 시도
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
    """관리 대상 파일 목록 (제외 규칙과 .gitignore 적용)."""
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


# ---------------------------------------------------------------- 문서 조작


def _split_sections(text: str) -> dict:
    """문서를 머리말 / 역할 / 하위 폴더 / 인덱스 / 기타로 나눈다."""
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
        if stripped == ROLE_HEADING:
            sections["role"] = []
            cur = "role"
        elif stripped == SUBDIR_HEADING:
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
    body = "\n".join(role_lines).replace(PLACEHOLDER, "").strip()
    return body == ""


def _parse_subdir_rows(lines: list[str]) -> list[tuple[str, str]]:
    rows = []
    for line in lines:
        s = line.strip()
        if not s.startswith("|") or set(s) <= set("|-: "):
            continue
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", s)[1:-1]]
        if len(cells) < 2 or cells[0] == "폴더":
            continue
        rows.append((cells[0].rstrip("/"), cells[1]))
    return rows


def render_doc(lib: Library, d: Path, role: list[str], subdirs: list[tuple[str, str]],
               index_rows: list[tuple[str, str, str]], head: list[str], tail: list[str]) -> str:
    parts: list[str] = []
    parts.append("\n".join(head).rstrip())
    parts.append(ROLE_HEADING + "\n\n" + ("\n".join(role).strip() or PLACEHOLDER))
    if subdirs:
        table = ["| 폴더 | 역할 |", "|---|---|"]
        table += [f"| {_escape(n)}/ | {r or PLACEHOLDER} |" for n, r in subdirs]
        parts.append(SUBDIR_HEADING + "\n\n" + "\n".join(table))
    extra = "\n".join(tail).strip()
    if extra:
        parts.append(extra)
    if index_rows:
        table = [INDEX_START, "| 파일 | 함수 | 줄 |", "|---|---|---|"]
        table += [f"| {_escape(f)} | {_escape(s)} | {ln} |" for f, s, ln in index_rows]
        table.append(INDEX_END)
        parts.append("\n".join(table))
    return "\n\n".join(p for p in parts if p) + "\n"


def default_head(lib: Library, d: Path) -> list[str]:
    if d == lib.root:
        return [f"# {lib.root.name}", "", ROOT_NOTE]
    return [f"# 상위 문서: ../{lib.primary_doc}"]


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
        except Exception as exc:  # 파싱 실패는 해당 파일만 건너뛴다
            report.warnings.append(f"{lib.rel(f)}: 파싱 실패 ({exc})")
            continue
        if not symbols:
            rows.append((f.name, "-", "-"))
        rows.extend((f.name, name, str(line)) for name, line in symbols)
    return rows


def sync_dir(lib: Library, d: Path, files: list[Path], dirs: set[Path], fix: bool) -> Report:
    """폴더 하나의 문서를 실제 상태와 맞춘다. fix=False면 차이만 보고한다."""
    report = Report()
    rel = lib.rel(d)
    doc = lib.doc_path(d)
    existed = doc.is_file()
    original = doc.read_text(encoding="utf-8") if existed else ""
    sec = _split_sections(original) if existed else {
        "head": default_head(lib, d), "role": None, "subdirs": None, "index": None, "tail": []}
    if not sec["head"] or not "".join(sec["head"]).strip():
        sec["head"] = default_head(lib, d)

    child_dirs = sorted((c for c in dirs if c.parent == d), key=lambda p: p.name.lower())
    known = dict(_parse_subdir_rows(sec["subdirs"] or []))
    subdirs = [(c.name, known.get(c.name, PLACEHOLDER)) for c in child_dirs]
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

    if _role_is_empty(sec["role"]) or any(r in ("", PLACEHOLDER) for _, r in subdirs):
        report.pending.append(rel)
    depth = 0 if d == lib.root else len(d.relative_to(lib.root).parts)
    if depth > int(lib.config["maxDepth"]):
        report.warnings.append(f"{rel}: 폴더 깊이 {depth} > {lib.config['maxDepth']} (구조 재편 권고)")
    if len(index_rows) > int(lib.config["maxEntries"]):
        report.warnings.append(
            f"{rel}: 인덱스 {len(index_rows)}행 > {lib.config['maxEntries']} (하위 폴더로 분리 권고)")
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
            # 사라진 폴더는 존재하는 가장 가까운 조상 폴더로 대체한다
            if t != lib.root and lib.root not in t.parents:
                continue
            cur = t
            while cur != lib.root and cur not in dirs:
                cur = cur.parent
            todo.add(cur)
            if cur != lib.root:
                todo.add(cur.parent)
            # 새로 생긴 폴더라면 문서 없는 조상 폴더도 함께 만든다
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
        if "R" in status or "C" in status:  # 이름 변경: 다음 항목이 원래 경로
            if i < len(entries) and entries[i]:
                paths.add((lib.root / entries[i]).parent)
            i += 1
    return paths


# ---------------------------------------------------------------- 스킬 연결


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
            os.rmdir(p)  # Windows 정션
    elif p.is_dir():
        shutil.rmtree(p)
    elif p.exists():
        p.unlink()


def _link_dir(src: Path, dest: Path) -> str:
    """디렉터리 링크를 만든다. 실패하면 복사한다. 사용한 방식을 돌려준다."""
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
            report.drift.append(f"{lib.rel(src)} 없음")
            return report
        shutil.copytree(TEMPLATE_DIR, src)
        report.created.append(lib.rel(src))
    for target in lib.config.get("targets", []):
        if target not in SKILL_TARGETS:
            report.warnings.append(f"알 수 없는 스킬 대상: {target}")
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
            report.drift.append(f"{lib.rel(dest)} 연결 끊김/내용 불일치")
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
    block = ["", "# claude-librarian: 스킬 링크 (check가 자동 복구)"] if current else [
        "# claude-librarian: 스킬 링크 (check가 자동 복구)"]
    gi.write_text("\n".join(current + block + missing) + "\n", encoding="utf-8", newline="\n")


# ---------------------------------------------------------------- 훅


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
        msgs.append("새 폴더 문서가 생성되었습니다. 각 문서의 '이 폴더의 역할'과 부모 문서의 "
                    "하위 폴더 표에서 역할을 채우세요 (함수 설명은 쓰지 마세요): "
                    + ", ".join(report.created))
    if report.warnings:
        msgs.append("librarian 경고: " + "; ".join(report.warnings))
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
        out["reason"] = ("librarian: 다음 폴더 문서의 '이 폴더의 역할' 또는 하위 폴더 표의 역할이 "
                         "비어 있습니다. 코드를 읽고 채우세요 (함수·파일 설명은 쓰지 말 것, "
                         "마커 블록은 수정하지 말 것): " + ", ".join(report.pending))
    _emit(out)


# ---------------------------------------------------------------- CLI


def _require(start: Path) -> Library:
    lib = load_library(start)
    if lib is None:
        sys.exit(f"{CONFIG_DIR}/{CONFIG_FILE}을 찾을 수 없습니다. 먼저 init을 실행하세요.")
    return lib


def _print_report(report: Report) -> None:
    for label, items in (("생성", report.created), ("갱신", report.updated),
                         ("불일치", report.drift), ("역할 작성 필요", report.pending),
                         ("경고", report.warnings), ("오류", report.errors)):
        for item in items:
            print(f"[{label}] {item}")


def cmd_init(args) -> None:
    root = Path(args.root).resolve()
    cfg_path = root / CONFIG_DIR / CONFIG_FILE
    cfg = dict(DEFAULT_CONFIG)
    if cfg_path.is_file():
        cfg.update(json.loads(cfg_path.read_text(encoding="utf-8")))
    cfg["docName"] = args.doc
    if args.targets is not None:
        cfg["targets"] = [t for t in args.targets.split(",") if t]
    if args.exclude:
        cfg["exclude"] = sorted(set(cfg.get("exclude", [])) | set(args.exclude))
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lib = Library(root=root, config=cfg)
    report = check_skills(lib, fix=True)
    _ensure_gitignore(lib)
    print(f"[설정] {lib.rel(cfg_path)}")
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
        sys.exit("폴더를 지정하거나 --all을 사용하세요.")
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
    except Exception as exc:  # 훅은 편집 흐름을 막지 않는다
        print(f"librarian hook error: {exc!r}", file=sys.stderr)
        if args.event == "stop":
            _emit({})


def main(argv: list[str] | None = None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="librarian")
    parser.add_argument("--root", default=".", help="프로젝트 루트 또는 그 하위 경로")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init")
    p.add_argument("--doc", choices=["CLAUDE.md", "AGENTS.md", "both"], default="CLAUDE.md")
    p.add_argument("--targets", help="claude,agents,codex 중 쉼표로 구분")
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
