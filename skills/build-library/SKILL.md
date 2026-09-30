---
name: build-library
description: Installs a agent-librarian library in a new project (or one with little code). Creates the config file and the folder document skeletons.
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
3. **Additional paths to exclude**
   - Excluded by default: paths in `.gitignore`, folders starting with a dot, `node_modules`, `dist`, `build`, and similar

## 2. Check Python

```bash
python --version
```

The plugin needs only Python 3.9 or later; it has no other dependencies. If Python is missing or older, ask the user to install a newer one.

## 3. Install

```bash
python <plugin>/scripts/librarian.py init --language <answer 1> --doc <answer 2> [--exclude <answer 3>...]
python <plugin>/scripts/librarian.py scaffold
```

- `init` creates `.librarian/config.json`, including `maxDocLines` (the document line limit, default 200). In a library built with an older version, it also removes the old rules skill links the same way `update` does (see `<plugin>/skills/update-library/SKILL.md`); pass any `warning` lines on to the user.
- `scaffold` creates a skeleton document in every folder that lacks one. Each document has a Notes section for human or agent context, separate from the generated index.

## 4. Fill in roles

If `python <plugin>/scripts/librarian.py pending` lists any folders, fill them in yourself following `<plugin>/skills/rebuild-library/references/cataloger.md`, in the library language. A new project has few folders, so do not use subagents.

## 5. Wrap up

- Show the user the root document and `.librarian/config.json`, and ask them to confirm the settings and roles look right.
- Explain what happens from now on:
  - When a file is edited, a hook updates the index.
  - At the end of each turn, a check hook fixes documents that no longer match the code and asks the agent to fill in any folder whose role is empty or missing.
  - At session start, a hook warns about folder documents and rule files longer than `maxDocLines`. `check` reports the same warnings.
  - If an index would make a folder document too long, the script moves it into `index.md` and, if needed, per-file indexes in `index/`.
  - Use `<plugin>/skills/rule-creator/SKILL.md` to place or shorten working rules. Put rules for Codex or both clients in root `AGENTS.md` Notes with their scope in the text; in `both` mode, leave the `CLAUDE.md` alias alone.
- Tell Codex users two things:
  - `~/.codex/config.toml` needs `[features] hooks = true`.
  - Codex runs an installed plugin's hooks only after they are trusted once in `/hooks`.
