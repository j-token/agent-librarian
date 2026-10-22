---
name: rebuild-library
description: Scans an existing codebase and builds (or rebuilds) an agent-librarian library. A script generates the documents and the code catalog; agents fill in folder roles, deepest folders first.
disable-model-invocation: true
---

# Rebuild the library (existing codebase)

`<plugin>` is the plugin root, two levels above this SKILL.md. Run every command from the project root.

## 0. Cost warning

Before starting, tell the user: this writes a role for every folder that holds code, so token cost grows with the number of such folders. In Claude Code it uses Sonnet subagents. Run `python <plugin>/scripts/librarian.py pending` after step 2 to show how many folders need a role.

## 1. Questions and dependencies

Follow steps 1–2 of `<plugin>/skills/build-library/SKILL.md` exactly. The library language is still the first question. If `.librarian/config.json` already exists, show its current values and ask only whether to change them.

## 2. Generate the mechanical parts first

```bash
python <plugin>/scripts/librarian.py init --language <answer 1> [--exclude <answer 2>...]
python <plugin>/scripts/librarian.py scaffold
python <plugin>/scripts/librarian.py index --all
```

After this, the root and every folder that holds code have a `CLAUDE.md`, and the catalog lists every definition. If the language changed, existing documents switch their generated headings to the new language, and roles and Notes already written are kept. Documents from older versions lose their generated index block, and generated `index.md` and `index/` files are removed.

## 3. Fill in roles (deepest folders first)

`python <plugin>/scripts/librarian.py pending` lists the folders whose roles are empty, deepest first. A parent can only summarize its children in one line once their roles exist, so **keep this order.**

- **If you can use subagents**:
  - Hand folders of the same depth to `folder-cataloger` agents in parallel, about 5–10 folders per agent.
  - Give each agent three things: its folder document paths, the rules file path `<plugin>/skills/rebuild-library/references/cataloger.md`, and the library language.
  - Finish one depth completely before moving to the next, shallower one.
- **If you cannot use subagents**: read `references/cataloger.md` and fill in the folders yourself, one at a time, in the same order.

## 4. Verify and report

```bash
python <plugin>/scripts/librarian.py check
```

Report to the user:
- How many documents were created
- Any remaining `role needed` entries
- Any folder depth or document length warnings (`warning`). Do not restructure folders; use the `rule-creator` skill to shorten long rules.

Then give the same wrap-up as step 5 of build-library.
