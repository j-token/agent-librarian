#!/usr/bin/env python3
"""agent-librarian: CLI that maintains per-folder documents (CLAUDE.md / AGENTS.md).

Each document separates the part written by humans/LLMs (folder role, subfolder table) from
the part written by this script (the index marker block). The index records only
file · function · line and never describes what a function does.
"""
from __future__ import annotations

import argparse
import difflib
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # hooks load this file via runpy
from extract import EXT_LANG, extract_symbols  # noqa: E402

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
    "injectRules": True,
}

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
    return Library(root=root, config=_read_config(root / CONFIG_DIR / CONFIG_FILE))


def _read_config(path: Path) -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if path.is_file():
        cfg.update(json.loads(path.read_text(encoding="utf-8-sig")))  # tolerate a BOM
    for key in ("maxEntries", "maxDepth"):
        try:
            cfg[key] = int(cfg[key])
        except (TypeError, ValueError):
            cfg[key] = DEFAULT_CONFIG[key]
        if cfg[key] < 1:
            cfg[key] = DEFAULT_CONFIG[key]
    cfg["injectRules"] = _is_true(cfg["injectRules"], default=DEFAULT_CONFIG["injectRules"])
    return cfg


def _write_config(root: Path, cfg: dict) -> Path:
    path = root / CONFIG_DIR / CONFIG_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _is_true(value, default: bool = False) -> bool:
    """Read a flag from a hand-edited config value or a hook payload value, where booleans
    may arrive as strings ("false", "0", "off"). null or an unrecognized value gives default."""
    if isinstance(value, bool):
        return value
    word = str(value).strip().lower()
    if word in ("true", "1", "on", "yes"):
        return True
    if word in ("false", "0", "off", "no"):
        return False
    return default


def plugin_version() -> str | None:
    """None when plugin.json is missing or unreadable, so callers can skip version checks."""
    try:
        version = json.loads(_read(PLUGIN_ROOT / "plugin.json") or "{}").get("version")
    except (json.JSONDecodeError, AttributeError):
        return None
    return str(version) if version else None


def _version_tuple(version: str) -> tuple[int, ...] | None:
    try:
        return tuple(int(part) for part in version.split("."))
    except ValueError:
        return None


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


_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def _split_sections(text: str) -> dict:
    """Split a document into head / role / subdirs / index / tail.

    Lines inside code fences are plain text: they never start a section, and an index
    marker counts only when a matching end marker follows it.
    """
    lines = text.splitlines()
    fenced = _fenced_lines(lines)
    sections = {"head": [], "role": None, "subdirs": None, "index": None, "tail": []}
    cur = "head"
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if i in fenced:
            sections[cur].append(line)
            i += 1
            continue
        if stripped == INDEX_START and sections["index"] is None:
            j = i + 1
            while j < len(lines) and lines[j].strip() != INDEX_END:
                j += 1
            if j < len(lines):
                sections["index"] = lines[i:j + 1]
                cur = "tail"
                i = j + 1
                continue
        if stripped in (INDEX_START, INDEX_END):
            i += 1  # an orphan generated marker: drop it so it cannot pair up later
            continue
        if stripped in ROLE_HEADINGS and sections["role"] is None:
            sections["role"] = []
            cur = "role"
        elif stripped in SUBDIR_HEADINGS and sections["subdirs"] is None:
            sections["subdirs"] = []
            cur = "subdirs"
        elif stripped.startswith("## ") or stripped.startswith("# "):
            if cur in ("role", "subdirs"):
                cur = "tail"
            sections[cur].append(line)
        else:
            sections[cur].append(line)
        i += 1
    return sections


def _fenced_lines(lines: list[str]) -> set[int]:
    """Indexes of lines inside (or delimiting) closed code fences. An unclosed fence is text."""
    fenced: set[int] = set()
    open_at, fence = None, None
    for k, line in enumerate(lines):
        m = _FENCE.match(line)
        if fence is None:
            if m:
                open_at, fence = k, m.group(1)
        elif m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence):
            fenced.update(range(open_at, k + 1))
            fence = None
    return fenced


