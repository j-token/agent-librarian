import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import librarian as lb  # noqa: E402

EN = lb.DOC_STRINGS["en"]
KO = lb.DOC_STRINGS["ko"]

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


def init(root, doc="CLAUDE.md", language=None):
    extra = ["--language", language] if language else []
    run(root, "init", "--doc", doc, *extra)
    run(root, "scaffold")


def root_doc(project):
    return (project / "CLAUDE.md").read_text(encoding="utf-8")


def plugin_version_from_manifest():
    return json.loads((REPO_ROOT / ".codex-plugin/plugin.json").read_text(
        encoding="utf-8"))["version"]


def commit_all(project):
    git(project, "add", "-A")
    git(project, "-c", "user.email=a@b", "-c", "user.name=t", "commit", "-qm", "c")


def index_rows(doc: Path):
    text = doc.read_text(encoding="utf-8")
    block = text[text.index(lb.INDEX_START):text.index(lb.INDEX_END)]
    rows = []
    for line in block.splitlines()[3:]:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        rows.append(tuple(cells))
    return rows


def hook(event, payload):
    stdin, stdout = sys.stdin, sys.stdout
    sys.stdin = io.TextIOWrapper(io.BytesIO(json.dumps(payload).encode("utf-8")), encoding="utf-8")
    sys.stdout = io.StringIO()
    try:
        lb.main(["hook", event])
        return sys.stdout.getvalue()
    finally:
        sys.stdin, sys.stdout = stdin, stdout


# ---------------------------------------------------------------- extraction


@pytest.mark.parametrize("rel,expected", [
    ("src/auth/auth.py", [("Session", 3, 6), ("Session.refresh", 4, 6), ("login", 9, 10)]),
    ("src/api/svc.ts", [("Svc", 1, 3), ("Svc.run", 2, 2), ("handler", 4, 4)]),
    ("web/main.go", [("S", 3, 3), ("S.Do", 5, 5), ("Top", 7, 7)]),
    ("native/lib.cpp", [("C", 2, 2), ("C::m", 3, 3), ("make", 5, 5)]),
    ("native/lib.rs", [("P", 1, 1), ("P", 2, 4), ("P.new", 3, 3), ("main", 5, 5)]),
    ("native/J.java", [("J", 1, 4), ("J.J", 2, 2), ("J.run", 3, 3)]),
    ("native/K.cs", [("K", 2, 4), ("K.M", 3, 3)]),
])
def test_scaffold_indexes_symbols_with_line_ranges(project, rel, expected):
    init(project)
    source = Path(rel)
    doc = project / source.parent / "CLAUDE.md"
    actual = [(symbol, int(start), int(end))
              for file_name, symbol, start, end in index_rows(doc)
              if file_name == source.name]
    assert actual == expected


# ---------------------------------------------------------------- scaffold / index


def test_scaffold_creates_hierarchy(project):
    init(project)
    for d in [".", "src", "src/auth", "src/api", "web", "native", "assets"]:
        assert (project / d / "CLAUDE.md").is_file(), d
    root = root_doc(project)
    assert root.startswith(f"# {project.name}\n\n{EN['role']}\n")  # no rules or skill pointer
    assert "| src/ |" in root and "| web/ |" in root
    assert lb.INDEX_START not in root  # the root has no code files
    sub = (project / "src/auth/CLAUDE.md").read_text(encoding="utf-8")
    assert sub.startswith("# Parent: ../CLAUDE.md")
    assert index_rows(project / "src/auth/CLAUDE.md") == [
        ("auth.py", "Session", "3", "6"), ("auth.py", "Session.refresh", "4", "6"),
        ("auth.py", "login", "9", "10")]
    assert lb.INDEX_START not in (project / "assets/CLAUDE.md").read_text(encoding="utf-8")


def test_scaffold_does_not_overwrite(project):
    (project / "src").mkdir(exist_ok=True)
    (project / "src/CLAUDE.md").write_text("user document\n", encoding="utf-8")
    init(project)
    assert (project / "src/CLAUDE.md").read_text(encoding="utf-8") == "user document\n"


def test_index_preserves_human_text(project):
    init(project)
    doc = project / "src/auth/CLAUDE.md"
    text = doc.read_text(encoding="utf-8").replace(EN["placeholder"], "Auth module.\n\n- detail")
    text += "\n## Notes\n\nsection written by a human\n"
    doc.write_text(text, encoding="utf-8")
    src = project / "src/auth/auth.py"
    src.write_text("# header\n\n" + src.read_text(encoding="utf-8"), encoding="utf-8")
    run(project, "index", str(project / "src/auth"))
    out = doc.read_text(encoding="utf-8")
    assert "Auth module.\n\n- detail" in out and "section written by a human" in out
    assert ("auth.py", "Session", "5", "8") in index_rows(doc)
    run(project, "index", str(project / "src/auth"))
    assert doc.read_text(encoding="utf-8") == out  # idempotent


