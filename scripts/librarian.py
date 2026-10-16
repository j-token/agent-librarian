#!/usr/bin/env python3
"""agent-librarian: CLI that maintains per-folder CLAUDE.md documents and a code catalog.

A folder document holds only what people and agents write: the folder's role, notes, and
a table of its subfolders. Definitions (file · symbol · start line · end line) live in a
derived catalog under .librarian/ that is queried on demand with `find` and `outline`, so
they never enter an agent's context unless it asks. The catalog never describes what a
function does.
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
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract import EXT_LANG, extract_symbols  # noqa: E402

CONFIG_DIR = ".librarian"
CONFIG_FILE = "config.json"
CATALOG_FILE = "catalog.json"
# Bump when the extractor's output changes, so cached catalogs are rebuilt.
CATALOG_SCHEMA = 1
DOC_NAME = "CLAUDE.md"
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
# Extensions the extractor reads that are documentation rather than code: they neither make
# a folder managed nor enter the catalog (`outline` still reads them on request).
DOC_EXTS = {".md"}
FIND_LIMIT = 60
# A lookup with at most this many matches also prints their code (each cut after
# FIND_CODE_LINES lines): it saves the agent a separate read, and every extra tool round
# trip resends the whole conversation.
FIND_CODE_HITS = 3
FIND_CODE_LINES = 60
GREP_LIMIT = 100
GREP_LINE_CHARS = 200
OUTLINE_NAMES_PER_FILE = 25
PENDING_LIST_LIMIT = 10
ROLE_PREVIEW_CHARS = 120

# Markers of the generated index older versions kept in folder documents, index.md files and
# index/ folders. They are read only to remove that index.
INDEX_START = "<!-- librarian:index:start -->"
INDEX_END = "<!-- librarian:index:end -->"
GENERATED_MARKER = "<!-- librarian:generated -->"
INDEX_FILE_NAME = "index.md"
INDEX_DIR_NAME = "index"
# Older versions could keep folder documents in AGENTS.md, with CLAUDE.md holding only this.
ALIAS = "@AGENTS.md"

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
    },
    "ko": {
        "parent": "# 상위 문서: ../{doc}",
        "role": "## 이 폴더의 역할",
        "notes": "## 메모",
        "subdirs": "## 하위 폴더",
        "placeholder": "_(작성 필요)_",
        "subdir_header": ("폴더", "역할"),
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
# (session-start rule injection), targets (rules skill link folders), docName (AGENTS.md
# document modes). Dropping them when the config is read lets every command that rewrites
# the whole config (init, update) remove them.
REMOVED_CONFIG_KEYS = ("maxEntries", "injectRules", "targets", "docName")
DEFAULT_EXCLUDE = [
    "node_modules", "dist", "build", "out", "target", "vendor",
    "venv", "__pycache__", "coverage",
]
DEFAULT_CONFIG = {
    "language": "en",
    "exclude": [],
    "maxDepth": 6,
    "maxDocLines": 60,
}
# Older versions defaulted to 200 lines because the index shared the document; `update`
# moves a library still on that default to the new one.
LEGACY_DEFAULT_MAX_DOC_LINES = 200
CLAUDE_RULES_DIR = Path(".claude") / "rules"

# ---------------------------------------------------------------- config / paths


@dataclass
class Library:
    root: Path
    config: dict = field(default_factory=dict)

    def doc_path(self, d: Path) -> Path:
        return d / DOC_NAME

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
    _write_utf8(path, json.dumps(cfg, ensure_ascii=False, indent=2) + "\n")
    return path


def _write_utf8(path: Path, text: str) -> None:
    """Write LF-delimited UTF-8 text with the Python 3.9-compatible Path.open API."""
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def _is_true(value) -> bool:
    """Read a flag from a hook payload value, where booleans may arrive as strings
    ("true", "1", "on"). null or an unrecognized value is False."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "on", "yes")


def plugin_version() -> str | None:
    """Read the plugin manifest; skip version checks when it is unusable."""
    try:
        version = json.loads(_read(PLUGIN_ROOT / ".claude-plugin" / "plugin.json") or "{}").get(
            "version")
    except (OSError, UnicodeError, json.JSONDecodeError, AttributeError):
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


