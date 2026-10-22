---
name: update-library
description: Brings an existing agent-librarian library up to date with the installed plugin version. Updates the config keys, moves the index out of folder documents into the catalog, and removes what older versions installed.
disable-model-invocation: true
---

# Update the library

`<plugin>` is the plugin root, two levels above this SKILL.md. Run every command from the project root.

This updates the library in the project. To update the plugin itself, the user runs `/plugin update` first.

## 1. Run the update

```bash
python <plugin>/scripts/librarian.py update
```

It does the following:
- Fills in missing keys in `.librarian/config.json` with their defaults, removes keys of removed features (including `docName`), and records the current plugin version in `libraryVersion`. A `maxDocLines` still at the old default of 200 becomes 60.
- Removes the generated index from every folder document, and deletes generated `index.md` and `index/` files. A hand-written `index.md` is left alone. Definitions are now looked up in the catalog (`.librarian/catalog.json`, kept out of git by `.librarian/.gitignore`), which `update` builds.
- Moves folder documents an `AGENTS.md`-mode library kept in `AGENTS.md` to `CLAUDE.md`.
- Removes what older versions installed for the `librarian-guide` rules skill: its links under `.claude/skills`, `.agents/skills`, and `.codex/skills`, and their `.gitignore` entries. A copied folder whose files differ from `.librarian/skills/librarian-guide` is left in place with a `warning`.
- Rewrites every folder document in the current format. Roles and user-written Notes are kept.

## 2. Leftovers to report, not delete

- A `warning` about `.librarian/skills/librarian-guide` or one of its copies: that folder is no longer used but may hold the user's own text.
- A `warning` that a folder "holds no code": older versions wrote documents in every folder; only folders with code are maintained now. The user may want to keep notes from it before deleting it.

Tell the user about each; do not delete them on your own.

## 3. Report

Report to the user:
- What was created, updated, or removed
- Any `role needed` entries. Offer to fill them in following `<plugin>/skills/rebuild-library/references/cataloger.md`, in the library language.
- Any folder depth or document length warnings (`warning`). Do not restructure folders; use the `rule-creator` skill for overlong working rules.
