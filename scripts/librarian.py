#!/usr/bin/env python3
"""agent-librarian: CLI that maintains per-folder documents (CLAUDE.md / AGENTS.md).

Each document separates the part written by humans/LLMs (folder role, subfolder table) from
the part written by this script (the index marker block). The index records only
file · function · start line · end line and never describes what a function does.
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
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))  # hooks load this file via runpy
from extract import EXT_LANG, extract_symbols  # noqa: E402

CONFIG_DIR = ".librarian"
CONFIG_FILE = "config.json"
PLUGIN_ROOT = Path(__file__).resolve().parent.parent

INDEX_START = "<!-- librarian:index:start -->"
INDEX_END = "<!-- librarian:index:end -->"
GENERATED_MARKER = "<!-- librarian:generated -->"
INDEX_FILE_NAME = "index.md"
INDEX_DIR_NAME = "index"
IndexRow = tuple[str, str, str, str]  # file, symbol, start line, end line

# Generated document text per library language. Languages without an entry use English
# headings; the role text itself is still written in the configured language.
DOC_STRINGS = {
    "en": {
        "parent": "# Parent: ../{doc}",
        "role": "## What this folder is for",
        "notes": "## Notes",
        "subdirs": "## Subfolders",
        "placeholder": "_(to be written)_",
        "subdir_header": ("Folder", "Role"),
        "index_header": ("File", "Function", "Start", "End"),
        "index_link": "[Index]({index_file})",
    },
    "ko": {
        "parent": "# 상위 문서: ../{doc}",
        "role": "## 이 폴더의 역할",
        "notes": "## 메모",
        "subdirs": "## 하위 폴더",
        "placeholder": "_(작성 필요)_",
        "subdir_header": ("폴더", "역할"),
        "index_header": ("파일", "함수", "시작 줄", "끝 줄"),
        "index_link": "[색인]({index_file})",
    },
}
ROLE_HEADINGS = {s["role"] for s in DOC_STRINGS.values()}
NOTES_HEADINGS = {s["notes"] for s in DOC_STRINGS.values()}
SUBDIR_HEADINGS = {s["subdirs"] for s in DOC_STRINGS.values()}
PLACEHOLDERS = {s["placeholder"] for s in DOC_STRINGS.values()}
# The line older versions wrote in the root document to point at the removed rules skill.
# Kept only so that normalize_head can delete it from existing libraries.
LEGACY_ROOT_NOTES = {
    "This repository follows the rules of the `librarian-guide` skill.",
    "이 저장소는 `librarian-guide` 스킬의 규칙을 따릅니다.",
}
SUBDIR_HEADER_CELLS = {s["subdir_header"][0] for s in DOC_STRINGS.values()}
# Third header cell of the index: "Start" now, "Line" in indexes written before rows had
# an end line
INDEX_LINE_HEADER_CELLS = {s["index_header"][2] for s in DOC_STRINGS.values()} | {"Line", "줄"}
PARENT_RE = re.compile(
    "^(?:" + "|".join(re.escape(s["parent"].split("{doc}")[0]) for s in DOC_STRINGS.values())
    + r")\S+\s*$")

# Older versions installed a rules skill: a source folder in the library, links to it in each
# agent's skills folder, and .gitignore lines for those links. `update` removes the links and
# lines, and only reports the source folder.
LEGACY_SKILL_SOURCE = Path(CONFIG_DIR) / "skills" / "librarian-guide"
LEGACY_SKILL_LINKS = [Path(agent) / "skills" / "librarian-guide"
                      for agent in (".claude", ".agents", ".codex")]
LEGACY_GITIGNORE_COMMENT = "# agent-librarian: skill links (restored automatically by check)"
LEGACY_GITIGNORE_LINES = {f"/{link.as_posix()}" for link in LEGACY_SKILL_LINKS}
# Config keys of removed features: maxEntries (index-row split warning), injectRules
# (session-start rule injection), targets (rules skill link folders). Dropping them when the
# config is read lets every command that rewrites the whole config (init, update) remove them.
REMOVED_CONFIG_KEYS = ("maxEntries", "injectRules", "targets")
DEFAULT_EXCLUDE = [
    "node_modules", "dist", "build", "out", "target", "vendor",
    "venv", "__pycache__", "coverage",
]
DEFAULT_CONFIG = {
    "language": "en",
    "docName": "CLAUDE.md",
    "exclude": [],
    "maxDepth": 6,
    "maxDocLines": 200,
}
CLAUDE_RULES_DIR = Path(".claude") / "rules"

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
    for key in REMOVED_CONFIG_KEYS:
        cfg.pop(key, None)
    for key in ("maxDepth", "maxDocLines"):
        try:
            cfg[key] = int(cfg[key])
        except (TypeError, ValueError):
            cfg[key] = DEFAULT_CONFIG[key]
        if cfg[key] < 1:
            cfg[key] = DEFAULT_CONFIG[key]
    return cfg


def _write_config(root: Path, cfg: dict) -> Path:
    path = root / CONFIG_DIR / CONFIG_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _is_true(value) -> bool:
    """Read a flag from a hook payload value, where booleans may arrive as strings
    ("true", "1", "on"). null or an unrecognized value is False."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "on", "yes")


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
            if _may_be_generated_name(parts) and _is_generated_file(p):
                continue
            files.append(p)
    return files