def _parse_index_rows(lines: list[str] | None) -> dict[str, list[tuple[str, str, str]]]:
    """Previous index rows by file name (kept when a file fails to parse)."""
    rows: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for line in lines or []:
        s_ = line.strip()
        if not s_.startswith("|") or set(s_) <= set("|-: "):
            continue
        cells = [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", s_)[1:-1]]
        if len(cells) == 3 and cells[2] not in {h["index_header"][2] for h in DOC_STRINGS.values()}:
            rows[cells[0]].append((cells[0], cells[1], cells[2]))
    return rows


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
               index_rows: list[tuple[str, str, str]], head: list[str], tail: list[str],
               subdir_notes: str = "") -> str:
    s = lib.strings
    placeholder = s["placeholder"]
    role_text = "\n".join(role).strip()
    if role_text in PLACEHOLDERS:
        role_text = ""
    parts: list[str] = []
    parts.append("\n".join(head).rstrip())
    parts.append(s["role"] + "\n\n" + (role_text or placeholder))
    if subdirs or subdir_notes:
        section = s["subdirs"]
        if subdirs:
            table = ["| {} | {} |".format(*s["subdir_header"]), "|---|---|"]
            table += [f"| {_escape(n)}/ | {placeholder if r in PLACEHOLDERS or not r else r} |"
                      for n, r in subdirs]
            section += "\n\n" + "\n".join(table)
        if subdir_notes:
            section += "\n\n" + subdir_notes  # text a human wrote under the table
        parts.append(section)
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


def build_index_rows(lib: Library, d: Path, files: list[Path], report: Report,
                     previous: dict | None = None):
    rows = []
    for f in sorted(files, key=lambda p: p.name.lower()):
        if f.name in lib.doc_names or f.suffix.lower() not in EXT_LANG:
            continue
        try:
            symbols = extract_symbols(f)
        except Exception as exc:  # keep the previous rows of a file that fails to parse
            report.warnings.append(f"{lib.rel(f)}: parse failed, keeping previous index rows ({exc})")
            rows.extend((previous or {}).get(f.name) or [(f.name, "-", "-")])
            continue
        if not symbols:
            rows.append((f.name, "-", "-"))
        rows.extend((f.name, name, str(line)) for name, line in symbols)
    return rows


ALIAS = "@AGENTS.md"


def _is_librarian_doc(text: str) -> bool:
    return INDEX_START in text or any(h in text for h in ROLE_HEADINGS | SUBDIR_HEADINGS)


def _read(path: Path) -> str | None:
    return path.read_text(encoding="utf-8-sig") if path.is_file() else None


def migrate_doc(lib: Library, d: Path) -> None:
    """Move a folder document when the doc mode changes (CLAUDE.md <-> AGENTS.md / both)."""
    claude, agents = d / "CLAUDE.md", d / "AGENTS.md"
    c, a = _read(claude), _read(agents)
    if lib.primary_doc == "AGENTS.md":
        if a is None and c is not None and c.strip() != ALIAS and _is_librarian_doc(c):
            claude.replace(agents)
    elif a is not None and _is_librarian_doc(a) and (c is None or c.strip() == ALIAS):
        agents.replace(claude)


def sync_dir(lib: Library, d: Path, files: list[Path], children: list[Path], fix: bool,
             had_doc: set[Path] | None = None) -> Report:
    """Bring one folder's document in line with the tree. With fix=False, only report.

    files: the files directly in d. children: the managed subfolders of d.
    had_doc: folders that had a document before this run (used to follow renames).
    """
    report = Report()
    rel = lib.rel(d)
    if fix:
        migrate_doc(lib, d)
    doc = lib.doc_path(d)
    original = _read(doc)
    existed = original is not None
    original = original or ""
    sec = _split_sections(original) if existed else {
        "head": [], "role": None, "subdirs": None, "index": None, "tail": []}
    sec["head"] = normalize_head(lib, d, sec["head"])

    child_dirs = sorted(children, key=lambda p: p.name.lower())
    rows = _parse_subdir_rows(sec["subdirs"] or [])
    known = dict(rows)
    subdirs = [(c.name, known.get(c.name, "")) for c in child_dirs]
    # a renamed folder (one row gone, one folder new that brought its document along)
    removed = [n for n, _ in rows if n not in {c.name for c in child_dirs}]
    added = [i for i, (n, r) in enumerate(subdirs) if n not in known]
    if (len(removed) == 1 and len(added) == 1 and had_doc is not None
            and child_dirs[added[0]] in had_doc and known[removed[0]] not in PLACEHOLDERS):
        subdirs[added[0]] = (subdirs[added[0]][0], known[removed[0]])
    notes = "\n".join(l for l in (sec["subdirs"] or []) if not l.strip().startswith("|")).strip()
    index_rows = build_index_rows(lib, d, files, report, _parse_index_rows(sec["index"]))

    rendered = render_doc(lib, d, sec["role"] or [], subdirs, index_rows, sec["head"], sec["tail"],
                          notes)
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
            alias.write_text(ALIAS + "\n", encoding="utf-8", newline="\n")

    if _role_is_empty(sec["role"]) or any(not r or r in PLACEHOLDERS for _, r in subdirs):
        report.pending.append(rel)
    depth = 0 if d == lib.root else len(d.relative_to(lib.root).parts)
    if depth > lib.config["maxDepth"]:
        report.warnings.append(
            f"{rel}: folder depth {depth} > {lib.config['maxDepth']} (consider restructuring)")
    if len(index_rows) > lib.config["maxEntries"]:
        report.warnings.append(
            f"{rel}: {len(index_rows)} index rows > {lib.config['maxEntries']} "
            "(consider splitting into subfolders)")
    return report


