import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import librarian as lb  # noqa: E402

EN = lb.DOC_STRINGS["en"]
KO = lb.DOC_STRINGS["ko"]
ORIGINAL_REFRESH = lb._refresh_catalog_in_background

SOURCES = {
    "src/auth/auth.py": (
        "import os\n"
        "\n"
        "class Session:\n"
        "    def refresh(self):\n"
        "        def inner():\n"
        "            pass\n"
        "\n"
        "@decorator\n"
        "def login(user):\n"
        "    return user\n"
    ),
    "src/api/svc.ts": (
        "export class Svc {\n"
        "  run(): void {}\n"
        "}\n"
        "export const handler = () => 1;\n"
        "describe('x', () => { it('y', () => {}); });\n"
    ),
    "web/main.go": "package web\n\ntype S struct{}\n\nfunc (s *S) Do() {}\n\nfunc Top() {}\n",
    "native/lib.cpp": "namespace ns {\nclass C { public: void m(); };\nvoid C::m() {}\n}\nint *make() { return 0; }\n",
    "native/lib.rs": "struct P;\nimpl P {\n    fn new() -> P { P }\n}\nfn main() {}\n",
    "native/J.java": "class J {\n  J() {}\n  void run() {}\n}\n",
    "native/K.cs": "namespace N {\n class K {\n  public void M() {}\n }\n}\n",
    "assets/logo.txt": "not code\n",
}


def git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture(autouse=True)
def refresh_calls(monkeypatch):
    """Session start spawns a background catalog refresh; record it instead of spawning."""
    calls = []
    monkeypatch.setattr(lb, "_refresh_catalog_in_background", calls.append)
    return calls


@pytest.fixture
def project(tmp_path):
    for rel, text in SOURCES.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    git(tmp_path, "init", "-q")
    return tmp_path


def run(root, *argv):
    lb.main(["--root", str(root), *argv])


def init(root, language=None):
    extra = ["--language", language] if language else []
    run(root, "init", *extra)
    run(root, "scaffold")


def library(root):
    return lb.load_library(Path(root))


def catalog(root):
    return lb.load_catalog(library(root))


def root_doc(project):
    return (project / "CLAUDE.md").read_text(encoding="utf-8")


def plugin_version_from_manifest():
    return json.loads((REPO_ROOT / ".claude-plugin/plugin.json").read_text(
        encoding="utf-8"))["version"]


def commit_all(project):
    git(project, "add", "-A")
    git(project, "-c", "user.email=a@b", "-c", "user.name=t", "commit", "-qm", "c")


def hook(event, payload):
    stdin, stdout = sys.stdin, sys.stdout
    sys.stdin = io.TextIOWrapper(io.BytesIO(json.dumps(payload).encode("utf-8")), encoding="utf-8")
    sys.stdout = io.StringIO()
    try:
        lb.main(["hook", event])
        return sys.stdout.getvalue()
    finally:
        sys.stdin, sys.stdout = stdin, stdout


def output(capsys, root, *argv):
    capsys.readouterr()
    run(root, *argv)
    return capsys.readouterr().out


def set_role(project, rel, role):
    doc = project / rel / "CLAUDE.md"
    doc.write_text(doc.read_text(encoding="utf-8").replace(EN["placeholder"], role, 1),
                   encoding="utf-8")


def _fill_all_roles(project):
    for doc in project.rglob("CLAUDE.md"):
        if ".librarian" in doc.parts:
            continue
        text = doc.read_text(encoding="utf-8").replace(EN["placeholder"], "role")
        doc.write_text(text, encoding="utf-8")


def find_bash():
    bash = shutil.which("bash")
    if bash is None or (os.name == "nt" and "system32" in bash.lower()):
        return None  # no shell, or the WSL launcher, which cannot see this Python
    return bash


def run_hooks_json_command(event_key, cwd, payload):
    bash = find_bash()
    if bash is None:
        pytest.skip("bash is needed to expand ${CLAUDE_PLUGIN_ROOT} in hooks.json")
    hooks = json.loads((REPO_ROOT / "hooks/hooks.json").read_text(encoding="utf-8"))
    command = hooks["hooks"][event_key][0]["hooks"][0]["command"]
    env = {**os.environ, "CLAUDE_PLUGIN_ROOT": REPO_ROOT.as_posix(), "PYTHONUTF8": "1"}
    return subprocess.run([bash, "-c", command], cwd=cwd, env=env,
                          input=json.dumps(payload).encode("utf-8"),
                          capture_output=True, timeout=60)


# ---------------------------------------------------------------- catalog extraction


@pytest.mark.parametrize("rel,expected", [
    ("src/auth/auth.py", [("Session", 3, 6), ("Session.refresh", 4, 6), ("Session.refresh.inner", 5, 6), ("login", 9, 10)]),
    ("src/api/svc.ts", [("Svc", 1, 3), ("Svc.run", 2, 2), ("handler", 4, 4),
                        ("describe('x')", 5, 5), ("it('y')", 5, 5)]),
    ("web/main.go", [("S", 3, 3), ("S.Do", 5, 5), ("Top", 7, 7)]),
    ("native/lib.cpp", [("C", 2, 2), ("C::m", 3, 3), ("make", 5, 5)]),
    ("native/lib.rs", [("P", 1, 1), ("P", 2, 4), ("P.new", 3, 3), ("main", 5, 5)]),
    ("native/J.java", [("J", 1, 4), ("J.J", 2, 2), ("J.run", 3, 3)]),
    ("native/K.cs", [("K", 2, 4), ("K.M", 3, 3)]),
])
def test_catalog_holds_symbols_with_line_ranges(project, rel, expected):
    init(project)
    assert [tuple(s) for s in catalog(project)[rel]] == expected


def test_catalog_skips_non_code_files(project):
    init(project)
    (project / "src/README.md").write_text("# Readme\n", encoding="utf-8")
    keys = set(catalog(project))
    assert "assets/logo.txt" not in keys and "src/README.md" not in keys
    assert len(keys) == 7


def test_anonymous_test_callbacks_are_found_and_refreshed(project, capsys):
    source = project / "src/api/callbacks.spec.ts"
    source.write_text(
        "test('한국어 | 테스트', async ({ game }) => {\n"
        "  await game.run();\n"
        "});\n"
        "it('second', function () {\n"
        "  run();\n"
        "});\n"
        "const runTest = async () => {};\n", encoding="utf-8")
    init(project, language="ko")

    out = output(capsys, project, "find", "test|second")
    assert "src/api/callbacks.spec.ts:1-3 test('한국어 | 테스트')" in out
    assert "src/api/callbacks.spec.ts:4-6 it('second')" in out
    assert "src/api/callbacks.spec.ts:7-7 runTest" in out

    source.write_text("\n" + source.read_text(encoding="utf-8"), encoding="utf-8")
    run(project, "index", str(source.parent))
    out = output(capsys, project, "find", "test|second")
    assert "src/api/callbacks.spec.ts:2-4 test('한국어 | 테스트')" in out
    assert "src/api/callbacks.spec.ts:5-7 it('second')" in out


# ---------------------------------------------------------------- scaffold / index


def test_scaffold_creates_hierarchy(project):
    init(project)
    for d in [".", "src", "src/auth", "src/api", "web", "native"]:
        assert (project / d / "CLAUDE.md").is_file(), d
    root = root_doc(project)
    assert root.startswith(f"# {project.name}\n\n{EN['role']}\n")  # no rules or skill pointer
    assert "| src/ |" in root and "| web/ |" in root
    sub = (project / "src/auth/CLAUDE.md").read_text(encoding="utf-8")
    assert sub.startswith("# Parent: ../CLAUDE.md")
    for doc in project.rglob("CLAUDE.md"):
        text = doc.read_text(encoding="utf-8")
        assert lb.INDEX_START not in text and "| File |" not in text, doc
    assert not list(project.rglob("index.md"))


