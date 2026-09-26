import io
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
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
    ("src/auth/auth.py", [("Session", 3), ("Session.refresh", 4), ("login", 9)]),
    ("src/api/svc.ts", [("Svc", 1), ("Svc.run", 2), ("handler", 4)]),
    ("web/main.go", [("S", 3), ("S.Do", 5), ("Top", 7)]),
    ("native/lib.cpp", [("C", 2), ("C::m", 3), ("make", 5)]),
    ("native/lib.rs", [("P", 1), ("P", 2), ("P.new", 3), ("main", 5)]),
    ("native/J.java", [("J", 1), ("J.J", 2), ("J.run", 3)]),
    ("native/K.cs", [("K", 2), ("K.M", 3)]),
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
        ("auth.py", "Session", "3"), ("auth.py", "Session.refresh", "4"), ("auth.py", "login", "9")]
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
    assert ("auth.py", "Session", "5") in index_rows(doc)
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
    assert ("auth.py", "Session", "5") in index_rows(project / "src/auth/CLAUDE.md")


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
    assert index_rows(project / "src/db/CLAUDE.md") == [("conn.py", "connect", "1")]
    assert "| db/ |" in (project / "src/CLAUDE.md").read_text(encoding="utf-8")
    assert index_rows(project / "web/CLAUDE.md") == [("new.go", "N", "3")]


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


def test_hook_stop_warns_on_size(project):
    init(project)
    cfg_path = project / ".librarian/config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["maxEntries"] = 2
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    out = json.loads(hook("stop", {"cwd": str(project), "stop_hook_active": True}))
    assert "src/auth" in out["systemMessage"]


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
    assert EN["role"] in text and "| File | Function | Line |" in text
    assert "| Folder | Role |" in (project / "src/CLAUDE.md").read_text(encoding="utf-8")


def test_korean_library(project):
    init(project, language="ko")
    text = (project / "src/auth/CLAUDE.md").read_text(encoding="utf-8")
    assert text.startswith("# 상위 문서: ../CLAUDE.md")
    assert KO["role"] in text and KO["placeholder"] in text and "| 파일 | 함수 | 줄 |" in text
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
    assert ("auth.py", "login", "9") in index_rows(doc)

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
    assert ("auth.py", "Session", "4") in index_rows(project / "src/auth/CLAUDE.md")


def test_stop_hook_active_string_false(project):
    init(project)
    out = json.loads(hook("stop", {"cwd": str(project), "stop_hook_active": "false"}))
    assert out.get("decision") == "block"


def test_parse_failure_keeps_previous_rows(project):
    init(project)
    (project / "src/auth/auth.py").write_text("def broken(:\n", encoding="utf-8")
    run(project, "index", str(project / "src/auth"))
    assert ("auth.py", "login", "9") in index_rows(project / "src/auth/CLAUDE.md")


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
    assert ("new.py", "-", "-") in index_rows(project / "src/auth/CLAUDE.md")


def test_negative_limits_fall_back(project):
    init(project)
    cfg_path = project / ".librarian/config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["maxEntries"] = -5
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    assert lb.load_library(project).config["maxEntries"] == lb.DEFAULT_CONFIG["maxEntries"]