def _tree_maps(lib: Library, files: list[Path], dirs: set[Path]):
    by_dir: dict[Path, list[Path]] = defaultdict(list)
    for f in files:
        by_dir[f.parent].append(f)
    children: dict[Path, list[Path]] = defaultdict(list)
    for d in dirs:
        if d != lib.root:
            children[d.parent].append(d)
    return by_dir, children


def sync_dirs(lib: Library, targets: set[Path] | None, fix: bool) -> Report:
    files = list_files(lib)
    dirs = managed_dirs(lib, files)
    by_dir, children = _tree_maps(lib, files, dirs)
    had_doc = {d for d in dirs if lib.doc_path(d).is_file()}
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
            # for new folders, also create documents for ancestors that lack one,
            # and update the parent of the topmost new folder
            for anc in cur.parents:
                if anc in dirs and anc not in had_doc:
                    todo.add(anc)
                    if anc != lib.root:
                        todo.add(anc.parent)
                if anc == lib.root:
                    break
    for d in sorted(todo, key=lambda p: len(p.parts), reverse=True):
        report.merge(sync_dir(lib, d, by_dir.get(d, []), children.get(d, []), fix, had_doc))
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


def _tree_files(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def _same_tree(a: Path, b: Path) -> bool:
    if not a.is_dir() or not b.is_dir():
        return False
    fa = _tree_files(a)
    return fa == _tree_files(b) and all((a / f).read_bytes() == (b / f).read_bytes() for f in fa)


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


_FRONTMATTER = re.compile(r"\A---[ \t]*\r?\n(?:.*?\r?\n)?---[ \t]*(?:\r?\n|\Z)", re.DOTALL)


def library_rules_text(lib: Library) -> str:
    """The rules skill body without its frontmatter. The SKILL.md stays the single source
    of the rule text, so the project's copy wins over the plugin template."""
    skill = skill_source(lib) / "SKILL.md"
    if not skill.is_file():
        skill = TEMPLATE_DIR / "SKILL.md"
    return _FRONTMATTER.sub("", skill.read_text(encoding="utf-8-sig"), count=1).strip()


def _skill_diff(library_dir: Path, template_dir: Path) -> list[str]:
    """Differences between the library's rules skill and the plugin's. Line endings are
    ignored, because git's autocrlf changes them on ordinary installs."""
    library_files, template_files = _tree_files(library_dir), _tree_files(template_dir)
    lines: list[str] = []
    for name in sorted(library_files | template_files):
        if name not in template_files:
            lines.append(f"{name}: only in library")
            continue
        if name not in library_files:
            lines.append(f"{name}: only in plugin")
            continue
        current_lines = (_read(library_dir / name) or "").splitlines()
        plugin_lines = (_read(template_dir / name) or "").splitlines()
        lines.extend(difflib.unified_diff(current_lines, plugin_lines,
                                          f"library/{name}", f"plugin/{name}", lineterm=""))
    return lines


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
    comment = "# agent-librarian: skill links (restored automatically by check)"
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


def _version_notice(library_version: str | None, plugin_ver: str | None) -> str | None:
    """Compare the plugin version the library was built with against the running plugin."""
    if plugin_ver is None or library_version == plugin_ver:
        return None
    update_library = (f"library was built with {library_version or 'an older version'}, "
                      f"plugin is {plugin_ver}: run /update-library")
    if not library_version:
        return update_library
    library_tuple = _version_tuple(library_version)
    plugin_tuple = _version_tuple(plugin_ver)
    if library_tuple is None or plugin_tuple is None:
        return update_library  # unparsable version: any difference means "update"
    if plugin_tuple > library_tuple:
        return update_library
    if plugin_tuple < library_tuple:
        return (f"library was built with {library_version}, but the plugin is {plugin_ver}: "
                "update the plugin")
    return None


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
    notices = list(report.warnings)
    version_notice = _version_notice(lib.config.get("libraryVersion"), plugin_version())
    if version_notice:
        notices.append(version_notice)
    if notices:
        out["systemMessage"] = "librarian: " + "; ".join(notices)
    active = _is_true(payload.get("stop_hook_active"))
    if report.pending and not active:
        out["decision"] = "block"
        out["reason"] = (
            f"librarian: these folder documents have an empty '{lib.strings['role']}' section "
            f"or empty role cells in the subfolder table: {', '.join(report.pending)}. "
            f"Read the code and fill them in, in the library language ({lib.language}). "
            "Do not describe functions or files, and do not edit the index marker block.")
    _emit(out)


def hook_session_start(payload: dict) -> None:
    cwd = Path(payload.get("cwd") or os.getcwd())
    lib = load_library(cwd)
    if lib is None or not lib.config["injectRules"]:
        return
    context = f"{library_rules_text(lib)}\n\nLibrary language: {lib.language}, folder document: {lib.primary_doc}"
    _emit({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                  "additionalContext": context}})


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
    cfg = _read_config(cfg_path)
    if args.doc:
        cfg["docName"] = args.doc
    if args.language:
        cfg["language"] = args.language
    if args.targets is not None:
        cfg["targets"] = [t for t in args.targets.split(",") if t]
    if args.exclude:
        cfg["exclude"] = sorted(set(cfg.get("exclude", [])) | set(args.exclude))
    cfg["libraryVersion"] = plugin_version()
    _write_config(root, cfg)
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
    by_dir, children = _tree_maps(lib, files, dirs)
    report = Report()
    for d in sorted(dirs, key=lambda p: len(p.parts), reverse=True):
        if not lib.doc_path(d).is_file():
            report.merge(sync_dir(lib, d, by_dir.get(d, []), children.get(d, []), fix=True))
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