def test_index_moves_to_index_md_and_returns_inline_when_limit_rises(project):
    init(project)
    doc = project / "src/auth/CLAUDE.md"
    notes = "## Notes\n\nKeep this explanation."
    doc.write_text(doc.read_text(encoding="utf-8").replace("## Notes", notes), encoding="utf-8")
    inline_lines = len(doc.read_text(encoding="utf-8").splitlines())
    set_max_doc_lines(project, inline_lines - 1)

    run(project, "index", str(doc.parent))

    index_file = doc.parent / "index.md"
    assert index_file.read_text(encoding="utf-8").startswith(lb.GENERATED_MARKER + "\n")
    assert "| auth.py | Session | 3 | 6 |" in index_file.read_text(encoding="utf-8")
    assert "[Index](index.md)" in doc.read_text(encoding="utf-8")
    assert notes in doc.read_text(encoding="utf-8")
    run(project, "index", "--all")
    assert "| index.md |" not in index_file.read_text(encoding="utf-8")

    set_max_doc_lines(project, 200)
    run(project, "index", str(doc.parent))

    assert ("auth.py", "Session", "3", "6") in index_rows(doc)
    assert notes in doc.read_text(encoding="utf-8")
    assert not index_file.exists()


def test_large_index_splits_per_file_then_recombines_through_both_tiers(project):
    init(project)
    folder = project / "src/auth"
    for number in range(8):
        (folder / f"extra{number}.py").write_text(f"def extra{number}(): pass\n", encoding="utf-8")
    set_max_doc_lines(project, 10)

    run(project, "index", str(folder))

    index_file = folder / "index.md"
    per_file = folder / "index/extra0.py.md"
    assert index_file.read_text(encoding="utf-8").startswith(lb.GENERATED_MARKER + "\n")
    assert "[extra0.py](index/extra0.py.md)" in index_file.read_text(encoding="utf-8")
    assert "| extra0.py | extra0 | 1 | 1 |" in per_file.read_text(encoding="utf-8")
    run(project, "index", "--all")
    assert not (folder / "index/CLAUDE.md").exists()
    assert "| extra0.py.md |" not in index_file.read_text(encoding="utf-8")

    set_max_doc_lines(project, 16)
    run(project, "index", str(folder))
    assert "| extra0.py | extra0 | 1 | 1 |" in index_file.read_text(encoding="utf-8")
    assert not (folder / "index").exists()

    set_max_doc_lines(project, 200)
    run(project, "index", str(folder))
    assert ("extra0.py", "extra0", "1", "1") in index_rows(folder / "CLAUDE.md")
    assert not index_file.exists()


def test_per_file_index_escapes_link_labels_and_warns_when_final_files_stay_long(project, capsys):
    init(project)
    folder = project / "src/auth"
    (folder / "a]b.py").write_text("def bracket(): pass\n", encoding="utf-8")
    for number in range(6):
        (folder / f"extra{number}.py").write_text(f"def extra{number}(): pass\n", encoding="utf-8")
    set_max_doc_lines(project, 5)

    run(project, "index", str(folder))

    index_file = folder / "index.md"
    links = index_file.read_text(encoding="utf-8")
    assert "- [a\\]b.py](index/a%5Db.py.md)" in links
    assert "| a]b.py | bracket | 1 | 1 |" in (folder / "index/a]b.py.md").read_text(encoding="utf-8")
    warnings = capsys.readouterr().out
    assert "src/auth/index.md: generated index has" in warnings
    assert "src/auth/index/auth.py.md: generated index has" in warnings
    assert "cannot be split further" in warnings


def test_human_index_paths_are_preserved_when_splitting_is_blocked(project, capsys):
    init(project)
    folder = project / "src/auth"
    set_max_doc_lines(project, 10)
    human_index = folder / "index.md"
    human_index.write_text("# Human index\n", encoding="utf-8")

    run(project, "index", str(folder))

    assert human_index.read_text(encoding="utf-8") == "# Human index\n"
    assert ("auth.py", "Session", "3", "6") in index_rows(folder / "CLAUDE.md")
    assert "index.md is human-owned" in capsys.readouterr().out

    human_index.unlink()
    index_dir = folder / "index"
    index_dir.mkdir()
    (index_dir / "keep.txt").write_text("human file\n", encoding="utf-8")
    for number in range(8):
        (folder / f"extra{number}.py").write_text(f"def extra{number}(): pass\n", encoding="utf-8")
    run(project, "index", str(folder))

    assert (index_dir / "keep.txt").read_text(encoding="utf-8") == "human file\n"
    assert not (index_dir / "extra0.py.md").exists()
    assert "| extra0.py | extra0 | 1 | 1 |" in (folder / "index.md").read_text(encoding="utf-8")
    assert "contains human-owned files" in capsys.readouterr().out


