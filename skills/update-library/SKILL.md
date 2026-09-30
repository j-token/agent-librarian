---
name: update-library
description: Brings an existing agent-librarian library up to date with the installed plugin version. Updates the config keys, removes the rules skill links older versions installed, and reformats every folder document.
disable-model-invocation: true
---

# Update the library

`<plugin>` is the plugin root, two levels above this SKILL.md. Run every command from the project root.

This updates the library in the project. To update the plugin itself, the user runs `/plugin update` (Claude Code) first.

## 1. Run the update

```bash
python <plugin>/scripts/librarian.py update
```

It does three things:
- Fills in missing keys in `.librarian/config.json` with their defaults (including `maxDocLines`, default 200), removes keys of removed features, and records the current plugin version in `libraryVersion`.
- Removes what older versions installed for the `librarian-guide` rules skill: its links under `.claude/skills`, `.agents/skills`, and `.codex/skills` (and those folders when they end up empty), and their `.gitignore` entries. A copied folder there whose files differ from `.librarian/skills/librarian-guide` is left in place with a `warning`.
- Rewrites every folder document in the current format. Roles and user-written Notes are kept, a Notes heading is added where missing, and the old one-line pointer to the rules skill is removed from the root document. Long generated indexes move to `index.md` and, if needed, per-file indexes in `index/`; they move back when the index shrinks. The configured `CLAUDE.md`, `AGENTS.md`, or `both` document mode is kept.

## 2. Leftover rules skill folder

If the output has a `warning` about `.librarian/skills/librarian-guide` or one of its copies, that folder is no longer used but was left in place, because the user may have added their own text to it. Tell the user; do not delete it on your own.

## 3. Report

Report to the user:
- What was created or updated
- Any `role needed` entries. Offer to fill them in following `<plugin>/skills/rebuild-library/references/cataloger.md`, in the library language.
- Any folder depth or document length warnings (`warning`). Do not restructure folders; use the `rule-creator` skill for overlong working rules, keeping non-Claude and shared rules in root `AGENTS.md`.
