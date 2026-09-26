---
name: build-library
description: Installs a claude-librarian library in a new project (or one with little code). Creates the config file, the library-rules skill, and the folder document skeletons.
disable-model-invocation: true
---

# Build a library (new project)

`<plugin>` is the plugin root, two levels above this SKILL.md. The script is `<plugin>/scripts/librarian.py`. Run every command from the project root.

## 1. Questions

Ask with an interactive question tool if one is available; otherwise ask in a normal message. **Ask the library language first**, and ask the remaining questions in that language.

1. **Library language**: the language the folder documents are written in.
   - `en` (English, default) or `ko` (Korean) have built-in headings.
   - Any other language is also accepted, e.g. `ja`. Headings stay in English, and roles are written in that language.
2. **Folder document name**
   - `CLAUDE.md`: Claude Code only
   - `AGENTS.md`: Codex and other agents
   - `both`: the content goes in AGENTS.md, and CLAUDE.md contains only `@AGENTS.md`
3. **Where to link the library-rules skill** (multiple choice; default is all)
   - `claude` → `.claude/skills`
   - `agents` → `.agents/skills`
   - `codex` → `.codex/skills`
4. **Additional paths to exclude**
   - Excluded by default: paths in `.gitignore`, folders starting with a dot, `node_modules`, `dist`, `build`, and similar

## 2. Check dependencies

```bash
python -c "import tree_sitter_language_pack"
```

If this fails, tell the user to run `pip install -r <plugin>/requirements.txt`. Run it yourself only if the user agrees.

## 3. Install

```bash
python <plugin>/scripts/librarian.py init --language <answer 1> --doc <answer 2> --targets <answer 3, comma-separated> [--exclude <answer 4>...]
python <plugin>/scripts/librarian.py scaffold
```

- `init` does three things:
  - Creates `.librarian/config.json`.
  - Installs `.librarian/skills/librarian-guide` and links it into each target. It uses a junction on Windows and a symbolic link elsewhere, and copies if linking fails.
  - Adds the link paths to `.gitignore`.
- `scaffold` creates a skeleton document in every folder that lacks one.

## 4. Fill in roles

If `python <plugin>/scripts/librarian.py pending` lists any folders, fill them in yourself following `<plugin>/skills/rebuild-library/references/cataloger.md`, in the library language. A new project has few folders, so do not use subagents.

## 5. Wrap up

- Show the user the root document and `.librarian/config.json`, and ask them to confirm the rules look right.
- Explain what happens from now on:
  - When a file is edited, a hook updates the index.
  - At the end of each turn, a check hook verifies that the documents match the code.
- Tell Codex users two things:
  - `~/.codex/config.toml` needs `[features] hooks = true`.
  - Codex runs an installed plugin's hooks only after they are trusted once in `/hooks`.