def test_folders_without_code_get_no_document(project):
    (project / "docs/guide").mkdir(parents=True)
    (project / "docs/guide/howto.md").write_text("# How to\n", encoding="utf-8")
    (project / "pkg/inner").mkdir(parents=True)
    (project / "pkg/inner/a.py").write_text("def a(): pass\n", encoding="utf-8")
    init(project)

    for d in ["assets", "docs", "docs/guide"]:
        assert not (project / d / "CLAUDE.md").exists(), d
    for d in ["pkg", "pkg/inner"]:  # a folder whose code is only below it is managed too
        assert (project / d / "CLAUDE.md").is_file(), d
    root = root_doc(project)
    assert "| assets/ |" not in root and "| docs/ |" not in root and "| pkg/ |" in root
    lib = library(project)
    rels = {lib.rel(d) for d in lb.managed_dirs(lib, lb.list_files(lib))}
    assert rels == {".", "src", "src/auth", "src/api", "web", "native", "pkg", "pkg/inner"}


def test_scaffold_does_not_overwrite(project):
    (project / "src/CLAUDE.md").write_text("user document\n", encoding="utf-8")
    init(project)
    assert (project / "src/CLAUDE.md").read_text(encoding="utf-8") == "user document\n"


def test_index_preserves_human_text(project):
    init(project)
    doc = project / "src/auth/CLAUDE.md"
    text = doc.read_text(encoding="utf-8").replace(EN["placeholder"], "Auth module.\n\n- detail")
    text += "\n## Extra\n\nsection written by a human\n"
    doc.write_text(text, encoding="utf-8")
    src = project / "src/auth/auth.py"
    src.write_text("# header\n\n" + src.read_text(encoding="utf-8"), encoding="utf-8")
    run(project, "index", str(project / "src/auth"))
    out = doc.read_text(encoding="utf-8")
    assert "Auth module.\n\n- detail" in out and "section written by a human" in out
    assert ["Session", 5, 8] in catalog(project)["src/auth/auth.py"]
    run(project, "index", str(project / "src/auth"))
    assert doc.read_text(encoding="utf-8") == out  # idempotent


def test_index_refreshes_catalog_and_reports_it(project, capsys):
    init(project)
    out = output(capsys, project, "index", "--all")
    assert re.search(r"^\[catalog\] 24 definitions in 7 files$", out, re.MULTILINE), out
    assert (project / ".librarian/catalog.json").is_file()


def test_index_requires_folders_or_all(project):
    init(project)
    with pytest.raises(SystemExit):
        run(project, "index")


def test_exclude_and_gitignore(project):
    (project / ".gitignore").write_text("gen/\n", encoding="utf-8")
    (project / "gen").mkdir()
    (project / "gen/x.py").write_text("def f(): pass\n", encoding="utf-8")
    (project / "node_modules/p").mkdir(parents=True)
    (project / "node_modules/p/i.js").write_text("function f(){}\n", encoding="utf-8")
    (project / "tmpx").mkdir()
    (project / "tmpx/t.py").write_text("def f(): pass\n", encoding="utf-8")
    run(project, "init", "--exclude", "tmpx")
    run(project, "scaffold")
    for d in ["gen", "node_modules", "tmpx"]:
        assert not (project / d / "CLAUDE.md").exists(), d
        assert not any(rel.startswith(d + "/") for rel in catalog(project)), d


def test_init_installs_no_skill_and_ignores_catalog(project):
    init(project)
    assert not (project / ".librarian/skills").exists()
    assert not any((project / agent / "skills").exists() for agent in (".claude", ".agents", ".codex"))
    assert not (project / ".gitignore").exists()
    assert (project / ".librarian/.gitignore").read_text(encoding="utf-8") == "catalog.json\n"


def test_pending_deepest_first(project, capsys):
    init(project)
    lines = output(capsys, project, "pending").split()
    depths = [0 if l == "." else len(Path(l).parts) for l in lines]
    assert depths == sorted(depths, reverse=True) and lines[-1] == "."


def test_many_files_is_fast(tmp_path):
    for d in range(200):
        for f in range(15):
            p = tmp_path / f"pkg{d % 20}" / f"mod{d}" / f"f{f}.py"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("def f(): pass\n", encoding="utf-8")
    git(tmp_path, "init", "-q")
    run(tmp_path, "init")
    start = time.perf_counter()
    run(tmp_path, "index", "--all")
    run(tmp_path, "pending")
    run(tmp_path, "find", "f")
    assert time.perf_counter() - start < 15


# ---------------------------------------------------------------- legacy migration


LEGACY_BLOCK = (f"{lb.INDEX_START}\n| File | Function | Start | End |\n|---|---|---|---|\n"
                f"| auth.py | Session | 3 | 6 |\n{lb.INDEX_END}\n")


def make_legacy_index(project):
    folder = project / "src/auth"
    doc = folder / "CLAUDE.md"
    doc.write_text(doc.read_text(encoding="utf-8").replace(
        "## Notes", "## Notes\n\nKeep this note.\n\n" + LEGACY_BLOCK), encoding="utf-8")
    (folder / "index.md").write_text(lb.GENERATED_MARKER + "\n| auth.py | Session | 3 | 6 |\n",
                                     encoding="utf-8")
    (folder / "index").mkdir()
    (folder / "index/auth.py.md").write_text(lb.GENERATED_MARKER + "\nrows\n", encoding="utf-8")
    human = project / "src/api/index.md"
    human.write_text("# Human index\n", encoding="utf-8")
    return doc, human


def test_check_reports_legacy_index_as_drift_without_writing(project, capsys):
    init(project)
    _fill_all_roles(project)
    doc, human = make_legacy_index(project)
    before = doc.read_text(encoding="utf-8")

    with pytest.raises(SystemExit) as error:
        run(project, "check")

    assert error.value.code == 1
    out = capsys.readouterr().out
    assert "[drift] src/auth\n" in out
    assert "[drift] src/auth/index.md (legacy index)" in out
    assert "[drift] src/auth/index/auth.py.md (legacy index)" in out
    assert "src/api/index.md" not in out
    assert doc.read_text(encoding="utf-8") == before
    assert (project / "src/auth/index.md").is_file()


def test_fix_removes_legacy_index_block_and_generated_files(project, capsys):
    init(project)
    _fill_all_roles(project)
    doc, human = make_legacy_index(project)

    out = output(capsys, project, "check", "--fix")

    text = doc.read_text(encoding="utf-8")
    assert lb.INDEX_START not in text and lb.INDEX_END not in text and "| auth.py |" not in text
    assert "Keep this note." in text
    assert not (project / "src/auth/index.md").exists()
    assert not (project / "src/auth/index").exists()
    assert human.read_text(encoding="utf-8") == "# Human index\n"  # no marker: human-owned
    assert "[updated] src/auth/index.md (removed)" in out
    run(project, "check")  # clean now: no SystemExit


def test_index_dir_with_human_files_is_kept(project):
    init(project)
    folder = project / "src/auth"
    (folder / "index").mkdir()
    (folder / "index/auth.py.md").write_text(lb.GENERATED_MARKER + "\n", encoding="utf-8")
    (folder / "index/keep.md").write_text("human file\n", encoding="utf-8")
    run(project, "index", "--all")
    assert not (folder / "index/auth.py.md").exists()
    assert (folder / "index/keep.md").read_text(encoding="utf-8") == "human file\n"


@pytest.mark.parametrize("claude_text", ["@AGENTS.md\n", None], ids=["alias", "no-claude"])
def test_legacy_agents_doc_moves_to_claude_md(project, claude_text):
    init(project)
    folder = project / "lib"
    folder.mkdir()
    (folder / "x.py").write_text("def x(): pass\n", encoding="utf-8")
    (folder / "AGENTS.md").write_text(
        f"# Parent: ../AGENTS.md\n\n{EN['role']}\n\nLibrary code.\n\n{EN['notes']}\n",
        encoding="utf-8")
    if claude_text is not None:
        (folder / "CLAUDE.md").write_text(claude_text, encoding="utf-8")
    human_agents = project / "AGENTS.md"
    human_agents.write_text("# Shared rules\n", encoding="utf-8")

    run(project, "index", "--all")

    text = (folder / "CLAUDE.md").read_text(encoding="utf-8")
    assert text.startswith("# Parent: ../CLAUDE.md\n")
    assert "Library code." in text
    assert not (folder / "AGENTS.md").exists()
    assert human_agents.read_text(encoding="utf-8") == "# Shared rules\n"
    assert "| lib/ |" in root_doc(project)