def _may_be_generated_name(rel_parts: tuple[str, ...]) -> bool:
    return rel_parts[-1] == INDEX_FILE_NAME or (len(rel_parts) >= 2 and rel_parts[-2] == INDEX_DIR_NAME)


def _is_generated_file(path: Path) -> bool:
    if _is_link(path) or not path.is_file():
        return False
    try:
        with path.open("rb") as handle:
            first_line = handle.readline(len(GENERATED_MARKER) + 16)
    except OSError:
        return False
    return first_line.decode("utf-8-sig", "replace").strip() == GENERATED_MARKER


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


def _escape_link_label(label: str) -> str:
    return label.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


# ---------------------------------------------------------------- documents


_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def _split_sections(text: str) -> dict:
    """Split a document into head / role / notes / subdirs / index / tail.

    Lines inside code fences are plain text: they never start a section, and an index
    marker counts only when a matching end marker follows it.
    """
    lines = text.splitlines()
    fenced = _fenced_lines(lines)
    sections = {"head": [], "role": None, "notes": None, "subdirs": None,
                "index": None, "tail": []}
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
        elif stripped in NOTES_HEADINGS and sections["notes"] is None:
            sections["notes"] = []
            cur = "notes"
        elif stripped in SUBDIR_HEADINGS and sections["subdirs"] is None:
            sections["subdirs"] = []
            cur = "subdirs"
        elif stripped.startswith("## ") or stripped.startswith("# "):
            if cur in ("role", "notes", "subdirs"):
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


def _parse_index_rows(lines: list[str] | None) -> dict[str, list[tuple[str, str, str, str]]]:
    """Previous index rows by file name (kept when a file fails to parse).

    Rows from an index written before rows had an end line have three cells; their end
    line is unknown and becomes "-"."""
    rows: dict[str, list[tuple[str, str, str, str]]] = defaultdict(list)
    for line in lines or []:
        s_ = line.strip()
        if not s_.startswith("|") or set(s_) <= set("|-: "):
            continue
        cells = [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", s_)[1:-1]]
        if len(cells) not in (3, 4) or cells[2] in INDEX_LINE_HEADER_CELLS:
            continue
        end = cells[3] if len(cells) == 4 else "-"
        rows[cells[0]].append((cells[0], cells[1], cells[2], end))
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
               index_block: list[str], head: list[str], tail: list[str],
               subdir_notes: str = "", folder_notes: list[str] | None = None) -> str:
    s = lib.strings
    placeholder = s["placeholder"]
    role_text = "\n".join(role).strip()
    if role_text in PLACEHOLDERS:
        role_text = ""
    parts: list[str] = []
    parts.append("\n".join(head).rstrip())
    parts.append(s["role"] + "\n\n" + (role_text or placeholder))
    notes_text = "\n".join(folder_notes or []).strip()
    parts.append(s["notes"] + ("\n\n" + notes_text if notes_text else ""))
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
    if index_block:
        parts.append("\n".join(index_block))
    return "\n\n".join(p for p in parts if p) + "\n"


def index_table_lines(lib: Library, index_rows: list[IndexRow]) -> list[str]:
    header = lib.strings["index_header"]
    table = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    table.extend(f"| {_escape(file_name)} | {_escape(symbol)} | {start} | {end} |"
                 for file_name, symbol, start, end in index_rows)
    return table


def _generated_text(lines: list[str]) -> str:
    return "\n".join([GENERATED_MARKER, *lines]) + "\n"


