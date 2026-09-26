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


def init(root, doc="CLAUDE.md", targets="claude,agents,codex", language=None):
    extra = ["--language", language] if language else []
    run(root, "init", "--doc", doc, "--targets", targets, *extra)
    run(root, "scaffold")


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
def test_extract_symbols(project, rel, expected):
    assert lb.extract_symbols(project / rel) == expected


# ---------------------------------------------------------------- scaffold / index


def test_scaffold_creates_hierarchy(project):
    init(project)
    for d in [".", "src", "src/auth", "src/api", "web", "native", "assets"]:
        assert (project / d / "CLAUDE.md").is_file(), d
    root = (project / "CLAUDE.md").read_text(encoding="utf-8")
    assert EN["root_note"] in root
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


def test_both_mode(project):
    init(project, doc="both")
    assert (project / "src/AGENTS.md").is_file()
    assert (project / "src/CLAUDE.md").read_text(encoding="utf-8") == "@AGENTS.md\n"
    assert "# Parent: ../AGENTS.md" in (project / "src/auth/AGENTS.md").read_text(encoding="utf-8")


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


def _fill_all_roles(project):
    for doc in project.rglob("CLAUDE.md"):
        if ".librarian" in doc.parts:
            continue
        text = doc.read_text(encoding="utf-8").replace(EN["placeholder"], "role")
        doc.write_text(text, encoding="utf-8")


def test_hook_stop_after_folder_changes(project):
    init(project)
    _fill_all_roles(project)
    git(project, "add", "-A")
    git(project, "-c", "user.email=a@b", "-c", "user.name=t", "commit", "-qm", "init")
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


# ---------------------------------------------------------------- skill links


def test_init_links_skills(project):
    init(project)
    src = project / ".librarian/skills/librarian-guide/SKILL.md"
    assert src.is_file()
    for t in [".claude", ".agents", ".codex"]:
        linked = project / t / "skills/librarian-guide"
        assert (linked / "SKILL.md").read_text(encoding="utf-8") == src.read_text(encoding="utf-8")
    gi = (project / ".gitignore").read_text(encoding="utf-8")
    assert "/.claude/skills/librarian-guide" in gi


def test_skill_copy_fallback_and_drift(project, monkeypatch):
    def copy_only(src, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dest)
        return "copy"
    monkeypatch.setattr(lb, "_link_dir", copy_only)
    init(project, targets="claude")
    lib = lb.load_library(project)
    assert lb.check_skills(lib, fix=False).drift == []

    (project / ".librarian/skills/librarian-guide/SKILL.md").write_text("changed\n", encoding="utf-8")
    assert lb.check_skills(lib, fix=False).drift
    lb.check_skills(lib, fix=True)
    assert (project / ".claude/skills/librarian-guide/SKILL.md").read_text(encoding="utf-8") == "changed\n"


def test_check_restores_broken_link(project):
    init(project, targets="agents")
    lib = lb.load_library(project)
    lb._remove(project / ".agents/skills/librarian-guide")
    assert lb.check_skills(lib, fix=False).drift
    json.loads(hook("stop", {"cwd": str(project), "stop_hook_active": True}))
    assert (project / ".agents/skills/librarian-guide/SKILL.md").is_file()


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


def test_korean_library(project):
    init(project, language="ko")
    text = (project / "src/auth/CLAUDE.md").read_text(encoding="utf-8")
    assert text.startswith("# 상위 문서: ../CLAUDE.md")
    assert KO["role"] in text and KO["placeholder"] in text and "| 파일 | 함수 | 시작 줄 | 끝 줄 |" in text
    assert KO["root_note"] in (project / "CLAUDE.md").read_text(encoding="utf-8")
    assert "src/auth" in [r for r in lb.sync_dirs(lb.load_library(project), None, False).pending]


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
    assert EN["root_note"] in (project / "CLAUDE.md").read_text(encoding="utf-8")


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
    assert "| x/ |" in (project / "CLAUDE.md").read_text(encoding="utf-8")
    assert "| y z/ |" in (project / "x/CLAUDE.md").read_text(encoding="utf-8")


def test_renamed_folder_keeps_role_cell(project):
    init(project)
    _fill_all_roles(project)
    git(project, "add", "-A")
    git(project, "-c", "user.email=a@b", "-c", "user.name=t", "commit", "-qm", "init")
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
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    run(project, "index", "--all")  # must not raise


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
    write_config(project, cfg)
    assert lb.load_library(project).config["maxDepth"] == lb.DEFAULT_CONFIG["maxDepth"]


# ---------------------------------------------------------------- session-start rules


def read_config(project):
    return json.loads((project / ".librarian/config.json").read_text(encoding="utf-8"))


def write_config(project, cfg):
    (project / ".librarian/config.json").write_text(json.dumps(cfg), encoding="utf-8")


def session_output(project):
    """The hookSpecificOutput of the session-start hook, or None when it printed nothing."""
    out = hook("session-start", {"cwd": str(project)})
    return json.loads(out)["hookSpecificOutput"] if out else None


def session_context(project):
    return session_output(project)["additionalContext"]


def test_session_start_injects_rules_without_frontmatter(project):
    init(project)
    out = session_output(project)
    assert out["hookEventName"] == "SessionStart"
    context = out["additionalContext"]
    assert context.startswith("# Library rules")
    assert "name: librarian-guide" not in context
    assert "Library language: en, folder document: CLAUDE.md" in context


def test_session_start_strips_empty_frontmatter(project):
    init(project)
    skill = project / ".librarian/skills/librarian-guide/SKILL.md"
    skill.write_text("---\n---\n# My rules\n", encoding="utf-8")
    assert session_context(project).startswith("# My rules")