def test_human_agents_md_next_to_claude_md_is_left_alone(project):
    init(project)
    agents = project / "src/AGENTS.md"
    agents.write_text(f"{EN['role']}\n\nHuman-kept copy.\n", encoding="utf-8")
    before = (project / "src/CLAUDE.md").read_text(encoding="utf-8")
    run(project, "index", "--all")
    assert agents.read_text(encoding="utf-8") == f"{EN['role']}\n\nHuman-kept copy.\n"
    assert (project / "src/CLAUDE.md").read_text(encoding="utf-8") == before


# ---------------------------------------------------------------- catalog


def count_extractions(monkeypatch):
    calls = []
    real = lb.extract_symbols

    def counting(path):
        calls.append(Path(path).name)
        return real(path)

    monkeypatch.setattr(lb, "extract_symbols", counting)
    return calls


def test_catalog_reuses_unchanged_files(project, monkeypatch):
    init(project)
    calls = count_extractions(monkeypatch)
    lib = library(project)
    first = lb.load_catalog(lib)
    assert len(calls) == len(first) == 7
    cache = project / ".librarian/catalog.json"
    stamp = cache.stat().st_mtime_ns

    calls.clear()
    assert lb.load_catalog(lib) == first
    assert calls == []
    assert cache.stat().st_mtime_ns == stamp  # nothing changed, nothing written

    src = project / "src/auth/auth.py"
    src.write_text(src.read_text(encoding="utf-8") + "\ndef logout():\n    pass\n",
                   encoding="utf-8")
    after = lb.load_catalog(lib)
    assert calls == ["auth.py"]
    assert ["logout", 12, 13] in after["src/auth/auth.py"]

    calls.clear()
    (project / "web/main.go").unlink()
    after = lb.load_catalog(lib)
    assert calls == [] and "web/main.go" not in after
    assert "web/main.go" not in json.loads(cache.read_text(encoding="utf-8"))["files"]


def test_catalog_with_other_schema_is_rebuilt(project, monkeypatch):
    init(project)
    lb.load_catalog(library(project))
    cache = project / ".librarian/catalog.json"
    data = json.loads(cache.read_text(encoding="utf-8"))
    data["schema"] = lb.CATALOG_SCHEMA + 1
    cache.write_text(json.dumps(data), encoding="utf-8")
    calls = count_extractions(monkeypatch)
    lb.load_catalog(library(project))
    assert len(calls) == 7
    assert json.loads(cache.read_text(encoding="utf-8"))["schema"] == lb.CATALOG_SCHEMA


def test_catalog_file_format_and_gitignore(project):
    run(project, "init")
    (project / ".librarian/.gitignore").unlink()
    lb.load_catalog(library(project))
    data = json.loads((project / ".librarian/catalog.json").read_text(encoding="utf-8"))
    assert data["schema"] == lb.CATALOG_SCHEMA
    mtime_ns, size, symbols = data["files"]["web/main.go"]
    st = (project / "web/main.go").stat()
    assert [mtime_ns, size] == [st.st_mtime_ns, st.st_size]
    assert symbols == [["S", 3, 3], ["S.Do", 5, 5], ["Top", 7, 7]]
    assert (project / ".librarian/.gitignore").read_text(encoding="utf-8") == "catalog.json\n"
    assert not list((project / ".librarian").glob(".catalog-*"))  # no temp file left behind
    ignored = subprocess.run(["git", "check-ignore", ".librarian/catalog.json"], cwd=project,
                             capture_output=True)
    assert ignored.returncode == 0


def test_ensure_catalog_ignored_appends_once(project):
    run(project, "init")
    gitignore = project / ".librarian/.gitignore"
    gitignore.write_text("other", encoding="utf-8")
    lib = library(project)
    lb.ensure_catalog_ignored(lib)
    lb.ensure_catalog_ignored(lib)
    assert gitignore.read_text(encoding="utf-8") == "other\ncatalog.json\n"


def test_atomic_write_keeps_old_catalog_when_replace_fails(tmp_path, monkeypatch):
    target = tmp_path / "catalog.json"
    target.write_text("old", encoding="utf-8")

    def failing_replace(src, dst):
        raise OSError("disk full")

    with monkeypatch.context() as patch:
        patch.setattr(lb.os, "replace", failing_replace)
        with pytest.raises(OSError):
            lb._write_atomic(target, "new")
    assert target.read_text(encoding="utf-8") == "old"
    assert [p.name for p in tmp_path.iterdir()] == ["catalog.json"]


def test_parse_failure_keeps_previous_symbols(project, capsys):
    init(project)
    before = catalog(project)["src/auth/auth.py"]
    (project / "src/auth/auth.py").write_text("def broken(:\n", encoding="utf-8")
    (project / "src/auth/new.py").write_text("def broken(:\n", encoding="utf-8")

    out = output(capsys, project, "catalog")

    assert "[warning] src/auth/auth.py: parse failed, keeping previous symbols" in out
    assert "[warning] src/auth/new.py: parse failed" in out
    after = catalog(project)
    assert after["src/auth/auth.py"] == before
    assert after["src/auth/new.py"] == []


def test_parse_failure_without_report_is_silent(project):
    init(project)
    (project / "src/auth/auth.py").write_text("def broken(:\n", encoding="utf-8")
    assert catalog(project)["src/auth/auth.py"] == []  # no previous catalog to keep from


# ---------------------------------------------------------------- find


def test_find_groups_by_folder_with_role_heading(project, capsys):
    init(project)
    set_role(project, "src/auth", "Login and\nsessions.")
    out = output(capsys, project, "find", "SESSION").splitlines()
    assert out == ["[src/auth/] Login and sessions.",
                   "src/auth/auth.py:3-6 Session",
                   "     3\tclass Session:",
                   "     4\t    def refresh(self):",
                   "     5\t        def inner():",
                   "     6\t            pass",
                   "src/auth/auth.py:4-6 Session.refresh",
                   "src/auth/auth.py:5-6 Session.refresh.inner"]
    out = output(capsys, project, "find", "^(svc|top)$").splitlines()
    assert out == ["[src/api/]", "src/api/svc.ts:1-3 Svc", "     1\texport class Svc {",
                   "     2\t  run(): void {}", "     3\t}",
                   "[web/]", "web/main.go:7-7 Top", "     7\tfunc Top() {}"]


def test_find_anchored_pattern_matches_method_names(project, capsys):
    init(project)
    out = output(capsys, project, "find", "^refresh$").splitlines()
    assert [line for line in out if not line.startswith((" ", "["))] == [
        "src/auth/auth.py:4-6 Session.refresh"]


def test_find_prints_code_only_for_narrow_lookups(project, capsys):
    big = project / "src/big/big.py"
    big.parent.mkdir()
    body = "".join(f"    x = {i}\n" for i in range(lb.FIND_CODE_LINES + 5))
    big.write_text("def huge():\n" + body, encoding="utf-8")
    init(project)
    out = output(capsys, project, "find", "^huge$").splitlines()
    assert len(out) == 2 + lb.FIND_CODE_LINES + 1
    last = 1 + lb.FIND_CODE_LINES + 5
    assert out[-1] == (f"   ... lines {lb.FIND_CODE_LINES + 1}-{last} not shown; "
                       "read that range if needed")
    out = output(capsys, project, "find", ".").splitlines()
    assert not any("\t" in line for line in out)


def test_grep_groups_matches_under_enclosing_definition(project, capsys):
    init(project)
    set_role(project, "src/auth", "Login.")
    out = output(capsys, project, "grep", "pass|import|user").splitlines()
    assert out[:7] == ["[src/auth/] Login.",
                       "src/auth/auth.py (outside any definition)",
                       "  1: import os",
                       "src/auth/auth.py:5-6 Session.refresh.inner",
                       "  6: pass",
                       "src/auth/auth.py:9-10 login",
                       "  9: def login(user):"]
    assert out[7] == "  10: return user"