def default_head(lib: Library, d: Path) -> list[str]:
    if d == lib.root:
        return [f"# {lib.root.name}"]
    return [lib.strings["parent"].format(doc=lib.primary_doc)]


def normalize_head(lib: Library, d: Path, head: list[str]) -> list[str]:
    """Rewrite the generated lines of the head (parent link) in the current language and
    doc name, and drop the old root note, keeping everything else the user wrote."""
    if d == lib.root:
        head = _without_legacy_root_note(head)
        return head if "".join(head).strip() else default_head(lib, d)
    if not "".join(head).strip():
        return default_head(lib, d)
    return [lib.strings["parent"].format(doc=lib.primary_doc) if PARENT_RE.match(line.strip())
            else line for line in head]


def _without_legacy_root_note(head: list[str]) -> list[str]:
    """Drop the old pointer line outside code fences, together with the blank line that
    separated it from what follows."""
    fenced = _fenced_lines(head)
    note_rows = {k for k, line in enumerate(head)
                 if k not in fenced and line.strip() in LEGACY_ROOT_NOTES}
    out: list[str] = []
    for k, line in enumerate(head):
        is_blank_after_note = k - 1 in note_rows and not line.strip()
        if k in note_rows or is_blank_after_note:
            continue
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
        if f.name in {"CLAUDE.md", "AGENTS.md"} or f.suffix.lower() not in EXT_LANG:
            continue
        no_symbol_row = (f.name, "-", "-", "-")
        try:
            symbols = extract_symbols(f)
        except Exception as exc:  # keep the previous rows of a file that fails to parse
            report.warnings.append(f"{lib.rel(f)}: parse failed, keeping previous index rows ({exc})")
            rows.extend((previous or {}).get(f.name) or [no_symbol_row])
            continue
        if not symbols:
            rows.append(no_symbol_row)
        rows.extend((f.name, name, str(start), str(end)) for name, start, end in symbols)
    return rows


def _generated_lines(path: Path) -> list[str] | None:
    if not _is_generated_file(path):
        return None
    return (_read(path) or "").splitlines()


def _per_file_index_paths(d: Path) -> list[Path]:
    index_dir = d / INDEX_DIR_NAME
    if not index_dir.is_dir() or _is_link(index_dir):
        return []
    # index/index.md can belong to a real source folder named "index".
    return [p for p in sorted(index_dir.iterdir()) if p.name != INDEX_FILE_NAME]


def read_previous_index_rows(d: Path, inline_block: list[str] | None) -> dict[str, list[IndexRow]]:
    """Read prior rows from the inline, shared, or per-file tier for parse-failure fallback."""
    sources = [inline_block, _generated_lines(d / INDEX_FILE_NAME),
               *(_generated_lines(p) for p in _per_file_index_paths(d))]
    rows: dict[str, list[IndexRow]] = {}
    for lines in sources:
        for file_name, file_rows in _parse_index_rows(lines).items():
            rows.setdefault(file_name, file_rows)
    return rows


def _path_is_free_for_generated_file(path: Path) -> bool:
    return not os.path.lexists(path) or _is_generated_file(path)


def _index_dir_is_free_for_generated_files(path: Path) -> bool:
    if not os.path.lexists(path):
        return True
    if not path.is_dir() or _is_link(path):
        return False
    return all(_is_generated_file(child) for child in path.iterdir())