def test_rules_off_stops_injection_and_on_restores_it(project):
    init(project)
    run(project, "rules", "off")
    assert read_config(project)["injectRules"] is False
    assert session_output(project) is None

    run(project, "rules", "on")
    assert read_config(project)["injectRules"] is True
    assert "# Library rules" in session_context(project)


def test_rules_off_changes_only_its_own_key(project):
    init(project)
    write_config(project, {"language": "en"})
    run(project, "rules", "off")
    assert read_config(project) == {"language": "en", "injectRules": False}


def test_rules_status_prints_current_state(project, capsys):
    init(project)
    capsys.readouterr()
    run(project, "rules", "status")
    assert capsys.readouterr().out.strip() == "[rules] on"


def test_config_without_inject_key_injects_rules(project):
    init(project)
    cfg = read_config(project)
    del cfg["injectRules"]
    write_config(project, cfg)
    assert "# Library rules" in session_context(project)


def test_inject_rules_string_false_turns_injection_off(project):
    init(project)
    cfg = read_config(project)
    cfg["injectRules"] = "false"
    write_config(project, cfg)
    assert session_output(project) is None


@pytest.mark.parametrize("value", [None, "maybe"])
def test_inject_rules_null_or_unknown_value_keeps_injection_on(project, value):
    init(project)
    cfg = read_config(project)
    cfg["injectRules"] = value
    write_config(project, cfg)
    assert "# Library rules" in session_context(project)


def test_session_start_without_library_prints_nothing(tmp_path):
    assert hook("session-start", {"cwd": str(tmp_path)}) == ""


def test_session_start_command_from_hooks_json_prints_rules(project):
    init(project)
    hooks = json.loads((REPO_ROOT / "hooks/hooks.json").read_text(encoding="utf-8"))
    command = hooks["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(REPO_ROOT)}
    payload = json.dumps({"cwd": str(project), "hook_event_name": "SessionStart"})

    res = subprocess.run(command, shell=True, cwd=project, env=env, input=payload.encode("utf-8"),
                         capture_output=True, timeout=60)

    out = json.loads(res.stdout.decode("utf-8"))
    assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert out["hookSpecificOutput"]["additionalContext"] == session_context(project)


# ---------------------------------------------------------------- update


def test_update_fills_missing_keys_and_records_version(project):
    init(project)
    write_config(project, {"language": "en", "docName": "CLAUDE.md"})
    run(project, "update")
    cfg = read_config(project)
    assert cfg["libraryVersion"] == lb.plugin_version()
    assert cfg["injectRules"] is True
    assert cfg["targets"] == lb.DEFAULT_CONFIG["targets"]


@pytest.mark.parametrize("command", ["update", "init"])
def test_rewriting_config_drops_legacy_max_entries(project, command):
    init(project)
    write_config(project, {"language": "en", "maxEntries": 60, "maxDepth": 4})
    run(project, command)
    cfg = read_config(project)
    assert "maxEntries" not in cfg
    assert cfg["maxDepth"] == 4


def test_update_shows_diff_for_edited_rules_and_keeps_them(project, capsys):
    init(project)
    skill = project / ".librarian/skills/librarian-guide/SKILL.md"
    skill.write_text(skill.read_text(encoding="utf-8") + "\nMy own rule.\n", encoding="utf-8")
    capsys.readouterr()
    run(project, "update")
    out = capsys.readouterr().out
    assert "[skill-diff] -My own rule." in out
    assert "My own rule." in skill.read_text(encoding="utf-8")


def test_update_replace_skill_restores_template(project, capsys):
    init(project)
    skill = project / ".librarian/skills/librarian-guide/SKILL.md"
    skill.write_text("edited\n", encoding="utf-8")
    run(project, "update", "--replace-skill")
    assert lb._same_tree(skill.parent, lb.TEMPLATE_DIR)
    assert "[skill-diff]" not in capsys.readouterr().out


def test_update_replace_skill_updates_linked_skill(project):
    init(project, targets="claude")
    (project / ".librarian/skills/librarian-guide/SKILL.md").write_text("edited\n", encoding="utf-8")
    run(project, "update", "--replace-skill")
    linked = project / ".claude/skills/librarian-guide/SKILL.md"
    template = lb.TEMPLATE_DIR / "SKILL.md"
    assert linked.read_bytes() == template.read_bytes()


def test_update_ignores_line_ending_only_difference(project, tmp_path_factory, monkeypatch,
                                                    capsys):
    init(project)
    # a fixed template, because the real one's line endings depend on git's autocrlf
    template = tmp_path_factory.mktemp("template")
    (template / "SKILL.md").write_bytes(b"rule\n")
    monkeypatch.setattr(lb, "TEMPLATE_DIR", template)
    (project / ".librarian/skills/librarian-guide/SKILL.md").write_bytes(b"rule\r\n")
    capsys.readouterr()
    run(project, "update")
    assert "[skill-diff]" not in capsys.readouterr().out


def test_update_reports_file_only_in_library(project, capsys):
    init(project)
    (project / ".librarian/skills/librarian-guide/extra.md").write_text("mine\n", encoding="utf-8")
    capsys.readouterr()
    run(project, "update")
    assert "[skill-diff] extra.md: only in library" in capsys.readouterr().out


def test_update_restores_removed_skill_link(project):
    init(project, targets="agents")
    lb._remove(project / ".agents/skills/librarian-guide")
    run(project, "update")
    assert (project / ".agents/skills/librarian-guide/SKILL.md").is_file()


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
    out = stop_with_library_version(project, lb.plugin_version())
    assert "systemMessage" not in out
