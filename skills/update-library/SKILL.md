---
name: update-library
description: Brings an existing agent-librarian library up to date with the installed plugin version. Fills in new config keys, offers to update the library-rules skill, restores skill links, and reformats every folder document.
disable-model-invocation: true
---

# Update the library

`<plugin>` is the plugin root, two levels above this SKILL.md. Run every command from the project root.

This updates the library in the project. To update the plugin itself, the user runs `/plugin update` (Claude Code) first.

## 1. Run the update

```bash
python <plugin>/scripts/librarian.py update
```

It does four things:
- Fills in missing keys in `.librarian/config.json` with their defaults and records the current plugin version in `libraryVersion`.
- Compares `.librarian/skills/librarian-guide` with the plugin's version of the rules.
- Restores the skill links and the `.gitignore` entries.
- Rewrites every folder document in the current format. Roles that are already written are kept.

## 2. Rules skill differences

If the output has `[skill-diff]` lines, the project's rules skill differs from the plugin's. The user may have edited it on purpose, so do not replace it on your own.

1. Show the user the diff (`library/...` is the project's copy, `plugin/...` is the new version).
2. Ask whether to replace the project's copy with the plugin's version.
3. Only if the user agrees, run:

```bash
python <plugin>/scripts/librarian.py update --replace-skill
```

## 3. Report

Report to the user:
- What was created or updated
- Any `role needed` entries. Offer to fill them in following `<plugin>/skills/rebuild-library/references/cataloger.md`, in the library language.
- Any split recommendations (`warning`). Do not restructure folders; only pass them on to the user.