def test_grep_case_scope_and_misses(project, capsys):
    init(project)
    assert output(capsys, project, "grep", "SESSION").startswith("No code line matches")
    out = output(capsys, project, "grep", "-i", "SESSION", str(project / "src/auth")).splitlines()
    assert out[1:] == ["src/auth/auth.py:3-6 Session", "  3: class Session:"]
    assert "outside the library" in output(capsys, project, "grep", "x", str(project.parent))
    assert output(capsys, project, "grep", "zz(").startswith("No code line matches")


def test_grep_limits_results(project, capsys):
    many = project / "src/many/many.py"
    many.parent.mkdir()
    many.write_text("".join(f"x_{i} = 1\n" for i in range(lb.GREP_LIMIT + 5)), encoding="utf-8")
    init(project)
    out = output(capsys, project, "grep", "^x_", str(project / "src/many")).splitlines()
    assert sum(1 for line in out if line.startswith("  ")) == lb.GREP_LIMIT
    assert out[-1] == "... 5 more matches in 1 file(s); narrow the pattern or pass a path"


def test_lookups_count_lines_like_editors(project, capsys):
    (project / "src/ff.py").write_text("def a():\n    pass\n\f\ndef b():\n    return 'needle'\n",
                                       encoding="utf-8")
    init(project)
    out = output(capsys, project, "grep", "needle").splitlines()
    assert out[1:] == ["src/ff.py:4-5 b", "  5: return 'needle'"]
    out = output(capsys, project, "find", "^b$").splitlines()
    assert out[2] == "     4\tdef b():"


def test_find_shows_nested_code_cut_from_its_container(project, capsys):
    big = project / "src/big/big.py"
    big.parent.mkdir()
    body = "".join(f"    x{i} = {i}\n" for i in range(lb.FIND_CODE_LINES + 5))
    big.write_text("class Widget:\n" + body + "    def target(self):\n        pass\n",
                   encoding="utf-8")
    init(project)
    out = output(capsys, project, "find", "Widget").splitlines()
    assert out[-1].endswith("\t        pass")


def test_outline_of_unparsable_uncataloged_file(project, capsys):
    (project / ".gitignore").write_text("vendor/\n", encoding="utf-8")
    bad = project / "vendor/bad.py"
    bad.parent.mkdir()
    bad.write_text("def x(:\n", encoding="utf-8")
    init(project)
    out = output(capsys, project, "outline", str(bad))
    assert "no definitions found" in out


def test_stop_hook_in_library_below_git_root(tmp_path):
    lib_root = tmp_path / "app"
    (lib_root / "src").mkdir(parents=True)
    (lib_root / "src/a.py").write_text("def a(): pass\n", encoding="utf-8")
    git(tmp_path, "init", "-q")
    init(lib_root)
    git(tmp_path, "add", "-A")
    git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x")
    (lib_root / "src/newmod").mkdir()
    (lib_root / "src/newmod/n.py").write_text("def n(): pass\n", encoding="utf-8")
    out = json.loads(hook("stop", {"cwd": str(lib_root)}))
    assert out.get("decision") == "block"
    assert (lib_root / "src/newmod" / lb.DOC_NAME).is_file()


def test_hand_written_agents_md_is_not_migrated(project):
    text = "# My agent instructions\n\n### Subfolders\nsee ## What this folder is for\n"
    (project / "AGENTS.md").write_text(text, encoding="utf-8")
    run(project, "init")
    hook("stop", {"cwd": str(project)})
    assert (project / "AGENTS.md").read_text(encoding="utf-8") == text


def test_find_root_heading_and_long_role(project, capsys):
    (project / "setup.py").write_text("def setup(): pass\n", encoding="utf-8")
    init(project)
    set_role(project, ".", "word " * 60)
    out = output(capsys, project, "find", "^setup$").splitlines()
    assert out[0].startswith("[./] word word") and out[0].endswith("...")
    assert len(out[0]) == len("[./] ") + lb.ROLE_PREVIEW_CHARS
    assert out[1] == "setup.py:1-1 setup"


def test_find_limits_results(project, capsys):
    many = project / "src/many/many.py"
    many.parent.mkdir()
    many.write_text("".join(f"def fn_{i:02d}(): pass\n" for i in range(lb.FIND_LIMIT + 10)),
                    encoding="utf-8")
    init(project)
    out = output(capsys, project, "find", "fn_").splitlines()
    assert sum(1 for line in out if line.startswith("src/many/many.py:")) == lb.FIND_LIMIT
    assert out[-1] == "... 10 more matches; narrow the pattern or pass a path"


def test_find_invalid_regex_is_literal(project, capsys):
    init(project)
    out = output(capsys, project, "find", "describe('x")
    assert "src/api/svc.ts:5-5 describe('x')" in out


def test_find_no_match_points_to_grep(project, capsys):
    init(project)
    out = output(capsys, project, "find", "zzz_nothing")
    assert "No definitions match 'zzz_nothing'" in out and "Grep" in out
    assert ".py" in out and ".md" not in out


def test_find_path_limits_scope(project, capsys):
    init(project)
    out = output(capsys, project, "find", ".", str(project / "native")).splitlines()
    assert out[0] == "[native/]"
    assert all(line.startswith(("native/", "[native/]")) for line in out)
    out = output(capsys, project, "find", ".", str(project / "native/lib.rs")).splitlines()
    assert out == ["[native/]", "native/lib.rs:1-1 P", "native/lib.rs:2-4 P",
                   "native/lib.rs:3-3 P.new", "native/lib.rs:5-5 main"]
    out = output(capsys, project, "find", "^Session$", str(project / "native"))
    assert "No definitions match" in out


def test_find_and_outline_reject_paths_outside_the_library(project, tmp_path_factory, capsys):
    init(project)
    outside = tmp_path_factory.mktemp("outside")
    (outside / "x.py").write_text("def x(): pass\n", encoding="utf-8")
    assert "outside the library" in output(capsys, project, "find", "x", str(outside))
    assert "outside the library" in output(capsys, project, "outline", str(outside / "x.py"))


# ---------------------------------------------------------------- outline


def test_outline_file(project, capsys):
    init(project)
    set_role(project, "native", "Native code.")
    out = output(capsys, project, "outline", str(project / "native/lib.rs")).splitlines()
    assert out == ["[native/] Native code.", "native/lib.rs",
                   "  1-1 P", "  2-4 P", "  3-3 P.new", "  5-5 main"]


def test_outline_folder(project, capsys):
    many = project / "native/many.py"
    many.write_text("".join(f"def f{i}(): pass\n" for i in range(lb.OUTLINE_NAMES_PER_FILE + 5)),
                    encoding="utf-8")
    (project / "native/empty.py").write_text("x = 1\n", encoding="utf-8")
    init(project)
    out = output(capsys, project, "outline", str(project / "native")).splitlines()
    assert out[:5] == ["[native/]", "J.java: J, J.J, J.run", "K.cs: K, K.M",
                       "empty.py: -", "lib.cpp: C, C::m, make"]
    assert out[5] == "lib.rs: P, P, P.new, main"
    assert out[6].startswith("many.py: f0, f1, ") and out[6].endswith(", f24, +5 more")

    out = output(capsys, project, "outline", str(project / "src")).splitlines()
    assert out == ["[src/]", "(no code files directly in this folder; see its subfolders)"]
    out = output(capsys, project, "outline", str(project / "missing"))
    assert "no such file or folder" in out


def test_outline_reads_markdown_and_other_files_directly(project, capsys):
    init(project)
    guide = project / "src/guide.md"
    guide.write_text("# Title\n\nx\n\n## Section\n\ny\n", encoding="utf-8")
    out = output(capsys, project, "outline", str(guide)).splitlines()
    assert out == ["[src/]", "src/guide.md", "  1-7 # Title", "  5-7 ## Section"]
    out = output(capsys, project, "outline", str(project / "assets/logo.txt")).splitlines()
    assert out[1] == "assets/logo.txt" and "no definitions found" in out[2]


# ---------------------------------------------------------------- hooks


