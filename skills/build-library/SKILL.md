---
name: build-library
description: Installs an agent-librarian library in a new project (or one with little code). Creates the config file, the folder document skeletons, and the code catalog.
disable-model-invocation: true
---

# Build a library (new project)

`<plugin>` is the plugin root, two levels above this SKILL.md. The script is `<plugin>/scripts/librarian.py`. Run every command from the project root.

## 1. Questions

Ask with an interactive question tool if one is available; otherwise ask in a normal message. **Ask the library language first**, and ask the remaining question in that language.

1. **Library language**: the language the folder documents are written in.
   - `en` (English, default) or `ko` (Korean) have built-in headings.
   - Any other language is also accepted, e.g. `ja`. Headings stay in English, and roles are written in that language.
2. **Additional paths to exclude**
   - Excluded by default: paths in `.gitignore`, folders starting with a dot, `node_modules`, `dist`, `build`, and similar

## 2. Check Python

```bash
python --version
```

The plugin needs only Python 3.9 or later; it has no other dependencies. If Python is missing or older, ask the user to install a newer one.

## 3. Install

```bash
python <plugin>/scripts/librarian.py init --language <answer 1> [--exclude <answer 2>...]
python <plugin>/scripts/librarian.py scaffold
python <plugin>/scripts/librarian.py index --all
```

- `init` creates `.librarian/config.json` (including `maxDocLines`, default 60) and `.librarian/.gitignore`, which keeps the derived catalog out of git. In a library built with an older version, it also removes the old rules skill links; pass any `warning` lines on to the user.
- `scaffold` creates a `CLAUDE.md` skeleton in the root and in every folder that holds code. Each document has a role section, a Notes section for human or agent context, and a subfolder table.
- `index --all` builds the catalog (`.librarian/catalog.json`): file · symbol · start line · end line for every code file.

## 4. Fill in roles

If `python <plugin>/scripts/librarian.py pending` lists any folders, fill them in yourself following `<plugin>/skills/rebuild-library/references/cataloger.md`, in the library language. A new project has few folders, so do not use subagents.

## 5. Wrap up

- Show the user the root document and `.librarian/config.json`, and ask them to confirm the settings and roles look right.
- Explain what happens from now on:
  - At session start, a hook tells the agent how to query the catalog (`find <regex>`, `grep <regex>`, `outline <path>`) and refreshes it in the background. The catalog also refreshes itself whenever it is queried, so it never needs to be committed or edited.
  - At the end of each turn, a hook creates documents for new code folders, updates subfolder tables, and asks the agent to fill in empty roles (at most 10 folders are listed at a time).
  - The session-start hook also warns about folder documents and rule files whose human-written text is longer than `maxDocLines`. `check` reports the same warnings.
  - Use `<plugin>/skills/rule-creator/SKILL.md` to place or shorten working rules.
