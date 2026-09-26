---
name: rebuild-library
description: Scans an existing codebase and builds (or rebuilds) a agent-librarian library. A script generates the index; agents fill in folder roles, deepest folders first.
disable-model-invocation: true
---

# Rebuild the library (existing codebase)

`<plugin>` is the plugin root, two levels above this SKILL.md. Run every command from the project root.

## 0. Cost warning

Before starting, tell the user: this reads the whole codebase and writes a role for every folder, so token cost grows with the number of folders. In Claude Code it uses Sonnet subagents.

## 1. Questions and dependencies

Follow steps 1–2 of `<plugin>/skills/build-library/SKILL.md` exactly. The library language is still the first question. If `.librarian/config.json` already exists, show its current values and ask only whether to change them.

## 2. Generate the mechanical parts first

```bash
python <plugin>/scripts/librarian.py init --language <answer 1> --doc <answer 2> [--exclude <answer 3>...]
python <plugin>/scripts/librarian.py scaffold
python <plugin>/scripts/librarian.py index --all
```

After this, every folder has a document and every index (file · function · start line · end line) is filled in. If the language changed, existing documents switch their generated headings to the new language, and the roles already written are kept.

## 3. Fill in roles (deepest folders first)

`python <plugin>/scripts/librarian.py pending` lists the folders whose roles are empty, deepest first. A parent can only summarize its children in one line once their roles exist, so **keep this order.**

- **If you can use subagents** (Claude Code):
  - Hand folders of the same depth to `folder-cataloger` agents in parallel, about 5–10 folders per agent.
  - Give each agent three things: its folder document paths, the rules file path `<plugin>/skills/rebuild-library/references/cataloger.md`, and the library language.
  - Finish one depth completely before moving to the next, shallower one.
- **If you cannot use subagents** (Codex and others): read `references/cataloger.md` and fill in the folders yourself, one at a time, in the same order.

## 4. Verify and report

```bash
python <plugin>/scripts/librarian.py check
```

Report to the user:
- How many documents were created
- Any remaining `role needed` entries
- Any folder depth warnings (`warning`). Do not restructure folders; only suggest it to the user.

Then give the same wrap-up as step 5 of build-library.