def test_hooks_json_registers_only_session_start_and_stop():
    hooks = json.loads((REPO_ROOT / "hooks/hooks.json").read_text(encoding="utf-8"))["hooks"]
    assert set(hooks) == {"SessionStart", "Stop"}
    for key, event in (("SessionStart", "session-start"), ("Stop", "stop")):
        command = hooks[key][0]["hooks"][0]["command"]
        script = '"${CLAUDE_PLUGIN_ROOT}/scripts/librarian.py"'
        assert command == f"python3 {script} hook {event} || python {script} hook {event}"


def test_hook_post_edit_does_nothing(project):
    init(project)
    before = {p: p.read_text(encoding="utf-8") for p in project.rglob("CLAUDE.md")}
    src = project / "src/auth/auth.py"
    src.write_text("\n\n" + src.read_text(encoding="utf-8"), encoding="utf-8")
    out = hook("post-edit", {"cwd": str(project), "tool_name": "Edit",
                             "tool_input": {"file_path": str(src)}})
    assert out == ""
    assert {p: p.read_text(encoding="utf-8") for p in project.rglob("CLAUDE.md")} == before
    assert not (project / ".librarian/catalog.json").exists()


def test_hook_ignores_unmanaged_project(tmp_path, refresh_calls):
    (tmp_path / "a.py").write_text("def f(): pass\n", encoding="utf-8")
    assert hook("post-edit", {"cwd": str(tmp_path)}) == ""
    assert hook("session-start", {"cwd": str(tmp_path)}) == ""
    assert json.loads(hook("stop", {"cwd": str(tmp_path)})) == {}
    assert not (tmp_path / "CLAUDE.md").exists()
    assert refresh_calls == []


@pytest.mark.parametrize("on_path", ["same", "other", None],
                         ids=["python-on-path", "other-python-on-path", "full-path"])
def test_session_start_gives_lookup_instructions_and_refreshes_catalog(
        project, refresh_calls, monkeypatch, on_path):
    init(project)
    with monkeypatch.context() as patch:
        found = {"same": sys.executable, "other": str(project / "python.exe"), None: None}[on_path]
        patch.setattr(lb.shutil, "which", lambda name: found)
        out = json.loads(hook("session-start", {"cwd": str(project / "src")}))
    context = out["hookSpecificOutput"]
    assert context["hookEventName"] == "SessionStart"
    text = context["additionalContext"]
    python = (Path(sys.executable).stem if on_path == "same"
              else f'"{Path(sys.executable).as_posix()}"')
    script = f'{python} "{(REPO_ROOT / "scripts/librarian.py").as_posix()}"'
    assert f"`{script} find <regex> [path]`" in text
    assert f"`{script} outline <file-or-folder>`" in text
    assert "Grep" in text and "maxDocLines" not in text
    assert [lib.root for lib in refresh_calls] == [project.resolve()]


def test_background_refresh_runs_catalog_command(project, monkeypatch):
    run(project, "init")
    seen = {}

    def fake_popen(args, **kwargs):
        seen["args"], seen["kwargs"] = args, kwargs

    monkeypatch.setattr(lb.subprocess, "Popen", fake_popen)
    ORIGINAL_REFRESH(library(project))
    assert seen["args"][0] == sys.executable
    assert seen["args"][-3:] == ["--root", str(project.resolve()), "catalog"]
    assert seen["kwargs"]["stdin"] == subprocess.DEVNULL
    assert seen["kwargs"]["stdout"] == subprocess.DEVNULL

    def failing_popen(args, **kwargs):
        raise OSError("no process")

    monkeypatch.setattr(lb.subprocess, "Popen", failing_popen)
    ORIGINAL_REFRESH(library(project))  # must not raise


def test_session_start_hook_reports_scan_error_without_stopping_session(project, monkeypatch, capsys):
    init(project)

    def fail_scan(_lib):
        raise RuntimeError("scan failed")

    monkeypatch.setattr(lb, "find_overlong_docs", fail_scan)
    assert hook("session-start", {"cwd": str(project)}) == ""
    assert "librarian hook error: RuntimeError('scan failed')" in capsys.readouterr().err


def test_check_and_session_start_warn_on_long_folder_and_rule_documents(project, capsys):
    init(project)
    _fill_all_roles(project)
    set_max_doc_lines(project, 30)
    folder_doc = project / "src/auth/CLAUDE.md"
    long_notes = "\n".join(f"- note {number}" for number in range(31))
    folder_doc.write_text(folder_doc.read_text(encoding="utf-8").replace(
        "## Notes", "## Notes\n\n" + long_notes), encoding="utf-8")
    (project / "AGENTS.md").write_text("# Shared rules\n" + "Follow this rule.\n" * 40,
                                       encoding="utf-8")
    rules_dir = project / ".claude/rules/topic"
    rules_dir.mkdir(parents=True)
    (rules_dir / "long.md").write_text("rule\n" * 31, encoding="utf-8")

    out = output(capsys, project, "check", "--fix")
    assert "[warning] src/auth/CLAUDE.md:" in out and "> maxDocLines 30" in out
    assert "[warning] .claude/rules/topic/long.md: 31 lines" in out
    assert "AGENTS.md" not in out  # the root AGENTS.md is no longer checked

    out = output(capsys, project, "check")  # warnings alone do not fail a read-only check
    assert "[drift]" not in out
    start = json.loads(hook("session-start", {"cwd": str(project / "src/auth")}))
    context = start["hookSpecificOutput"]["additionalContext"]
    assert "src/auth/CLAUDE.md (" in context
    assert ".claude/rules/topic/long.md (31 lines)" in context
    assert "subfolder table rows excluded" in context
    assert "AGENTS.md (" not in context

    set_max_doc_lines(project, 200)
    context = json.loads(hook("session-start", {"cwd": str(project)}))[
        "hookSpecificOutput"]["additionalContext"]
    assert "maxDocLines" not in context and " find <regex>" in context


def test_overlong_count_excludes_subfolder_rows(project):
    for number in range(40):
        p = project / f"pkg{number:02d}/m.py"
        p.parent.mkdir()
        p.write_text("def m(): pass\n", encoding="utf-8")
    init(project)
    set_max_doc_lines(project, 30)
    text = root_doc(project)
    table_rows = sum(1 for line in text.splitlines() if line.startswith("|"))
    assert table_rows == 43 + 2  # 43 folders plus the header and separator rows
    assert lb.prose_line_count(text) == len(text.splitlines()) - table_rows
    assert len(text.splitlines()) > 30
    lib = library(project)
    assert "CLAUDE.md" not in dict(lb.find_overlong_docs(lib))

    notes = "\n".join(f"- note {number}" for number in range(31))
    (project / "CLAUDE.md").write_text(text.replace("## Notes", "## Notes\n\n" + notes),
                                       encoding="utf-8")
    assert "CLAUDE.md" in dict(lb.find_overlong_docs(lib))


def test_hook_stop_after_folder_changes(project):
    init(project)
    _fill_all_roles(project)
    commit_all(project)
    assert json.loads(hook("stop", {"cwd": str(project)})) == {}

    # a deleted folder and a brand-new folder (created without any document)
    shutil.rmtree(project / "src/api")
    (project / "src/billing").mkdir()
    (project / "src/billing/pay.py").write_text("def pay(): pass\n", encoding="utf-8")
    out = json.loads(hook("stop", {"cwd": str(project), "stop_hook_active": False}))
    assert out["decision"] == "block" and "src/billing" in out["reason"]
    table = (project / "src/CLAUDE.md").read_text(encoding="utf-8")
    assert "| api/ |" not in table and f"| billing/ | {EN['placeholder']} |" in table

    again = json.loads(hook("stop", {"cwd": str(project), "stop_hook_active": True}))
    assert "decision" not in again


def test_hook_stop_lists_at_most_ten_pending_folders_deepest_first(project):
    init(project)
    _fill_all_roles(project)
    commit_all(project)
    deep = project / "deep/x/y/z.py"
    deep.parent.mkdir(parents=True)
    deep.write_text("def z(): pass\n", encoding="utf-8")
    for number in range(11):
        p = project / f"flat{number:02d}/m.py"
        p.parent.mkdir()
        p.write_text("def m(): pass\n", encoding="utf-8")

    reason = json.loads(hook("stop", {"cwd": str(project)}))["reason"]

    assert lb.PENDING_LIST_LIMIT == 10
    assert ": deep/x/y, deep/x, deep, flat00, flat01, flat02, flat03, flat04, flat05, flat06, and 5 more (run /rebuild-library" in reason
    assert "flat07" not in reason