def test_parse_failure_preserves_rows_across_split_tiers(project):
    init(project)
    folder = project / "src/auth"
    set_max_doc_lines(project, 14)
    run(project, "index", str(folder))
    assert (folder / "index.md").is_file()

    (folder / "auth.py").write_text("def broken(:\n", encoding="utf-8")
    for number in range(8):
        (folder / f"extra{number}.py").write_text(f"def extra{number}(): pass\n", encoding="utf-8")
    set_max_doc_lines(project, 10)
    run(project, "index", str(folder))
    assert "| auth.py | Session | 3 | 6 |" in (folder / "index/auth.py.md").read_text(encoding="utf-8")

    set_max_doc_lines(project, 200)
    run(project, "index", str(folder))
    assert ("auth.py", "Session", "3", "6") in index_rows(folder / "CLAUDE.md")


def test_check_reports_split_drift_without_writing_files(project, capsys):
    init(project)
    _fill_all_roles(project)
    folder = project / "src/auth"
    original = (folder / "CLAUDE.md").read_text(encoding="utf-8")
    set_max_doc_lines(project, len(original.splitlines()) - 1)

    with pytest.raises(SystemExit) as error:
        run(project, "check")

    assert error.value.code == 1
    assert "[drift] src/auth" in capsys.readouterr().out
    assert (folder / "CLAUDE.md").read_text(encoding="utf-8") == original
    assert not (folder / "index.md").exists()

    run(project, "check", "--fix")
    assert (folder / "index.md").is_file()
    run(project, "check")


def test_cleanup_keeps_generated_index_file_edited_by_human(project):
    init(project)
    folder = project / "src/auth"
    set_max_doc_lines(project, 10)
    run(project, "index", str(folder))
    index_file = folder / "index.md"
    human_text = "# This index is now human-maintained\n"
    index_file.write_text(human_text, encoding="utf-8")

    set_max_doc_lines(project, 200)
    run(project, "index", str(folder))

    assert index_file.read_text(encoding="utf-8") == human_text
    assert ("auth.py", "Session", "3", "6") in index_rows(folder / "CLAUDE.md")


def test_both_mode(project):
    init(project, doc="both")
    assert (project / "src/AGENTS.md").is_file()
    assert (project / "src/CLAUDE.md").read_text(encoding="utf-8") == "@AGENTS.md\n"
    assert "# Parent: ../AGENTS.md" in (project / "src/auth/AGENTS.md").read_text(encoding="utf-8")


def test_switch_to_both_merges_managed_root_claude_with_human_root_agents(project):
    init(project)
    claude = project / "CLAUDE.md"
    agents = project / "AGENTS.md"
    claude.write_text(claude.read_text(encoding="utf-8").replace(
        EN["placeholder"], "Managed root role.", 1).replace(
        "## Notes", "## Notes\n\nExisting Claude notes."), encoding="utf-8")
    human_rules = ("# Shared rules\n\n" +
                   "\n".join(f"- Keep rule {number}." for number in range(25)) +
                   "\n\n## Detailed scope\n\nHuman details stay here.\n")
    agents.write_text(human_rules, encoding="utf-8")

    run(project, "init", "--doc", "both")
    run(project, "index", "--all")
    run(project, "index", "--all")

    merged = agents.read_text(encoding="utf-8")
    assert "Managed root role." in merged
    assert "Existing Claude notes." in merged
    assert "Human details stay here." in merged
    assert all(f"- Keep rule {number}." in merged for number in range(25))
    assert claude.read_text(encoding="utf-8") == "@AGENTS.md\n"


def test_switch_to_both_warns_when_both_root_docs_have_managed_sections(project, capsys):
    init(project)
    claude = project / "CLAUDE.md"
    agents = project / "AGENTS.md"
    old_claude = claude.read_text(encoding="utf-8").replace(EN["placeholder"], "Claude role.", 1)
    claude.write_text(old_claude, encoding="utf-8")
    human_agents = "# Shared rules\n\n## What this folder is for\n\nHuman rule body.\n"
    agents.write_text(human_agents, encoding="utf-8")

    run(project, "init", "--doc", "both")
    run(project, "index", "--all")

    assert "both CLAUDE.md and AGENTS.md contain folder-document sections" in capsys.readouterr().out
    assert claude.read_text(encoding="utf-8") == old_claude
    assert agents.read_text(encoding="utf-8") == human_agents