def plan_index_layout(lib: Library, d: Path, index_rows: list[IndexRow],
                      doc_lines_without_index: int,
                      report: Report) -> tuple[list[str], dict[Path, str]]:
    """Use the smallest index tier that fits, without taking over human-owned paths."""
    if not index_rows:
        return [], {}
    table = index_table_lines(lib, index_rows)
    inline_block = [INDEX_START, *table, INDEX_END]
    limit = lib.config["maxDocLines"]
    if doc_lines_without_index + 1 + len(inline_block) <= limit:
        return inline_block, {}

    rel = lib.rel(d)
    index_file = d / INDEX_FILE_NAME
    if not _path_is_free_for_generated_file(index_file):
        report.warnings.append(
            f"{rel}: the folder document exceeds maxDocLines {limit}, but {INDEX_FILE_NAME} "
            "is human-owned; the index remains inline. Move that file to allow index splitting")
        return inline_block, {}

    link_block = [INDEX_START, lib.strings["index_link"].format(index_file=INDEX_FILE_NAME),
                  INDEX_END]
    generated_table = _generated_text(table)
    if len(generated_table.splitlines()) <= limit:
        return link_block, {index_file: generated_table}

    if not _index_dir_is_free_for_generated_files(d / INDEX_DIR_NAME):
        report.warnings.append(
            f"{rel}: {INDEX_FILE_NAME} exceeds maxDocLines {limit}, but {INDEX_DIR_NAME}/ "
            "contains human-owned files; per-file indexes cannot be created. Move that "
            "directory to allow splitting")
        return link_block, {index_file: generated_table}

    rows_by_file: dict[str, list[IndexRow]] = defaultdict(list)
    for row in index_rows:
        rows_by_file[row[0]].append(row)
    generated: dict[Path, str] = {}
    links = []
    for file_name, file_rows in rows_by_file.items():
        per_file_name = f"{file_name}.md"
        generated[d / INDEX_DIR_NAME / per_file_name] = _generated_text(
            index_table_lines(lib, file_rows))
        links.append(f"- [{_escape_link_label(file_name)}]({INDEX_DIR_NAME}/{quote(per_file_name)})")
    generated[index_file] = _generated_text(links)
    for path, text in generated.items():
        line_count = len(text.splitlines())
        if line_count > limit:
            report.warnings.append(
                f"{lib.rel(path)}: generated index has {line_count} lines > maxDocLines {limit}; "
                "this index cannot be split further")
    return link_block, generated