def test_hook_stop_creates_documents_for_new_nested_folders(project):
    init(project)
    _fill_all_roles(project)
    commit_all(project)
    new = project / "x/y z/한/q.py"
    new.parent.mkdir(parents=True)
    new.write_text("def q(): pass\n", encoding="utf-8")
    hook("stop", {"cwd": str(project)})
    assert "| x/ |" in root_doc(project)
    assert "| y z/ |" in (project / "x/CLAUDE.md").read_text(encoding="utf-8")
    assert (project / "x/y z/한/CLAUDE.md").is_file()


def test_hook_stop_warns_on_deep_folders_only(project):
    init(project)
    cfg = read_config(project)
    cfg["maxDepth"] = 1
    cfg["maxEntries"] = 1  # a legacy key: many index rows no longer cause a warning
    write_config(project, cfg)
    out = json.loads(hook("stop", {"cwd": str(project), "stop_hook_active": True}))
    assert "src/auth: folder depth 2 > 1" in out["systemMessage"]
    assert "index rows" not in out["systemMessage"]
    assert "native" not in out["systemMessage"]


def test_stop_hook_blocks_only_for_new_folders_and_notes_older_empty_roles(project):
    init(project)  # documents exist with empty roles before this turn
    commit_all(project)
    (project / "src/auth/auth.py").write_text("x = 1\n", encoding="utf-8")
    out = json.loads(hook("stop", {"cwd": str(project)}))
    assert "decision" not in out
    assert "still have empty roles; run /rebuild-library" in out["systemMessage"]

    (project / "src/auth/fresh").mkdir()
    (project / "src/auth/fresh/new.py").write_text("def f(): pass\n", encoding="utf-8")
    out = json.loads(hook("stop", {"cwd": str(project)}))
    assert out["decision"] == "block"
    listed = out["reason"].split(" of: ")[1].split(". Write")[0].split(", ")
    assert listed == ["src/auth/fresh", "src/auth"]  # the new folder and its new table row


def test_stop_hook_active_string_false(project):
    run(project, "init")  # no scaffold: the stop hook creates the documents
    out = json.loads(hook("stop", {"cwd": str(project), "stop_hook_active": "false"}))
    assert out.get("decision") == "block"


def test_stop_hook_reports_error_and_still_emits_json(project, monkeypatch, capsys):
    init(project)

    def fail(*_args, **_kwargs):
        raise RuntimeError("sync failed")

    monkeypatch.setattr(lb, "sync_dirs", fail)
    assert json.loads(hook("stop", {"cwd": str(project)})) == {}
    assert "librarian hook error: RuntimeError('sync failed')" in capsys.readouterr().err


def test_renamed_folder_keeps_role_cell(project):
    init(project)
    _fill_all_roles(project)
    commit_all(project)
    doc = project / "src/CLAUDE.md"
    doc.write_text(doc.read_text(encoding="utf-8").replace("| auth/ | role |", "| auth/ | Login |"),
                   encoding="utf-8")
    shutil.move(str(project / "src/auth"), str(project / "src/identity"))
    out = json.loads(hook("stop", {"cwd": str(project)}))
    assert "| identity/ | Login |" in doc.read_text(encoding="utf-8")
    assert "decision" not in out


def test_stop_command_from_hooks_json_removes_legacy_root_note(project):
    init(project)
    write_root_with_note(project, LEGACY_EN_NOTE)
    payload = {"cwd": str(project), "hook_event_name": "Stop", "stop_hook_active": True}

    res = run_hooks_json_command("Stop", project, payload)

    assert res.returncode == 0, res.stderr.decode("utf-8", "replace")
    assert isinstance(json.loads(res.stdout.decode("utf-8").strip().splitlines()[-1]), dict)
    assert LEGACY_EN_NOTE not in root_doc(project) and "Our own intro." in root_doc(project)


def test_session_start_command_from_hooks_json_builds_catalog(project):
    init(project)
    payload = {"cwd": str(project), "hook_event_name": "SessionStart"}

    res = run_hooks_json_command("SessionStart", project, payload)

    assert res.returncode == 0, res.stderr.decode("utf-8", "replace")
    out = json.loads(res.stdout.decode("utf-8").strip().splitlines()[-1])
    assert " find <regex> [path]" in out["hookSpecificOutput"]["additionalContext"]
    cache = project / ".librarian/catalog.json"
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:  # the refresh runs in a detached process
        try:
            if "web/main.go" in json.loads(cache.read_text(encoding="utf-8"))["files"]:
                break
        except (OSError, ValueError):
            pass
        time.sleep(0.2)
    else:
        pytest.fail("the background catalog refresh did not write the catalog")


# ---------------------------------------------------------------- library language


def test_default_language_is_english(project):
    init(project)
    assert read_config(project)["language"] == "en"
    assert EN["role"] in (project / "src/auth/CLAUDE.md").read_text(encoding="utf-8")
    assert "| Folder | Role |" in (project / "src/CLAUDE.md").read_text(encoding="utf-8")


def test_korean_library(project, capsys):
    init(project, language="ko")
    text = (project / "src/auth/CLAUDE.md").read_text(encoding="utf-8")
    assert text.startswith("# 상위 문서: ../CLAUDE.md")
    assert KO["role"] in text and KO["placeholder"] in text
    assert "| 폴더 | 역할 |" in (project / "src/CLAUDE.md").read_text(encoding="utf-8")
    assert root_doc(project).startswith(f"# {project.name}\n\n{KO['role']}\n")
    assert "src/auth" in output(capsys, project, "pending").splitlines()


def test_language_switch_keeps_roles(project):
    init(project, language="ko")
    doc = project / "src/CLAUDE.md"
    doc.write_text(doc.read_text(encoding="utf-8")
                   .replace(KO["placeholder"], "소스 코드", 1)
                   .replace(f"| auth/ | {KO['placeholder']} |", "| auth/ | 인증 |"), encoding="utf-8")
    run(project, "init", "--language", "en")
    run(project, "index", "--all")
    text = doc.read_text(encoding="utf-8")
    assert text.startswith("# Parent: ../CLAUDE.md")
    assert EN["role"] in text and "소스 코드" in text
    assert "| auth/ | 인증 |" in text and f"| api/ | {EN['placeholder']} |" in text
    assert not any(v in text for v in (KO["role"], KO["subdirs"], KO["placeholder"]))


def test_unknown_language_uses_english_headings(project):
    run(project, "init", "--language", "ja")
    out = json.loads(hook("stop", {"cwd": str(project)}))
    assert EN["role"] in (project / "src/CLAUDE.md").read_text(encoding="utf-8")
    assert out["decision"] == "block" and "(ja)" in out["reason"]


# ---------------------------------------------------------------- document parsing


def test_fenced_or_unmatched_marker_keeps_human_text(project):
    init(project)
    doc = project / "src/auth/CLAUDE.md"
    fenced = ("Example of the generated block:\n\n```markdown\n" + lb.INDEX_START
              + "\n| File | Function | Line |\n```\n")
    doc.write_text(doc.read_text(encoding="utf-8").replace(EN["placeholder"], fenced),
                   encoding="utf-8")
    run(project, "index", str(project / "src/auth"))
    out = doc.read_text(encoding="utf-8")
    assert fenced in out

    # a start marker without an end marker is treated as text, not as the index
    doc.write_text(out + "\n" + lb.INDEX_START + "\n\n## Extra\n\nkeep me\n", encoding="utf-8")
    run(project, "index", str(project / "src/auth"))
    out = doc.read_text(encoding="utf-8")
    assert "keep me" in out and fenced in out
    assert out.count(lb.INDEX_START) == 1  # only the fenced example remains