def is_code(path: Path) -> bool:
    suffix = path.suffix.lower()
    return suffix in EXT_LANG and suffix not in DOC_EXTS


def managed_dirs(lib: Library, files: list[Path]) -> set[Path]:
    """The root and every folder that holds a code file directly or below it."""
    dirs = {lib.root}
    for f in files:
        if not is_code(f):
            continue
        for parent in f.parents:
            if parent == lib.root or lib.root not in parent.parents or parent in dirs:
                break
            dirs.add(parent)
    return dirs


def _escape(cell: str) -> str:
    return cell.replace("|", "\\|")


# ---------------------------------------------------------------- documents


_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def _split_sections(text: str) -> dict:
    """Split a document into head / role / notes / subdirs / index / tail.

    Lines inside code fences are plain text: they never start a section, and an index
    marker counts only when a matching end marker follows it. The index section exists only
    in documents written by older versions; rendering drops it.
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


def _role_is_empty(role_lines: list[str] | None) -> bool:
    if role_lines is None:
        return True
    body = "\n".join(role_lines)
    for ph in PLACEHOLDERS:
        body = body.replace(ph, "")
    return body.strip() == ""


def _is_table_row(line: str) -> bool:
    return line.strip().startswith("|")


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
               head: list[str], tail: list[str], subdir_notes: str = "",
               folder_notes: list[str] | None = None) -> str:
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
    return "\n\n".join(p for p in parts if p) + "\n"


def default_head(lib: Library, d: Path) -> list[str]:
    if d == lib.root:
        return [f"# {lib.root.name}"]
    return [lib.strings["parent"].format(doc=DOC_NAME)]


def normalize_head(lib: Library, d: Path, head: list[str]) -> list[str]:
    """Rewrite the generated lines of the head (parent link) in the current language, and
    drop the old root note, keeping everything else the user wrote."""
    if d == lib.root:
        head = _without_legacy_root_note(head)
        return head if "".join(head).strip() else default_head(lib, d)
    if not "".join(head).strip():
        return default_head(lib, d)
    return [lib.strings["parent"].format(doc=DOC_NAME) if PARENT_RE.match(line.strip())
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


def _read(path: Path) -> str | None:
    return path.read_text(encoding="utf-8-sig") if path.is_file() else None


def _is_librarian_doc(text: str) -> bool:
    """Did this plugin write the document? A role heading or index marker must stand on its
    own line, so a hand-written AGENTS.md that merely mentions one is left alone."""
    lines = {line.strip() for line in text.split("\n")}
    return INDEX_START in lines or bool(lines & ROLE_HEADINGS)


def _is_generated_file(path: Path) -> bool:
    if _is_link(path) or not path.is_file():
        return False
    try:
        with path.open("rb") as handle:
            first_line = handle.readline(len(GENERATED_MARKER) + 16)
    except OSError:
        return False
    return first_line.decode("utf-8-sig", "replace").strip() == GENERATED_MARKER


def legacy_index_files(d: Path) -> list[Path]:
    """index.md and index/*.md files an older version generated in folder d."""
    candidates = [d / INDEX_FILE_NAME]
    index_dir = d / INDEX_DIR_NAME
    if index_dir.is_dir() and not _is_link(index_dir):
        candidates.extend(sorted(index_dir.glob("*.md")))
    return [p for p in candidates if _is_generated_file(p)]


def remove_legacy_index_files(lib: Library, d: Path, fix: bool, report: Report) -> None:
    stale = legacy_index_files(d)
    if not fix:
        report.drift.extend(f"{lib.rel(p)} (legacy index)" for p in stale)
        return
    for path in stale:
        path.unlink()
        report.updated.append(f"{lib.rel(path)} (removed)")
    if stale:
        _rmdir_if_empty(d / INDEX_DIR_NAME)


def migrate_legacy_agents_doc(lib: Library, d: Path) -> None:
    """Move a folder document an AGENTS.md-mode library kept in AGENTS.md to CLAUDE.md."""
    claude, agents = d / DOC_NAME, d / "AGENTS.md"
    c, a = _read(claude), _read(agents)
    if a is not None and _is_librarian_doc(a) and (c is None or c.strip() == ALIAS):
        agents.replace(claude)


def sync_dir(lib: Library, d: Path, children: list[Path], fix: bool,
             had_doc: set[Path] | None = None) -> Report:
    """Bring one folder's document in line with the tree. With fix=False, only report.

    children: the managed subfolders of d.
    had_doc: folders that had a document before this run (used to follow renames).
    """
    report = Report()
    rel = lib.rel(d)
    if fix:
        migrate_legacy_agents_doc(lib, d)
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
    notes = "\n".join(l for l in (sec["subdirs"] or []) if not _is_table_row(l)).strip()
    rendered = render_doc(lib, d, sec["role"] or [], subdirs, sec["head"], sec["tail"],
                          notes, sec["notes"] or [])
    if rendered != original:
        if not existed:
            (report.created if fix else report.drift).append(rel)
        else:
            (report.updated if fix else report.drift).append(rel)
        if fix:
            _write_utf8(doc, rendered)
    remove_legacy_index_files(lib, d, fix, report)

    if _role_is_empty(sec["role"]) or any(not r or r in PLACEHOLDERS for _, r in subdirs):
        report.pending.append(rel)
    depth = 0 if d == lib.root else len(d.relative_to(lib.root).parts)
    if depth > lib.config["maxDepth"]:
        report.warnings.append(
            f"{rel}: folder depth {depth} > {lib.config['maxDepth']} (consider restructuring)")
    return report


def _children_map(lib: Library, dirs: set[Path]) -> dict[Path, list[Path]]:
    children: dict[Path, list[Path]] = defaultdict(list)
    for d in dirs:
        if d != lib.root:
            children[d.parent].append(d)
    return children


def sync_dirs(lib: Library, targets: set[Path] | None, fix: bool) -> Report:
    report = Report()
    if targets is not None and not targets:
        return report
    dirs = managed_dirs(lib, list_files(lib))
    children = _children_map(lib, dirs)
    had_doc = {d for d in dirs if lib.doc_path(d).is_file()}
    if targets is None:
        todo = dirs
    else:
        todo = set()
        for t in targets:
            # a folder that no longer exists, or holds no code, is replaced by its nearest
            # managed ancestor
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
        report.merge(sync_dir(lib, d, children.get(d, []), fix, had_doc))
    return report


def changed_dirs(lib: Library) -> set[Path] | None:
    out = _git(lib.root, "status", "--porcelain", "-z", "--untracked-files=all")
    top = _git(lib.root, "rev-parse", "--show-toplevel")
    if out is None or top is None:
        return None
    base = Path(top.strip()).resolve()  # porcelain paths are relative to the repository root
    paths: set[Path] = set()
    entries = out.split("\0")
    i = 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if len(entry) < 4:
            continue
        status, rel = entry[:2], entry[3:]
        paths.add((base / rel).parent)
        if "R" in status or "C" in status:  # rename: the next entry is the original path
            if i < len(entries) and entries[i]:
                paths.add((base / entries[i]).parent)
            i += 1
    return paths


# ---------------------------------------------------------------- catalog


def catalog_path(lib: Library) -> Path:
    return lib.root / CONFIG_DIR / CATALOG_FILE


def ensure_catalog_ignored(lib: Library) -> None:
    """Keep the derived catalog out of git with a .gitignore inside .librarian."""
    gitignore = lib.root / CONFIG_DIR / ".gitignore"
    text = _read(gitignore) or ""
    if CATALOG_FILE in text.split():
        return
    gitignore.parent.mkdir(parents=True, exist_ok=True)
    _write_utf8(gitignore, text + ("" if not text or text.endswith("\n") else "\n")
                + CATALOG_FILE + "\n")


def _read_catalog(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or data.get("schema") != CATALOG_SCHEMA:
        return {}
    files = data.get("files")
    return files if isinstance(files, dict) else {}


def _write_atomic(path: Path, text: str) -> None:
    """Replace path in one step so a reader never sees a half-written catalog."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n",
                                         dir=path.parent, prefix=".catalog-", delete=False)
    try:
        with handle:
            handle.write(text)
        os.replace(handle.name, path)
    finally:
        if os.path.exists(handle.name):
            os.unlink(handle.name)


def load_catalog(lib: Library, report: Report | None = None) -> dict[str, list]:
    """Symbols of every code file, keyed by root-relative path. Files whose modification
    time and size match the cache are not parsed again; the cache is rewritten only when
    something changed."""
    path = catalog_path(lib)
    cached = _read_catalog(path)
    fresh: dict[str, list] = {}
    changed = False
    for f in list_files(lib):
        if not is_code(f):
            continue
        rel = lib.rel(f)
        try:
            st = f.stat()
        except OSError:
            continue
        stamp = [st.st_mtime_ns, st.st_size]
        hit = cached.get(rel)
        if isinstance(hit, list) and len(hit) == 3 and hit[:2] == stamp:
            fresh[rel] = hit
            continue
        try:
            symbols = [list(s) for s in extract_symbols(f)]
        except Exception as exc:  # keep the previous symbols of a file that fails to parse
            symbols = hit[2] if isinstance(hit, list) and len(hit) == 3 else []
            if report is not None:
                report.warnings.append(f"{rel}: parse failed, keeping previous symbols ({exc})")
        fresh[rel] = [*stamp, symbols]
        changed = True
    if changed or fresh.keys() != cached.keys():
        try:
            ensure_catalog_ignored(lib)
            _write_atomic(path, json.dumps({"schema": CATALOG_SCHEMA, "files": fresh},
                                           ensure_ascii=False, separators=(",", ":")))
        except OSError:
            pass  # another process holds the file (Windows); the next query writes it
    return {rel: entry[2] for rel, entry in fresh.items()}


def folder_role(lib: Library, folder_rel: str, cache: dict[str, str | None]) -> str | None:
    """The folder's role collapsed to one line, or None when it is not written."""
    if folder_rel not in cache:
        text = _read(lib.root / folder_rel / DOC_NAME) if folder_rel != "." else _read(
            lib.root / DOC_NAME)
        role = None
        if text is not None:
            lines = _split_sections(text)["role"]
            if not _role_is_empty(lines):
                role = re.sub(r"\s+", " ", "\n".join(lines)).strip()
                if len(role) > ROLE_PREVIEW_CHARS:
                    role = role[:ROLE_PREVIEW_CHARS - 3].rstrip() + "..."
        cache[folder_rel] = role
    return cache[folder_rel]


def _folder_of(rel: str) -> str:
    parent = Path(rel).parent.as_posix()
    return "." if parent in ("", ".") else parent


def _folder_heading(lib: Library, folder_rel: str, roles: dict) -> str:
    role = folder_role(lib, folder_rel, roles)
    label = "./" if folder_rel == "." else folder_rel + "/"
    return f"[{label}] {role}" if role else f"[{label}]"


def _inside(lib: Library, path: Path) -> bool:
    return path == lib.root or lib.root in path.parents


def _scope_rel(lib: Library, scope: str | None) -> str | None:
    if not scope:
        return None
    rel = lib.rel(Path(scope).resolve())
    return None if rel == "." else rel


def _code_lines(path: Path, start: int, end: int) -> list[str]:
    """The definition's source with line numbers, so a narrow lookup needs no separate read.
    Long definitions are cut after FIND_CODE_LINES lines."""
    try:
        # split on newlines only: splitlines() also breaks on form feeds and U+2028,
        # which would shift every later line number
        lines = path.read_text(encoding="utf-8-sig", errors="replace").split("\n")
    except OSError:
        return []
    last = min(end, len(lines), start + FIND_CODE_LINES - 1)
    out = [f"{n:>6}\t{lines[n - 1]}" for n in range(start, last + 1)]
    if last < end:
        out.append(f"   ... lines {last + 1}-{end} not shown; read that range if needed")
    return out


def find_symbols(lib: Library, pattern: str, scope: str | None = None) -> list[str]:
    try:
        rx = re.compile(pattern, re.IGNORECASE)
    except re.error:
        rx = re.compile(re.escape(pattern), re.IGNORECASE)
    if scope and not _inside(lib, Path(scope).resolve()):
        return [f"{scope}: outside the library at {lib.root.as_posix()}"]
    scope_rel = _scope_rel(lib, scope)
    hits = []
    for rel, symbols in sorted(load_catalog(lib).items()):
        if scope_rel and not (rel == scope_rel or rel.startswith(scope_rel + "/")):
            continue
        # `^name$` must also find methods, whose catalog names carry their container.
        hits.extend((rel, name, start, end) for name, start, end in symbols
                    if rx.search(name) or rx.search(name.rsplit(".", 1)[-1]))
    if not hits:
        exts = " ".join(sorted(e for e in EXT_LANG if e not in DOC_EXTS))
        return [f"No definitions match {pattern!r}. The catalog covers only definitions in "
                f"{exts} files; use Grep for anything else."]
    out: list[str] = []
    roles: dict[str, str | None] = {}
    folder = None
    show_code = len(hits) <= FIND_CODE_HITS
    shown: list[tuple[str, int, int]] = []
    for rel, name, start, end in hits[:FIND_LIMIT]:
        if _folder_of(rel) != folder:
            folder = _folder_of(rel)
            out.append(_folder_heading(lib, folder, roles))
        out.append(f"{rel}:{start}-{end} {name}")
        # A method inside the printed part of a class needs no second copy.
        if show_code and not any(r == rel and s <= start and end <= e for r, s, e in shown):
            out.extend(_code_lines(lib.root / rel, start, end))
            shown.append((rel, start, min(end, start + FIND_CODE_LINES - 1)))
    if len(hits) > FIND_LIMIT:
        out.append(f"... {len(hits) - FIND_LIMIT} more matches; narrow the pattern or "
                   "pass a path")
    return out


def _enclosing(symbols: list, line: int) -> list | None:
    """The innermost definition whose range holds the line."""
    best = None
    for sym in symbols:
        if sym[1] <= line <= sym[2] and (best is None or sym[1] > best[1]
                                         or (sym[1] == best[1] and sym[2] < best[2])):
            best = sym
    return best


def grep_code(lib: Library, pattern: str, scope: str | None = None,
              ignore_case: bool = False) -> list[str]:
    """Lines of code files matching a regex, each grouped under the definition that holds
    it, so finding the caller of a match needs no second lookup."""
    try:
        rx = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
    except re.error:
        rx = re.compile(re.escape(pattern), re.IGNORECASE if ignore_case else 0)
    if scope and not _inside(lib, Path(scope).resolve()):
        return [f"{scope}: outside the library at {lib.root.as_posix()}"]
    scope_rel = _scope_rel(lib, scope)
    out: list[str] = []
    roles: dict[str, str | None] = {}
    folder = None
    shown = total = 0
    files_left: set[str] = set()
    for rel, symbols in sorted(load_catalog(lib).items()):
        if scope_rel and not (rel == scope_rel or rel.startswith(scope_rel + "/")):
            continue
        try:
            text = (lib.root / rel).read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
        group = None
        for n, line in enumerate(text.split("\n"), 1):
            if not rx.search(line):
                continue
            total += 1
            if shown >= GREP_LIMIT:
                files_left.add(rel)
                continue
            if _folder_of(rel) != folder:
                folder = _folder_of(rel)
                out.append(_folder_heading(lib, folder, roles))
            sym = _enclosing(symbols, n)
            key = tuple(sym) if sym else rel
            if key != group:
                group = key
                out.append(f"{rel}:{sym[1]}-{sym[2]} {sym[0]}" if sym
                           else f"{rel} (outside any definition)")
            body = line.strip()
            if len(body) > GREP_LINE_CHARS:
                body = body[:GREP_LINE_CHARS - 3] + "..."
            out.append(f"  {n}: {body}")
            shown += 1
    if not total:
        return [f"No code line matches {pattern!r}. Only code files are searched; use Grep "
                "for documents and other files."]
    if total > shown:
        out.append(f"... {total - shown} more matches in {len(files_left)} file(s); narrow "
                   "the pattern or pass a path")
    return out


def outline(lib: Library, target: str) -> list[str]:
    path = Path(target).resolve()
    if not _inside(lib, path):
        return [f"{target}: outside the library at {lib.root.as_posix()}"]
    roles: dict[str, str | None] = {}
    if path.is_file():
        rel = lib.rel(path)
        symbols = load_catalog(lib).get(rel)
        if symbols is None:  # documentation or an excluded file: read it directly
            try:
                symbols = [list(s) for s in extract_symbols(path)]
            except Exception:  # unparsable, like load_catalog's parse failures
                symbols = []
        out = [_folder_heading(lib, _folder_of(rel), roles), rel]
        out.extend(f"  {start}-{end} {name}" for name, start, end in symbols)
        if not symbols:
            out.append("  (no definitions found; read the file or use Grep)")
        return out
    if not path.is_dir():
        return [f"{target}: no such file or folder"]
    folder_rel = lib.rel(path)
    out = [_folder_heading(lib, folder_rel, roles)]
    for rel, symbols in sorted(load_catalog(lib).items()):
        if _folder_of(rel) != folder_rel:
            continue
        names = [name for name, _, _ in symbols]
        shown = ", ".join(names[:OUTLINE_NAMES_PER_FILE])
        more = f", +{len(names) - OUTLINE_NAMES_PER_FILE} more" if len(
            names) > OUTLINE_NAMES_PER_FILE else ""
        out.append(f"{Path(rel).name}: {shown}{more}" if names else f"{Path(rel).name}: -")
    if len(out) == 1:
        out.append("(no code files directly in this folder; see its subfolders)")
    return out


# ---------------------------------------------------------------- long documents


def prose_line_count(text: str) -> int:
    """Lines of a folder document that people write: everything except the subfolder table
    rows the script maintains and a legacy generated index."""
    sec = _split_sections(text)
    generated = len(sec["index"] or []) + sum(1 for l in sec["subdirs"] or [] if _is_table_row(l))
    return len(text.splitlines()) - generated


def find_overlong_docs(lib: Library) -> list[tuple[str, int]]:
    """Find folder documents and Claude rule files longer than maxDocLines."""
    folder_docs = {lib.doc_path(d) for d in managed_dirs(lib, list_files(lib))}
    candidates = set(folder_docs)
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
        count = prose_line_count(text) if path in folder_docs else len(text.splitlines())
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


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=True) + "\n")


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


def _pending_listing(pending: list[str]) -> str:
    ordered = sorted(pending, key=lambda r: (-len(Path(r).parts), r))
    listing = ", ".join(ordered[:PENDING_LIST_LIMIT])
    if len(ordered) > PENDING_LIST_LIMIT:
        listing += (f", and {len(ordered) - PENDING_LIST_LIMIT} more (run /rebuild-library "
                    "to fill many folders at once)")
    return listing


def hook_stop(payload: dict) -> None:
    cwd = Path(payload.get("cwd") or os.getcwd())
    lib = load_library(cwd)
    if lib is None:
        _emit({})
        return
    report = sync_dirs(lib, changed_dirs(lib), fix=True)
    out: dict = {}
    # Only folders this turn created (and the parents whose tables gained a row) block the
    # agent. Roles that were already empty belong to /rebuild-library: forcing an extra turn
    # whenever a file in such a folder changes costs far more context than it is worth.
    created = set(report.created)
    new_rows = {_folder_of(rel) for rel in created if rel != "."}
    blocking = [rel for rel in report.pending if rel in created or rel in new_rows]
    notices = list(report.warnings)
    older = len(report.pending) - len(blocking)
    if older:
        notices.append(f"{older} folder document(s) touched this turn still have empty "
                       "roles; run /rebuild-library to fill them")
    version_notice = _version_notice(lib.config.get("libraryVersion"), plugin_version())
    if version_notice:
        notices.append(version_notice)
    if notices:
        out["systemMessage"] = "librarian: " + "; ".join(notices)
    active = _is_true(payload.get("stop_hook_active"))
    if blocking and not active:
        out["decision"] = "block"
        out["reason"] = (
            f"librarian: write the '{lib.strings['role']}' section (1-3 sentences on the "
            "folder's responsibility) and any empty role cells in the subfolder table of: "
            f"{_pending_listing(blocking)}. Write in the library language "
            f"({lib.language}). Do not describe functions or files.")
    _emit(out)


def _python_command() -> str:
    """The interpreter running this hook, by name when PATH finds that same name (shorter,
    and it matches permission rules such as `Bash(python:*)`), else by full path."""
    name = Path(sys.executable).stem
    found = shutil.which(name)
    try:
        if found and Path(found).resolve() == Path(sys.executable).resolve():
            return name
    except OSError:
        pass
    return f'"{Path(sys.executable).as_posix()}"'


def _lookup_instructions() -> str:
    script = f'{_python_command()} "{Path(__file__).resolve().as_posix()}"'
    return "\n".join([
        "## Code lookup (agent-librarian)",
        "",
        f"- Find where a function, class, or method is defined: `{script} find <regex> "
        "[path]` prints `path:start-end Symbol` grouped under each folder's role, and the "
        f"code itself when at most {FIND_CODE_HITS} definitions match.",
        f"- Find call sites, field writes, or strings in code: `{script} grep [-i] <regex> "
        "[path]` prints matching lines grouped under the function that holds each one "
        "(`path:start-end Symbol`). Prefer it to Grep for code; use Grep for other files.",
        f"- List a file's or folder's definitions with line ranges: `{script} outline "
        "<file-or-folder>`.",
        "- Read only a reported line range instead of the whole file.",
    ])


def _refresh_catalog_in_background(lib: Library) -> None:
    """Build or refresh the catalog without delaying session start."""
    kwargs: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
                    "stderr": subprocess.DEVNULL, "cwd": lib.root}
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED | NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    try:
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--root",
                          str(lib.root), "catalog"], **kwargs)
    except OSError:
        pass  # `find` and `outline` build the catalog themselves


def hook_session_start(payload: dict) -> None:
    cwd = Path(payload.get("cwd") or os.getcwd())
    lib = load_library(cwd)
    if lib is None:
        return
    _refresh_catalog_in_background(lib)
    context = [_lookup_instructions()]
    overlong = find_overlong_docs(lib)
    if overlong:
        listing = ", ".join(f"{rel} ({count} lines)" for rel, count in overlong)
        context.append(
            f"librarian: these documents exceed maxDocLines {lib.config['maxDocLines']} "
            f"(subfolder table rows excluded): {listing}. When you next edit one, split its "
            "human-written text by topic and leave a one-line pointer (see the rule-creator "
            "skill).")
    _emit({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                  "additionalContext": "\n".join(context)}})


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


def _overlong_warnings(lib: Library) -> list[str]:
    limit = lib.config["maxDocLines"]
    return [f"{rel}: {count} lines > maxDocLines {limit}; split human-written text by topic "
            "and leave a one-line pointer (see the rule-creator skill)"
            for rel, count in find_overlong_docs(lib)]


def cmd_init(args) -> None:
    root = Path(args.root).resolve()
    cfg_path = root / CONFIG_DIR / CONFIG_FILE
    cfg = _read_config(cfg_path)
    if args.language:
        cfg["language"] = args.language
    if args.exclude:
        cfg["exclude"] = sorted(set(cfg.get("exclude", [])) | set(args.exclude))
    cfg["libraryVersion"] = plugin_version()
    _write_config(root, cfg)
    lib = Library(root=root, config=cfg)
    ensure_catalog_ignored(lib)
    print(f"[config] {cfg_path.relative_to(root).as_posix()}")
    # a library rebuilt with init gets the new version stamp, so the Stop hook no longer
    # asks for /update-library; the old rules skill is cleaned up here as well
    _print_report(remove_legacy_skill(lib))


def cmd_scaffold(args) -> None:
    lib = _require(Path(args.root))
    dirs = managed_dirs(lib, list_files(lib))
    children = _children_map(lib, dirs)
    report = Report()
    for d in sorted(dirs, key=lambda p: len(p.parts), reverse=True):
        if not lib.doc_path(d).is_file():
            report.merge(sync_dir(lib, d, children.get(d, []), fix=True))
    _print_report(Report(created=report.created, warnings=report.warnings))


def cmd_index(args) -> None:
    lib = _require(Path(args.root))
    targets = None if args.all else {Path(p).resolve() for p in args.dirs}
    if targets is not None and not targets:
        sys.exit("Specify folders or use --all.")
    report = sync_dirs(lib, targets, fix=True)
    catalog = load_catalog(lib, report)
    _print_report(Report(created=report.created, updated=report.updated,
                         warnings=report.warnings))
    print(f"[catalog] {sum(len(s) for s in catalog.values())} definitions in "
          f"{len(catalog)} files")


def cmd_catalog(args) -> None:
    lib = _require(Path(args.root))
    report = Report()
    catalog = load_catalog(lib, report)
    _print_report(report)
    print(f"[catalog] {sum(len(s) for s in catalog.values())} definitions in "
          f"{len(catalog)} files")


def cmd_find(args) -> None:
    lib = _require(Path(args.root))
    print("\n".join(find_symbols(lib, args.pattern, args.path)))


def cmd_grep(args) -> None:
    lib = _require(Path(args.root))
    print("\n".join(grep_code(lib, args.pattern, args.path, args.ignore_case)))


def cmd_outline(args) -> None:
    lib = _require(Path(args.root))
    print("\n".join(outline(lib, args.path)))


def cmd_check(args) -> None:
    lib = _require(Path(args.root))
    targets = changed_dirs(lib) if args.changed else None
    report = sync_dirs(lib, targets, fix=args.fix)
    report.warnings.extend(_overlong_warnings(lib))
    _print_report(report)
    if report.drift or report.pending:
        sys.exit(1)


def cmd_pending(args) -> None:
    lib = _require(Path(args.root))
    report = sync_dirs(lib, None, fix=False)
    for rel in sorted(report.pending, key=lambda r: (-len(Path(r).parts), r)):
        print(rel)


def unmanaged_folder_docs(lib: Library) -> list[str]:
    """Folder documents older versions wrote in folders that hold no code."""
    files = list_files(lib)
    dirs = managed_dirs(lib, files)
    found = []
    for f in files:
        if f.name == DOC_NAME and f.parent not in dirs:
            text = _read(f)
            if text is not None and _is_librarian_doc(text):
                found.append(lib.rel(f))
    return sorted(found)


def cmd_update(args) -> None:
    lib = _require(Path(args.root))
    report = remove_legacy_skill(lib)
    if lib.config["maxDocLines"] == LEGACY_DEFAULT_MAX_DOC_LINES:
        lib.config["maxDocLines"] = DEFAULT_CONFIG["maxDocLines"]
        report.updated.append(
            f"maxDocLines {LEGACY_DEFAULT_MAX_DOC_LINES} -> {DEFAULT_CONFIG['maxDocLines']} "
            "(the old default; folder documents no longer hold the index)")
    report.merge(sync_dirs(lib, None, fix=True))
    report.warnings.extend(
        f"{rel}: this folder holds no code, so its document is no longer maintained; "
        "delete it once you have kept anything you need from it"
        for rel in unmanaged_folder_docs(lib))
    load_catalog(lib, report)

    # migration: this intentionally writes the full config, so keys added in newer versions
    # (filled with defaults by _read_config) appear in the file and removed keys disappear.
    # It runs last so that a failure above keeps the old version, and the Stop hook keeps
    # asking for the update.
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
        if args.event == "session-start":
            hook_session_start(payload)
        elif args.event == "stop":
            hook_stop(payload)
        # post-edit: hooks.json from before the catalog may still call it; nothing to do
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
    p.add_argument("--exclude", nargs="*", default=[])
    p.set_defaults(func=cmd_init)

    sub.add_parser("scaffold").set_defaults(func=cmd_scaffold)

    p = sub.add_parser("index", help="sync folder documents and refresh the catalog")
    p.add_argument("dirs", nargs="*")
    p.add_argument("--all", action="store_true")
    p.set_defaults(func=cmd_index)

    sub.add_parser("catalog", help="refresh the catalog only").set_defaults(func=cmd_catalog)

    p = sub.add_parser("find", help="find definitions whose name matches a regex")
    p.add_argument("pattern")
    p.add_argument("path", nargs="?", help="limit the search to this file or folder")
    p.set_defaults(func=cmd_find)

    p = sub.add_parser("grep", help="search code lines, grouped by the definition holding "
                                    "each match")
    p.add_argument("pattern")
    p.add_argument("path", nargs="?", help="limit the search to this file or folder")
    p.add_argument("-i", "--ignore-case", action="store_true")
    p.set_defaults(func=cmd_grep)

    p = sub.add_parser("outline", help="list a file's or folder's definitions")
    p.add_argument("path")
    p.set_defaults(func=cmd_outline)

    p = sub.add_parser("check")
    p.add_argument("--fix", action="store_true")
    p.add_argument("--changed", action="store_true")
    p.set_defaults(func=cmd_check)

    sub.add_parser("pending").set_defaults(func=cmd_pending)

    sub.add_parser("update").set_defaults(func=cmd_update)

    p = sub.add_parser("hook")
    p.add_argument("event", choices=["stop", "session-start", "post-edit"])
    p.set_defaults(func=cmd_hook)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