def test_split_and_both_migration_do_not_require_path_write_text_newline(project, monkeypatch):
    init(project)
    root_claude = project / "CLAUDE.md"
    root_claude.write_text(root_claude.read_text(encoding="utf-8").replace(
        EN["placeholder"], "Root role.", 1), encoding="utf-8")
    root_agents = project / "AGENTS.md"
    root_agents.write_text("# Shared rules\n\nKeep this rule.\n", encoding="utf-8")
    set_max_doc_lines(project, 10)

    original_write_text = Path.write_text

    def python39_write_text(path, text, *args, **kwargs):
        if "newline" in kwargs:
            raise TypeError("Path.write_text() got an unexpected keyword argument 'newline'")
        return original_write_text(path, text, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", python39_write_text)
    folder = project / "src/auth"
    run(project, "index", str(folder))
    assert (folder / "index.md").read_text(encoding="utf-8").startswith(
        lb.GENERATED_MARKER + "\n")

    run(project, "init", "--doc", "both")
    run(project, "index", "--all")
    assert "Root role." in root_agents.read_text(encoding="utf-8")
    assert "Keep this rule." in root_agents.read_text(encoding="utf-8")
    assert root_claude.read_text(encoding="utf-8") == "@AGENTS.md\n"
    assert (folder / "AGENTS.md").is_file()


def test_exclude_and_gitignore(project):
    (project / ".gitignore").write_text("gen/\n", encoding="utf-8")
    (project / "gen").mkdir()
    (project / "gen/x.py").write_text("def f(): pass\n", encoding="utf-8")
    (project / "node_modules/p").mkdir(parents=True)
    (project / "node_modules/p/i.js").write_text("function f(){}\n", encoding="utf-8")
    (project / "tmpx").mkdir()
    (project / "tmpx/t.py").write_text("def f(): pass\n", encoding="utf-8")
    run(project, "init", "--doc", "CLAUDE.md", "--exclude", "tmpx")
    run(project, "scaffold")
    for d in ["gen", "node_modules", "tmpx"]:
        assert not (project / d / "CLAUDE.md").exists(), d


# ---------------------------------------------------------------- hooks


def test_hook_post_edit_claude(project):
    init(project)
    src = project / "src/auth/auth.py"
    src.write_text("\n\n" + src.read_text(encoding="utf-8"), encoding="utf-8")
    out = hook("post-edit", {"cwd": str(project), "tool_name": "Edit",
                             "tool_input": {"file_path": str(src)}})
    assert out == ""
    assert ("auth.py", "Session", "5", "8") in index_rows(project / "src/auth/CLAUDE.md")


def test_hook_post_edit_codex_patch(project):
    init(project)
    (project / "src/db").mkdir()
    (project / "src/db/conn.py").write_text("def connect():\n    pass\n", encoding="utf-8")
    (project / "web/main.go").unlink()
    (project / "web/new.go").write_text("package web\n\nfunc N() {}\n", encoding="utf-8")
    patch = ("*** Begin Patch\n*** Add File: src/db/conn.py\n+def connect():\n+    pass\n"
             "*** Update File: web/main.go\n*** Move to: web/new.go\n@@\n*** End Patch\n")
    out = hook("post-edit", {"cwd": str(project), "tool_name": "apply_patch",
                             "tool_input": {"command": patch}})
    ctx = json.loads(out)["hookSpecificOutput"]
    assert ctx["hookEventName"] == "PostToolUse" and "src/db" in ctx["additionalContext"]
    assert index_rows(project / "src/db/CLAUDE.md") == [("conn.py", "connect", "1", "2")]
    assert "| db/ |" in (project / "src/CLAUDE.md").read_text(encoding="utf-8")
    assert index_rows(project / "web/CLAUDE.md") == [("new.go", "N", "3", "3")]


def test_hook_ignores_unmanaged_project(tmp_path):
    (tmp_path / "a.py").write_text("def f(): pass\n", encoding="utf-8")
    out = hook("post-edit", {"cwd": str(tmp_path), "tool_input": {"file_path": str(tmp_path / "a.py")}})
    assert out == ""
    assert json.loads(hook("stop", {"cwd": str(tmp_path)})) == {}
    assert not (tmp_path / "CLAUDE.md").exists()


def test_hook_ignores_doc_edits(project):
    init(project)
    doc = project / "src/CLAUDE.md"
    before = doc.read_text(encoding="utf-8")
    hook("post-edit", {"cwd": str(project), "tool_input": {"file_path": str(doc)}})
    assert doc.read_text(encoding="utf-8") == before


def test_session_start_hook_reports_scan_error_without_stopping_session(project, monkeypatch, capsys):
    init(project)

    def fail_scan(_lib):
        raise RuntimeError("scan failed")

    monkeypatch.setattr(lb, "find_overlong_docs", fail_scan)
    assert hook("session-start", {"cwd": str(project)}) == ""
    assert "librarian hook error: RuntimeError('scan failed')" in capsys.readouterr().err


def test_session_start_command_keeps_python3_fallback():
    hooks = json.loads((REPO_ROOT / "hooks/hooks.json").read_text(encoding="utf-8"))
    command = hooks["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    assert command.startswith("python3 -c ")
    assert " || python -c " in command
    assert "CLAUDE_PLUGIN_ROOT" in command and "PLUGIN_ROOT" in command


def test_check_and_session_start_warn_on_long_folder_and_rule_documents(project, capsys):
    init(project, doc="both")
    for doc in project.rglob("AGENTS.md"):
        doc.write_text(doc.read_text(encoding="utf-8").replace(EN["placeholder"], "role"),
                       encoding="utf-8")
    set_max_doc_lines(project, 30)
    folder_doc = project / "src/auth/AGENTS.md"
    long_notes = "\n".join(f"- note {number}" for number in range(31))
    folder_doc.write_text(folder_doc.read_text(encoding="utf-8").replace(
        "## Notes", "## Notes\n\n" + long_notes), encoding="utf-8")
    root_agents = project / "AGENTS.md"
    root_agents.write_text(root_agents.read_text(encoding="utf-8").replace(
        "## Notes", "## Notes\n\n" + long_notes), encoding="utf-8")
    rules_dir = project / ".claude/rules"
    rules_dir.mkdir(parents=True)
    (rules_dir / "long.md").write_text("rule\n" * 31, encoding="utf-8")

    run(project, "check", "--fix")
    warnings = capsys.readouterr().out
    assert "src/auth/AGENTS.md" in warnings
    assert ".claude/rules/long.md" in warnings
    assert warnings.count("[warning] AGENTS.md:") == 1
    assert "src/auth/CLAUDE.md" not in warnings
    assert (project / "src/auth/CLAUDE.md").read_text(encoding="utf-8") == "@AGENTS.md\n"
    assert "[Index](index.md)" in folder_doc.read_text(encoding="utf-8")

    run(project, "check")  # warnings alone do not fail a read-only check
    assert "[drift]" not in capsys.readouterr().out
    start = json.loads(hook("session-start", {"cwd": str(project / "src/auth")}))
    context = start["hookSpecificOutput"]
    assert context["hookEventName"] == "SessionStart"
    assert "src/auth/AGENTS.md" in context["additionalContext"]
    assert ".claude/rules/long.md" in context["additionalContext"]
    assert "AGENTS.md (" in context["additionalContext"]

    set_max_doc_lines(project, 200)
    assert hook("session-start", {"cwd": str(project)}) == ""


def test_check_warns_on_user_owned_root_agents_without_modifying_it(project, capsys):
    init(project, doc="CLAUDE.md")
    _fill_all_roles(project)
    set_max_doc_lines(project, 30)
    root_agents = project / "AGENTS.md"
    manual_rules = "# Shared rules\n" + "Follow this rule.\n" * 31
    root_agents.write_text(manual_rules, encoding="utf-8")

    run(project, "check", "--fix")

    assert "[warning] AGENTS.md: 32 lines > maxDocLines 30" in capsys.readouterr().out
    assert root_agents.read_text(encoding="utf-8") == manual_rules
    assert "| AGENTS.md |" not in root_doc(project)
    assert "AGENTS.md (32 lines)" in json.loads(hook(
        "session-start", {"cwd": str(project)}))["hookSpecificOutput"]["additionalContext"]


def _fill_all_roles(project):
    for doc in project.rglob("CLAUDE.md"):
        if ".librarian" in doc.parts:
            continue
        text = doc.read_text(encoding="utf-8").replace(EN["placeholder"], "role")
        doc.write_text(text, encoding="utf-8")


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


def test_init_installs_no_skill(project):
    init(project)
    assert not (project / ".librarian/skills").exists()
    assert not any((project / agent / "skills").exists() for agent in (".claude", ".agents", ".codex"))
    assert not (project / ".gitignore").exists()


def test_pending_deepest_first(project, capsys):
    init(project)
    capsys.readouterr()
    run(project, "pending")
    lines = capsys.readouterr().out.split()
    depths = [0 if l == "." else len(Path(l).parts) for l in lines]
    assert depths == sorted(depths, reverse=True) and lines[-1] == "."


# ---------------------------------------------------------------- library language


def test_default_language_is_english(project):
    init(project)
    assert json.loads((project / ".librarian/config.json").read_text(encoding="utf-8"))["language"] == "en"
    text = (project / "src/auth/CLAUDE.md").read_text(encoding="utf-8")
    assert EN["role"] in text and "| File | Function | Start | End |" in text
    assert "| Folder | Role |" in (project / "src/CLAUDE.md").read_text(encoding="utf-8")


def test_korean_library(project, capsys):
    init(project, language="ko")
    text = (project / "src/auth/CLAUDE.md").read_text(encoding="utf-8")
    assert text.startswith("# 상위 문서: ../CLAUDE.md")
    assert KO["role"] in text and KO["placeholder"] in text and "| 파일 | 함수 | 시작 줄 | 끝 줄 |" in text
    assert root_doc(project).startswith(f"# {project.name}\n\n{KO['role']}\n")
    capsys.readouterr()
    run(project, "pending")
    assert "src/auth" in capsys.readouterr().out.splitlines()


def test_language_switch_keeps_roles(project):
    init(project, language="ko")
    doc = project / "src/CLAUDE.md"
    doc.write_text(doc.read_text(encoding="utf-8")
                   .replace(KO["placeholder"], "소스 코드", 1)
                   .replace(f"| auth/ | {KO['placeholder']} |", "| auth/ | 인증 |"), encoding="utf-8")
    run(project, "init", "--language", "en", "--doc", "CLAUDE.md")
    run(project, "index", "--all")
    text = doc.read_text(encoding="utf-8")
    assert text.startswith("# Parent: ../CLAUDE.md")
    assert EN["role"] in text and "소스 코드" in text
    assert "| auth/ | 인증 |" in text and f"| api/ | {EN['placeholder']} |" in text
    assert not any(v in text for v in (KO["role"], KO["subdirs"], KO["placeholder"]))


def test_unknown_language_uses_english_headings(project):
    init(project, language="ja")
    assert EN["role"] in (project / "src/CLAUDE.md").read_text(encoding="utf-8")
    init(project)
    out = json.loads(hook("stop", {"cwd": str(project)}))
    assert out["decision"] == "block" and "(ja)" in out["reason"]


# ---------------------------------------------------------------- QA round 3 regressions (sync)


def _role_doc(project, rel):
    return (project / rel / "CLAUDE.md")


def test_unmatched_or_fenced_marker_keeps_human_text(project):
    init(project)
    doc = _role_doc(project, "src/auth")
    text = doc.read_text(encoding="utf-8")
    fenced = ("Example of the generated block:\n\n```markdown\n" + lb.INDEX_START
              + "\n| File | Function | Line |\n```\n")
    text = text.replace(EN["placeholder"], fenced)
    doc.write_text(text, encoding="utf-8")
    run(project, "index", str(project / "src/auth"))
    out = doc.read_text(encoding="utf-8")
    assert fenced in out
    assert ("auth.py", "login", "9", "10") in index_rows(doc)

    # a start marker without an end marker is treated as text, not as the index
    broken = out.replace(lb.INDEX_END, "") + "\n## Notes\n\nkeep me\n"
    doc.write_text(broken, encoding="utf-8")
    run(project, "index", str(project / "src/auth"))
    assert "keep me" in doc.read_text(encoding="utf-8")


def test_heading_inside_code_fence_is_not_a_section(project):
    init(project)
    doc = _role_doc(project, "src")
    role = "Build notes:\n\n```bash\n# install deps first\nnpm ci\n```"
    doc.write_text(doc.read_text(encoding="utf-8").replace(EN["placeholder"], role, 1), encoding="utf-8")
    run(project, "index", str(project / "src"))
    out = doc.read_text(encoding="utf-8")
    assert role in out
    assert out.index(role) < out.index(EN["subdirs"])


def test_text_under_subfolder_table_is_kept(project):
    init(project)
    doc = _role_doc(project, "src")
    text = doc.read_text(encoding="utf-8")
    table_end = text.index("| auth/ |")
    line_end = text.index("\n", table_end)
    text = text[:line_end + 1] + "\nNote: api/ is being split.\n" + text[line_end + 1:]
    doc.write_text(text, encoding="utf-8")
    run(project, "index", str(project / "src"))
    assert "Note: api/ is being split." in doc.read_text(encoding="utf-8")


def test_reinit_keeps_doc_mode(project):
    init(project, doc="both")
    run(project, "init", "--language", "ko")
    cfg = json.loads((project / ".librarian/config.json").read_text(encoding="utf-8"))
    assert cfg["docName"] == "both" and cfg["language"] == "ko"


def test_switching_to_both_moves_roles(project):
    init(project)
    doc = _role_doc(project, "src")
    doc.write_text(doc.read_text(encoding="utf-8").replace(EN["placeholder"], "Source code.", 1),
                   encoding="utf-8")
    run(project, "init", "--doc", "both")
    run(project, "index", "--all")
    assert "Source code." in (project / "src/AGENTS.md").read_text(encoding="utf-8")
    assert (project / "src/CLAUDE.md").read_text(encoding="utf-8") == "@AGENTS.md\n"


def test_post_edit_updates_parent_of_topmost_new_folder(project):
    init(project)
    new = project / "x/y z/한/q.py"
    new.parent.mkdir(parents=True)
    new.write_text("def q(): pass\n", encoding="utf-8")
    hook("post-edit", {"cwd": str(project), "tool_input": {"file_path": str(new)}})
    assert "| x/ |" in root_doc(project)
    assert "| y z/ |" in (project / "x/CLAUDE.md").read_text(encoding="utf-8")


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


def test_config_with_bom(project):
    init(project)
    cfg = project / ".librarian/config.json"
    cfg.write_bytes(b"\xef\xbb\xbf" + cfg.read_bytes())
    run(project, "index", "--all")
    src = project / "src/auth/auth.py"
    src.write_text("\n" + src.read_text(encoding="utf-8"), encoding="utf-8")
    hook("post-edit", {"cwd": str(project), "tool_input": {"file_path": str(src)}})
    assert ("auth.py", "Session", "4", "7") in index_rows(project / "src/auth/CLAUDE.md")


def test_stop_hook_active_string_false(project):
    init(project)
    out = json.loads(hook("stop", {"cwd": str(project), "stop_hook_active": "false"}))
    assert out.get("decision") == "block"


def test_parse_failure_keeps_previous_rows(project):
    init(project)
    (project / "src/auth/auth.py").write_text("def broken(:\n", encoding="utf-8")
    run(project, "index", str(project / "src/auth"))
    assert ("auth.py", "login", "9", "10") in index_rows(project / "src/auth/CLAUDE.md")


def test_parse_failure_keeps_legacy_three_column_rows(project):
    init(project)
    doc = project / "src/auth/CLAUDE.md"
    text = doc.read_text(encoding="utf-8")
    new_block = text[text.index(lb.INDEX_START):text.index(lb.INDEX_END)]
    legacy_block = (f"{lb.INDEX_START}\n| File | Function | Line |\n|---|---|---|\n"
                    "| auth.py | Session | 3 |\n| auth.py | login | 9 |\n")
    doc.write_text(text.replace(new_block, legacy_block), encoding="utf-8")
    (project / "src/auth/auth.py").write_text("def broken(:\n", encoding="utf-8")

    run(project, "index", str(project / "src/auth"))

    assert index_rows(doc) == [("auth.py", "Session", "3", "-"), ("auth.py", "login", "9", "-")]
    assert "| File | Function | Start | End |" in doc.read_text(encoding="utf-8")


def test_invalid_config_numbers_fall_back(project):
    init(project)
    cfg_path = project / ".librarian/config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["maxDepth"] = "deep"
    cfg["maxDocLines"] = "many"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    run(project, "index", "--all")  # must not raise
    run(project, "update")
    assert read_config(project)["maxDocLines"] == 200


def test_many_files_is_fast(tmp_path):
    import time
    for d in range(200):
        for f in range(15):
            p = tmp_path / f"pkg{d % 20}" / f"mod{d}" / f"f{f}.py"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("def f(): pass\n", encoding="utf-8")
    git(tmp_path, "init", "-q")
    run(tmp_path, "init", "--doc", "CLAUDE.md")
    start = time.perf_counter()
    run(tmp_path, "index", "--all")
    run(tmp_path, "pending")
    assert time.perf_counter() - start < 15


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


def test_orphan_start_marker_never_loses_text(project):
    init(project)
    doc = project / "src/auth/CLAUDE.md"
    text = doc.read_text(encoding="utf-8").replace(lb.INDEX_END, "") + "\n## Notes\n\nImportant human notes\n"
    doc.write_text(text, encoding="utf-8")
    for _ in range(3):
        run(project, "index", str(project / "src/auth"))
    out = doc.read_text(encoding="utf-8")
    assert "Important human notes" in out
    assert out.count(lb.INDEX_START) == 1 and out.count(lb.INDEX_END) == 1


def test_parse_failure_without_previous_rows_lists_file(project):
    init(project)
    (project / "src/auth/new.py").write_text("def broken(:\n", encoding="utf-8")
    run(project, "index", str(project / "src/auth"))
    assert ("new.py", "-", "-", "-") in index_rows(project / "src/auth/CLAUDE.md")


def test_negative_limits_fall_back(project):
    init(project)
    cfg = read_config(project)
    cfg["maxDepth"] = -5
    cfg["maxDocLines"] = 0
    write_config(project, cfg)
    run(project, "update")
    assert read_config(project)["maxDepth"] == lb.DEFAULT_CONFIG["maxDepth"]
    assert read_config(project)["maxDocLines"] == lb.DEFAULT_CONFIG["maxDocLines"]


# ---------------------------------------------------------------- config


def read_config(project):
    return json.loads((project / ".librarian/config.json").read_text(encoding="utf-8"))


def write_config(project, cfg):
    (project / ".librarian/config.json").write_text(json.dumps(cfg), encoding="utf-8")


def set_max_doc_lines(project, limit):
    cfg = read_config(project)
    cfg["maxDocLines"] = limit
    write_config(project, cfg)


# keys written by versions that had the index-row warning, the session-start hook, or the
# rules skill links
@pytest.mark.parametrize("key,value", [("maxEntries", 60), ("injectRules", False),
                                       ("targets", ["claude"])])
@pytest.mark.parametrize("command", ["update", "init"])
def test_rewriting_config_drops_removed_key_and_keeps_others(project, key, value, command):
    init(project)
    write_config(project, {"language": "en", "maxDepth": 4, key: value})

    run(project, "index", "--all")  # must not raise
    run(project, command)

    cfg = read_config(project)
    assert key not in cfg
    assert cfg["maxDepth"] == 4


# ---------------------------------------------------------------- update


def test_update_fills_missing_keys_and_records_version(project):
    init(project)
    write_config(project, {"language": "en", "docName": "CLAUDE.md"})
    run(project, "update")
    cfg = read_config(project)
    assert cfg["libraryVersion"] == plugin_version_from_manifest()
    assert cfg["maxDepth"] == lb.DEFAULT_CONFIG["maxDepth"]


def test_update_keeps_korean_headings_and_roles(project):
    init(project, language="ko")
    doc = project / "src/CLAUDE.md"
    doc.write_text(doc.read_text(encoding="utf-8").replace(KO["placeholder"], "소스 코드", 1),
                   encoding="utf-8")
    run(project, "update")
    text = doc.read_text(encoding="utf-8")
    assert text.startswith("# 상위 문서: ../CLAUDE.md")
    assert KO["role"] in text and "소스 코드" in text


# ---------------------------------------------------------------- stop hook version notice


@pytest.mark.parametrize("codex_manifest,claude_manifest,expected_version", [
    (b'{"version":"0.6.1"}', b'{"version":"0.6.0"}', "0.6.1"),
    (None, b'{"version":"0.6.1"}', "0.6.1"),
    (b'{', b'{"version":"0.6.1"}', "0.6.1"),
    (b'\xff', b'{"version":"0.6.1"}', "0.6.1"),
    (b'[]', b'{"version":"0.6.1"}', "0.6.1"),
    (None, None, None),
    (b'{', b'\xff', None),
], ids=["codex-preferred", "claude-only", "malformed-codex", "non-utf8-codex",
        "non-object-codex", "both-absent", "both-unreadable"])
def test_native_manifests_stamp_cli_versions_and_preserve_hook_notices(
        project, tmp_path, codex_manifest, claude_manifest, expected_version):
    plugin_root = tmp_path / "native plugin"
    shutil.copytree(REPO_ROOT / "scripts", plugin_root / "scripts",
                    ignore=shutil.ignore_patterns("__pycache__"))
    for manifest_dir, contents in ((".codex-plugin", codex_manifest),
                                   (".claude-plugin", claude_manifest)):
        if contents is not None:
            manifest = plugin_root / manifest_dir / "plugin.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_bytes(contents)
    # A stale portable manifest must not affect the migrated version lookup.
    (plugin_root / "plugin.json").write_text('{"version":"99.0.0"}', encoding="utf-8")
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

    cli("init", "--doc", "AGENTS.md")
    assert read_config(project)["libraryVersion"] == expected_version
    cli("scaffold")
    cfg = read_config(project)
    cfg["libraryVersion"] = "0.0.1"
    cfg["maxDocLines"] = 30
    write_config(project, cfg)
    rules = project / ".claude/rules/long.md"
    rules.parent.mkdir(parents=True)
    rules.write_text("Follow this rule.\n" * 31, encoding="utf-8")

    context = json.loads(cli("hook", "session-start", payload={"cwd": str(project)}))
    assert context["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert ".claude/rules/long.md" in context["hookSpecificOutput"]["additionalContext"]
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
    init(project)
    monkeypatch.setattr(lb, "plugin_version", lambda: None)
    out = json.loads(hook("stop", {"cwd": str(project)}))
    assert out["decision"] == "block"
    assert "systemMessage" not in out


def test_stop_hook_has_no_update_notice_when_versions_match(project):
    init(project)
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
    capsys.readouterr()

    run(project, command)

    out = capsys.readouterr().out
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
    capsys.readouterr()

    run(project, "update")

    out = capsys.readouterr().out
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
    capsys.readouterr()
    run(project, "update")
    out = capsys.readouterr().out
    assert "librarian-guide" not in out and ".gitignore" not in out


def test_stop_command_from_hooks_json_removes_legacy_root_note(project):
    init(project)
    write_root_with_note(project, LEGACY_EN_NOTE)
    hooks = json.loads((REPO_ROOT / "hooks/hooks.json").read_text(encoding="utf-8"))
    command = hooks["hooks"]["Stop"][0]["hooks"][0]["command"]
    env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(REPO_ROOT)}
    payload = json.dumps({"cwd": str(project), "hook_event_name": "Stop",
                          "stop_hook_active": True})

    res = subprocess.run(command, shell=True, cwd=project, env=env, input=payload.encode("utf-8"),
                         capture_output=True, timeout=60)

    assert res.returncode == 0, res.stderr.decode("utf-8", "replace")
    assert LEGACY_EN_NOTE not in root_doc(project) and "Our own intro." in root_doc(project)