def test_orphan_markers_never_lose_text(project):
    init(project)
    doc = project / "src/auth/CLAUDE.md"
    text = (doc.read_text(encoding="utf-8") + "\n" + lb.INDEX_END + "\n\n" + lb.INDEX_START
            + "\n\n## Extra\n\nImportant human notes\n")
    doc.write_text(text, encoding="utf-8")
    run(project, "index", str(project / "src/auth"))
    first = doc.read_text(encoding="utf-8")
    for _ in range(2):
        run(project, "index", str(project / "src/auth"))
    out = doc.read_text(encoding="utf-8")
    assert out == first
    assert "Important human notes" in out
    assert lb.INDEX_START not in out and lb.INDEX_END not in out


def test_heading_inside_code_fence_is_not_a_section(project):
    init(project)
    doc = project / "src/CLAUDE.md"
    role = "Build notes:\n\n```bash\n# install deps first\nnpm ci\n```"
    doc.write_text(doc.read_text(encoding="utf-8").replace(EN["placeholder"], role, 1), encoding="utf-8")
    run(project, "index", str(project / "src"))
    out = doc.read_text(encoding="utf-8")
    assert role in out
    assert out.index(role) < out.index(EN["subdirs"])


def test_text_under_subfolder_table_is_kept(project):
    init(project)
    doc = project / "src/CLAUDE.md"
    text = doc.read_text(encoding="utf-8")
    table_end = text.index("| auth/ |")
    line_end = text.index("\n", table_end)
    text = text[:line_end + 1] + "\nNote: api/ is being split.\n" + text[line_end + 1:]
    doc.write_text(text, encoding="utf-8")
    run(project, "index", str(project / "src"))
    assert "Note: api/ is being split." in doc.read_text(encoding="utf-8")


def test_unclosed_fence_is_idempotent(project):
    init(project)
    doc = project / "src/CLAUDE.md"
    doc.write_text(f"# Parent: ../CLAUDE.md\n\n{EN['role']}\n\nRole:\n\n```\ncode\n", encoding="utf-8")
    run(project, "index", str(project / "src"))
    first = doc.read_text(encoding="utf-8")
    run(project, "index", str(project / "src"))
    run(project, "index", str(project / "src"))
    assert doc.read_text(encoding="utf-8") == first
    assert first.count(EN["subdirs"]) == 1


# ---------------------------------------------------------------- config


def read_config(project):
    return json.loads((project / ".librarian/config.json").read_text(encoding="utf-8"))


def write_config(project, cfg):
    (project / ".librarian/config.json").write_text(json.dumps(cfg), encoding="utf-8")


def set_max_doc_lines(project, limit):
    cfg = read_config(project)
    cfg["maxDocLines"] = limit
    write_config(project, cfg)


def test_config_with_bom(project, capsys):
    init(project)
    cfg = project / ".librarian/config.json"
    cfg.write_bytes(b"\xef\xbb\xbf" + cfg.read_bytes())
    run(project, "index", "--all")
    src = project / "src/auth/auth.py"
    src.write_text("\n" + src.read_text(encoding="utf-8"), encoding="utf-8")
    assert "src/auth/auth.py:4-7 Session" in output(capsys, project, "find", "^Session$")
    assert "/rebuild-library" in json.loads(hook("stop", {"cwd": str(project)}))["systemMessage"]


def test_invalid_config_numbers_fall_back(project):
    init(project)
    cfg = read_config(project)
    cfg["maxDepth"] = "deep"
    cfg["maxDocLines"] = "many"
    write_config(project, cfg)
    run(project, "index", "--all")  # must not raise
    run(project, "update")
    assert read_config(project)["maxDocLines"] == lb.DEFAULT_CONFIG["maxDocLines"] == 60
    assert read_config(project)["maxDepth"] == lb.DEFAULT_CONFIG["maxDepth"]


def test_negative_limits_fall_back(project):
    init(project)
    cfg = read_config(project)
    cfg["maxDepth"] = -5
    cfg["maxDocLines"] = 0
    write_config(project, cfg)
    run(project, "update")
    assert read_config(project)["maxDepth"] == lb.DEFAULT_CONFIG["maxDepth"]
    assert read_config(project)["maxDocLines"] == lb.DEFAULT_CONFIG["maxDocLines"]


# keys written by versions that had the index-row warning, the session-start rule injection,
# the rules skill links, or the AGENTS.md document modes
@pytest.mark.parametrize("key,value", [("maxEntries", 60), ("injectRules", False),
                                       ("targets", ["claude"]), ("docName", "AGENTS.md")])
@pytest.mark.parametrize("command", ["update", "init"])
def test_rewriting_config_drops_removed_key_and_keeps_others(project, key, value, command):
    init(project)
    write_config(project, {"language": "en", "maxDepth": 4, key: value})

    run(project, "index", "--all")  # must not raise
    run(project, command)

    cfg = read_config(project)
    assert key not in cfg
    assert cfg["maxDepth"] == 4


def test_init_rejects_removed_doc_option(project):
    with pytest.raises(SystemExit):
        run(project, "init", "--doc", "AGENTS.md")


# ---------------------------------------------------------------- update


def test_update_fills_missing_keys_and_records_version(project):
    init(project)
    write_config(project, {"language": "en", "docName": "CLAUDE.md"})
    run(project, "update")
    cfg = read_config(project)
    assert cfg["libraryVersion"] == plugin_version_from_manifest()
    assert cfg["maxDepth"] == lb.DEFAULT_CONFIG["maxDepth"]
    assert cfg["maxDocLines"] == 60
    assert (project / ".librarian/catalog.json").is_file()


def test_update_keeps_korean_headings_and_roles(project):
    init(project, language="ko")
    doc = project / "src/CLAUDE.md"
    doc.write_text(doc.read_text(encoding="utf-8").replace(KO["placeholder"], "소스 코드", 1),
                   encoding="utf-8")
    run(project, "update")
    text = doc.read_text(encoding="utf-8")
    assert text.startswith("# 상위 문서: ../CLAUDE.md")
    assert KO["role"] in text and "소스 코드" in text


def test_update_moves_legacy_max_doc_lines_default(project, capsys):
    init(project)
    set_max_doc_lines(project, lb.LEGACY_DEFAULT_MAX_DOC_LINES)
    out = output(capsys, project, "update")
    assert read_config(project)["maxDocLines"] == 60
    assert "[updated] maxDocLines 200 -> 60" in out

    set_max_doc_lines(project, 150)  # a value the user chose stays
    out = output(capsys, project, "update")
    assert read_config(project)["maxDocLines"] == 150
    assert "maxDocLines" not in out


def test_update_warns_about_documents_in_folders_without_code(project, capsys):
    init(project)
    legacy = project / "assets/CLAUDE.md"
    legacy.write_text(f"# Parent: ../CLAUDE.md\n\n{EN['role']}\n\nImages.\n", encoding="utf-8")
    (project / "docs").mkdir()
    human = project / "docs/CLAUDE.md"
    human.write_text("# Writing guide\n", encoding="utf-8")

    out = output(capsys, project, "update")

    assert "[warning] assets/CLAUDE.md: this folder holds no code" in out
    assert "docs/CLAUDE.md" not in out
    assert legacy.is_file() and human.is_file()


# ---------------------------------------------------------------- stop hook version notice