def cmd_rules(args) -> None:
    lib = _require(Path(args.root))
    inject = lib.config["injectRules"]
    if args.state != "status":
        # change only this key so the file does not gain every default value
        raw = json.loads(_read(lib.root / CONFIG_DIR / CONFIG_FILE) or "{}")
        inject = args.state == "on"
        raw["injectRules"] = inject
        _write_config(lib.root, raw)
    print(f"[rules] {'on' if inject else 'off'}")


def _replace_with_template(src: Path) -> None:
    """Swap src for a fresh template copy. The new copy is complete before the old one is
    moved away, so a failure never leaves the skill folder missing."""
    staged = src.with_name(f"{src.name}.new")
    backup = src.with_name(f"{src.name}.bak")
    for leftover in (staged, backup):
        _remove(leftover)
    shutil.copytree(TEMPLATE_DIR, staged)
    src.rename(backup)
    staged.rename(src)
    _remove(backup)


def cmd_update(args) -> None:
    lib = _require(Path(args.root))
    # migration: unlike `rules`, this intentionally writes the full config, so keys added
    # in newer versions (filled with defaults by _read_config) appear in the file
    lib.config["libraryVersion"] = plugin_version()
    cfg_path = _write_config(lib.root, lib.config)
    print(f"[config] {lib.rel(cfg_path)}")

    report = Report()
    src = skill_source(lib)
    skill_diff = _skill_diff(src, TEMPLATE_DIR) if src.is_dir() else []
    if skill_diff:
        if args.replace_skill:
            _replace_with_template(src)
            report.updated.append(lib.rel(src))
        else:  # the user may have edited the rules; show the diff and let them decide
            for line in skill_diff:
                print(f"[skill-diff] {line}")

    report.merge(check_skills(lib, fix=True))
    _ensure_gitignore(lib)
    report.merge(sync_dirs(lib, None, fix=True))
    _print_report(report)


def cmd_hook(args) -> None:
    raw = sys.stdin.buffer.read().decode("utf-8", "replace")
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        payload = {}
    try:
        if args.event == "post-edit":
            hook_post_edit(payload)
        elif args.event == "session-start":
            hook_session_start(payload)
        else:
            hook_stop(payload)
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
    p.add_argument("--doc", choices=["CLAUDE.md", "AGENTS.md", "both"],
                   help="folder document name (default: keep the current one, else CLAUDE.md)")
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

    p = sub.add_parser("rules")
    p.add_argument("state", choices=["on", "off", "status"])
    p.set_defaults(func=cmd_rules)

    p = sub.add_parser("update")
    p.add_argument("--replace-skill", action="store_true",
                   help="replace the library's rules skill with the plugin template")
    p.set_defaults(func=cmd_update)

    p = sub.add_parser("hook")
    p.add_argument("event", choices=["post-edit", "stop", "session-start"])
    p.set_defaults(func=cmd_hook)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