def sync_generated_files(lib: Library, d: Path, wanted: dict[Path, str], fix: bool,
                         report: Report) -> list[Path]:
    """Write new index files before the folder doc; return stale files for later cleanup."""
    for path, text in wanted.items():
        if _read(path) == text:
            continue
        (report.updated if fix else report.drift).append(lib.rel(path))
        if fix:
            if not _path_is_free_for_generated_file(path):
                raise FileExistsError(f"refusing to overwrite human-owned index: {path}")
            path.parent.mkdir(exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")

    stale = [p for p in [d / INDEX_FILE_NAME, *_per_file_index_paths(d)]
             if p not in wanted and _is_generated_file(p)]
    if not fix:
        report.drift.extend(f"{lib.rel(p)} (stale)" for p in stale)
    return stale


def remove_stale_index_files(lib: Library, d: Path, stale: list[Path], report: Report) -> None:
    removed_any = False
    for path in stale:
        if not _is_generated_file(path):
            continue  # a person changed it after the stale-file scan
        path.unlink()
        report.updated.append(f"{lib.rel(path)} (removed)")
        removed_any = True
    index_dir = d / INDEX_DIR_NAME
    if removed_any and index_dir.is_dir() and not _is_link(index_dir) and not any(index_dir.iterdir()):
        index_dir.rmdir()


ALIAS = "@AGENTS.md"


def _is_librarian_doc(text: str) -> bool:
    return INDEX_START in text or any(h in text for h in ROLE_HEADINGS | SUBDIR_HEADINGS)


def _read(path: Path) -> str | None:
    return path.read_text(encoding="utf-8-sig") if path.is_file() else None


def migrate_doc(lib: Library, d: Path) -> str | None:
    """Move a folder document when the doc mode changes (CLAUDE.md <-> AGENTS.md / both)."""
    claude, agents = d / "CLAUDE.md", d / "AGENTS.md"
    c, a = _read(claude), _read(agents)
    if lib.primary_doc == "AGENTS.md":
        if a is None and c is not None and c.strip() != ALIAS and _is_librarian_doc(c):
            claude.replace(agents)
        elif (d == lib.root and lib.doc_mode == "both" and a is not None and c is not None
              and c.strip() != ALIAS and _is_librarian_doc(c)):
            if _is_librarian_doc(a):
                return (f"{lib.rel(d)}: both CLAUDE.md and AGENTS.md contain folder-document "
                        "sections; review and merge their human-written instructions manually")
            # A user may have written shared rules in root AGENTS.md before enabling both.
            # Store both bodies in the new primary document before replacing CLAUDE.md.
            agents.write_text(c.rstrip("\n") + "\n\n" + a, encoding="utf-8", newline="\n")
            claude.write_text(ALIAS + "\n", encoding="utf-8", newline="\n")
    elif a is not None and _is_librarian_doc(a) and (c is None or c.strip() == ALIAS):
        agents.replace(claude)
    return None


def sync_dir(lib: Library, d: Path, files: list[Path], children: list[Path], fix: bool,
             had_doc: set[Path] | None = None) -> Report:
    """Bring one folder's document in line with the tree. With fix=False, only report.

    files: the files directly in d. children: the managed subfolders of d.
    had_doc: folders that had a document before this run (used to follow renames).
    """
    report = Report()
    rel = lib.rel(d)
    if fix:
        migration_warning = migrate_doc(lib, d)
        if migration_warning:
            report.warnings.append(migration_warning)
            return report  # neither document can be rewritten until the conflict is resolved
    doc = lib.doc_path(d)
    original = _read(doc)
    existed = original is not None
    original = original or ""
    sec = _split_sections(original) if existed else {
        "head": [], "role": None, "notes": None, "subdirs": None, "index": None,
        "tail": []}
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
    index_rows = build_index_rows(lib, d, files, report, read_previous_index_rows(d, sec["index"]))

    def render_with_index_block(index_block: list[str]) -> str:
        return render_doc(lib, d, sec["role"] or [], subdirs, index_block, sec["head"],
                          sec["tail"], notes, sec["notes"] or [])

    doc_lines_without_index = len(render_with_index_block([]).splitlines())
    index_block, generated_files = plan_index_layout(
        lib, d, index_rows, doc_lines_without_index, report)
    rendered = render_with_index_block(index_block)
    stale_index_files = sync_generated_files(lib, d, generated_files, fix, report)
    if rendered != original:
        if not existed:
            (report.created if fix else report.drift).append(rel)
        else:
            (report.updated if fix else report.drift).append(rel)
        if fix:
            doc.write_text(rendered, encoding="utf-8", newline="\n")
    if fix:
        remove_stale_index_files(lib, d, stale_index_files, report)
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


# ---------------------------------------------------------------- long documents


def find_overlong_docs(lib: Library) -> list[tuple[str, int]]:
    """Find long folder docs, root AGENTS.md, and Claude rule files.

    The root AGENTS.md may be a user-owned shared-rules file even when CLAUDE.md is the
    configured folder document. Only managed folder documents omit generated index rows.
    """
    folder_docs = {lib.doc_path(d) for d in managed_dirs(lib, list_files(lib))}
    candidates = folder_docs | {lib.root / "AGENTS.md"}
    rules_dir = lib.root / CLAUDE_RULES_DIR
    if not _is_link(rules_dir):
        try:
            candidates.update(rules_dir.rglob("*.md"))
        except OSError:
            pass

    overlong = []
    for path in sorted(candidates):
        try:
            text = _read(path)
        except (OSError, UnicodeDecodeError):
            continue
        if text is None:
            continue
        count = len(text.splitlines())
        if path in folder_docs:
            count -= len(_split_sections(text)["index"] or [])
        if count > lib.config["maxDocLines"]:
            overlong.append((lib.rel(path), count))
    return overlong


# ---------------------------------------------------------------- legacy rules skill


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


def remove_legacy_skill(lib: Library) -> Report:
    """Remove the links and .gitignore lines of the rules skill older versions installed.
    Anything that may hold the user's own text is left in place with a warning: the source
    folder, and a copied link folder whose files differ from the source."""
    report = Report()
    source = lib.root / LEGACY_SKILL_SOURCE
    for link in LEGACY_SKILL_LINKS:
        path = lib.root / link
        if not os.path.lexists(path):
            continue
        if not _is_link(path) and not _same_text_files(path, source):
            report.warnings.append(
                f"{link.as_posix()} differs from {LEGACY_SKILL_SOURCE.as_posix()}, so it was "
                "left in place. It is no longer used; delete it once you have kept what you need")
            continue
        _remove(path)
        report.updated.append(f"{link.as_posix()} (removed)")
        _rmdir_if_empty(path.parent)
        if path.parent.parent.name != ".claude":  # .claude also holds Claude Code settings
            _rmdir_if_empty(path.parent.parent)
    if _remove_legacy_gitignore_lines(lib):
        report.updated.append(".gitignore (removed skill link entries)")
    if source.exists():
        report.warnings.append(
            f"{LEGACY_SKILL_SOURCE.as_posix()} is no longer used and was left in place. "
            "Move anything you still want from it into a folder document, then delete it")
    return report


def _same_text_files(a: Path, b: Path) -> bool:
    """Whether two folders hold the same files with the same text. Line endings are ignored,
    because git's autocrlf changes them on ordinary checkouts."""
    if not a.is_dir() or not b.is_dir():
        return False
    names_a = {p.relative_to(a) for p in a.rglob("*") if p.is_file()}
    names_b = {p.relative_to(b) for p in b.rglob("*") if p.is_file()}
    return names_a == names_b and all(
        (a / name).read_bytes().replace(b"\r\n", b"\n")
        == (b / name).read_bytes().replace(b"\r\n", b"\n") for name in names_a)


def _rmdir_if_empty(path: Path) -> None:
    if path.is_dir() and not _is_link(path) and not any(path.iterdir()):
        path.rmdir()


def _remove_legacy_gitignore_lines(lib: Library) -> bool:
    """Drop the .gitignore lines older versions added for the skill links, keeping the file's
    BOM and line ending style. Returns whether the file changed."""
    gitignore = lib.root / ".gitignore"
    if not gitignore.is_file():
        return False
    raw = gitignore.read_bytes()
    bom = b"\xef\xbb\xbf" if raw.startswith(b"\xef\xbb\xbf") else b""
    text = raw[len(bom):].decode("utf-8")
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines()
    kept: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped == LEGACY_GITIGNORE_COMMENT:
            if kept and not kept[-1].strip():
                kept.pop()  # the blank line that was added to separate the block
            continue
        if stripped not in LEGACY_GITIGNORE_LINES:
            kept.append(line)
    if kept == lines:
        return False
    if any(line.strip() for line in kept):
        gitignore.write_bytes(bom + (newline.join(kept) + newline).encode("utf-8"))
    else:
        gitignore.unlink()  # the file held nothing but the plugin's lines
    return True


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
    report = sync_dirs(lib, changed_dirs(lib), fix=True)
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
    if lib is None:
        return
    overlong = find_overlong_docs(lib)
    if not overlong:
        return
    listing = ", ".join(f"{rel} ({count} lines)" for rel, count in overlong)
    context = (
        f"librarian: these documents exceed maxDocLines {lib.config['maxDocLines']}: {listing}. "
        "The folder-document count excludes generated index rows. Split human-written text "
        "by topic, leave a one-line pointer in the original, and avoid duplicated rules. "
        "Keep shared and non-Claude instructions in root AGENTS.md; group or condense them "
        "there and point to detailed ordinary documents when needed. "
        f"See the rule-creator skill. Write in the library language ({lib.language}).")
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
    if args.exclude:
        cfg["exclude"] = sorted(set(cfg.get("exclude", [])) | set(args.exclude))
    cfg["libraryVersion"] = plugin_version()
    _write_config(root, cfg)
    print(f"[config] {cfg_path.relative_to(root).as_posix()}")
    # a library rebuilt with init gets the new version stamp, so the Stop hook no longer
    # asks for /update-library; the old rules skill is cleaned up here as well
    _print_report(remove_legacy_skill(Library(root=root, config=cfg)))


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
    targets = changed_dirs(lib) if args.changed else None
    report = sync_dirs(lib, targets, fix=args.fix)
    limit = lib.config["maxDocLines"]
    report.warnings.extend(
        f"{rel}: {count} lines > maxDocLines {limit}; split human-written text by topic "
        "and leave a one-line pointer; keep shared and non-Claude instructions in root "
        "AGENTS.md (see the rule-creator skill)"
        for rel, count in find_overlong_docs(lib))
    _print_report(report)
    if report.drift or report.pending:
        sys.exit(1)


def cmd_pending(args) -> None:
    lib = _require(Path(args.root))
    report = sync_dirs(lib, None, fix=False)
    for rel in sorted(report.pending, key=lambda r: (-len(Path(r).parts), r)):
        print(rel)


def cmd_update(args) -> None:
    lib = _require(Path(args.root))
    report = remove_legacy_skill(lib)
    report.merge(sync_dirs(lib, None, fix=True))

    # migration: this intentionally writes the full config, so keys added in newer versions
    # (filled with defaults by _read_config) appear in the file. It runs last so that a
    # failure above keeps the old version, and the Stop hook keeps asking for the update.
    lib.config["libraryVersion"] = plugin_version()
    cfg_path = _write_config(lib.root, lib.config)
    print(f"[config] {lib.rel(cfg_path)}")
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
    p.add_argument("--exclude", nargs="*", default=[])
    p.set_defaults(func=cmd_init)

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

    sub.add_parser("update").set_defaults(func=cmd_update)

    p = sub.add_parser("hook")
    p.add_argument("event", choices=["post-edit", "stop", "session-start"])
    p.set_defaults(func=cmd_hook)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