@pytest.mark.parametrize("claude_manifest,expected_version", [
    (b'{"version":"0.6.1"}', "0.6.1"),
    (None, None),
    (b'{', None),
    (b'\xff', None),
    (b'[]', None),
], ids=["valid", "absent", "malformed", "non-utf8", "non-object"])
def test_claude_manifest_stamps_cli_versions_and_preserves_hook_notices(
        project, tmp_path, claude_manifest, expected_version):
    plugin_root = tmp_path / "native plugin"
    shutil.copytree(REPO_ROOT / "scripts", plugin_root / "scripts",
                    ignore=shutil.ignore_patterns("__pycache__"))
    if claude_manifest is not None:
        manifest = plugin_root / ".claude-plugin/plugin.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_bytes(claude_manifest)
    # manifests other than .claude-plugin/plugin.json must not affect the version lookup
    (plugin_root / "plugin.json").write_text('{"version":"99.0.0"}', encoding="utf-8")
    (plugin_root / ".codex-plugin").mkdir()
    (plugin_root / ".codex-plugin/plugin.json").write_text('{"version":"98.0.0"}',
                                                           encoding="utf-8")
    script = plugin_root / "scripts/librarian.py"

    def cli(*argv, payload=None):
        result = subprocess.run(
            [sys.executable, str(script), "--root", str(project), *argv], cwd=project,
            env={**os.environ, "PYTHONUTF8": "1"},
            input=json.dumps(payload) if payload is not None else None,
            text=True, encoding="utf-8", capture_output=True, timeout=60)
        assert result.returncode == 0, result.stderr
        assert result.stderr == ""
        return result.stdout

    cli("init")
    assert read_config(project)["libraryVersion"] == expected_version
    cfg = read_config(project)
    cfg["libraryVersion"] = "0.0.1"
    write_config(project, cfg)

    stop = json.loads(cli("hook", "stop", payload={"cwd": str(project)}))
    assert stop["decision"] == "block"
    assert ("/update-library" in stop.get("systemMessage", "")) == (expected_version is not None)

    cli("update")
    assert read_config(project)["libraryVersion"] == expected_version
    stop = json.loads(cli("hook", "stop", payload={"cwd": str(project), "stop_hook_active": True}))
    assert "/update-library" not in stop.get("systemMessage", "")


# These tests pass stop_hook_active: True only to suppress the empty-role block, so the
# output holds nothing but the version notice.


def stop_with_library_version(project, version):
    cfg = read_config(project)
    if version is None:
        del cfg["libraryVersion"]
    else:
        cfg["libraryVersion"] = version
    write_config(project, cfg)
    return json.loads(hook("stop", {"cwd": str(project), "stop_hook_active": True}))


def test_stop_hook_asks_for_update_when_library_is_older(project):
    init(project)
    out = stop_with_library_version(project, "0.0.1")
    assert "/update-library" in out["systemMessage"]


def test_stop_hook_asks_for_update_when_library_has_no_version(project):
    init(project)
    out = stop_with_library_version(project, None)
    assert "/update-library" in out["systemMessage"]


def test_stop_hook_asks_to_update_plugin_when_library_is_newer(project):
    init(project)
    out = stop_with_library_version(project, "99.0.0")
    assert "update the plugin" in out["systemMessage"]
    assert "/update-library" not in out["systemMessage"]


def test_stop_hook_without_plugin_version_still_blocks_on_empty_roles(project, monkeypatch):
    run(project, "init")
    monkeypatch.setattr(lb, "plugin_version", lambda: None)
    out = json.loads(hook("stop", {"cwd": str(project)}))
    assert out["decision"] == "block"
    assert "systemMessage" not in out


def test_stop_hook_has_no_update_notice_when_versions_match(project):
    init(project)
    _fill_all_roles(project)
    out = stop_with_library_version(project, plugin_version_from_manifest())
    assert "systemMessage" not in out


# ---------------------------------------------------------------- legacy rules skill


# the exact lines older versions wrote, kept literal because they test real old documents
LEGACY_EN_NOTE = "This repository follows the rules of the `librarian-guide` skill."
LEGACY_KO_NOTE = "이 저장소는 `librarian-guide` 스킬의 규칙을 따릅니다."
LEGACY_GITIGNORE = ("node_modules/\n"
                    "\n"
                    "# agent-librarian: skill links (restored automatically by check)\n"
                    "/.claude/skills/librarian-guide\n"
                    "/.agents/skills/librarian-guide\n"
                    "/.codex/skills/librarian-guide\n")


def write_root_with_note(project, note):
    body = root_doc(project).split("\n", 2)[2]  # everything after "# <name>" and a blank line
    (project / "CLAUDE.md").write_text(
        f"# {project.name}\n\n{note}\n\nOur own intro.\n\n{body}", encoding="utf-8")


@pytest.mark.parametrize("language,note", [("en", LEGACY_EN_NOTE), ("ko", LEGACY_KO_NOTE)])
def test_sync_removes_legacy_root_note_and_keeps_user_text(project, language, note):
    init(project, language=language)
    write_root_with_note(project, note)

    run(project, "index", "--all")

    out = root_doc(project)
    role_heading = lb.DOC_STRINGS[language]["role"]
    assert out.startswith(f"# {project.name}\n\nOur own intro.\n\n{role_heading}\n")
    run(project, "index", "--all")
    assert root_doc(project) == out  # idempotent


def test_legacy_root_note_inside_code_fence_is_kept(project):
    init(project)
    fenced = f"```\n{LEGACY_EN_NOTE}\n```"
    write_root_with_note(project, fenced)
    run(project, "index", "--all")
    assert fenced in root_doc(project)


def make_legacy_skill_install(project):
    """What 0.4 installed: a source folder, a junction/symlink in .claude and copies (the
    fallback when linking failed) in .agents and .codex, plus the .gitignore lines."""
    source = project / ".librarian/skills/librarian-guide"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_bytes(b"---\nname: librarian-guide\n---\n# rules\n")
    link = project / ".claude/skills/librarian-guide"
    link.parent.mkdir(parents=True)
    if os.name == "nt":
        import _winapi
        _winapi.CreateJunction(str(source), str(link))
    else:
        os.symlink(source, link, target_is_directory=True)
    for agent in (".agents", ".codex"):
        copy = project / agent / "skills/librarian-guide"
        copy.mkdir(parents=True)
        # a CRLF checkout of the same text still counts as an unedited copy
        (copy / "SKILL.md").write_bytes(b"---\r\nname: librarian-guide\r\n---\r\n# rules\r\n")
    (project / ".gitignore").write_text(LEGACY_GITIGNORE, encoding="utf-8")
    return source


@pytest.mark.parametrize("command", ["update", "init"])
def test_legacy_skill_links_and_gitignore_lines_are_removed(project, capsys, command):
    init(project)
    source = make_legacy_skill_install(project)

    out = output(capsys, project, command)

    for agent in (".claude", ".agents", ".codex"):
        assert not os.path.lexists(project / agent / "skills/librarian-guide"), agent
        assert f"[updated] {agent}/skills/librarian-guide (removed)" in out
    # empty folders go, but .claude stays because Claude Code keeps settings there
    assert not os.path.lexists(project / ".agents") and not os.path.lexists(project / ".codex")
    assert not os.path.lexists(project / ".claude/skills") and (project / ".claude").is_dir()
    assert (project / ".gitignore").read_text(encoding="utf-8") == "node_modules/\n"
    # the source may hold rules the user wrote, so it stays and a warning names it
    assert (source / "SKILL.md").is_file()
    assert "[warning] .librarian/skills/librarian-guide is no longer used" in out


def test_legacy_skill_cleanup_keeps_other_skills_and_edited_copies(project, capsys):
    init(project)
    make_legacy_skill_install(project)
    (project / ".claude/skills/other").mkdir()  # a skill that is not ours
    edited = project / ".agents/skills/librarian-guide/SKILL.md"
    edited.write_bytes(edited.read_bytes() + b"My own rule.\n")

    out = output(capsys, project, "update")

    assert (project / ".claude/skills/other").is_dir()
    assert edited.is_file()
    assert "[warning] .agents/skills/librarian-guide differs from" in out
    assert not os.path.lexists(project / ".codex/skills/librarian-guide")


def test_gitignore_cleanup_keeps_bom_and_crlf(project):
    init(project)
    legacy = "﻿" + LEGACY_GITIGNORE.replace("\n", "\r\n")
    (project / ".gitignore").write_bytes(legacy.encode("utf-8"))
    run(project, "update")
    assert (project / ".gitignore").read_bytes() == b"\xef\xbb\xbfnode_modules/\r\n"


def test_update_deletes_gitignore_that_held_only_skill_lines(project):
    init(project)
    (project / ".gitignore").write_text("\n" + LEGACY_GITIGNORE.split("\n", 1)[1], encoding="utf-8")
    run(project, "update")
    assert not (project / ".gitignore").exists()


def test_update_without_legacy_skill_prints_no_skill_lines(project, capsys):
    init(project)
    out = output(capsys, project, "update")
    assert "librarian-guide" not in out and ".gitignore" not in out
