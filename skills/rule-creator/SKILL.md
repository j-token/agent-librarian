---
name: rule-creator
description: Record a reusable project rule or missing context where Claude Code will find it. Use when the user says to remember a constraint, prevent a recurring mistake, or follow an instruction whenever a kind of work is done.
---

# Create or revise a rule

`<plugin>` is the plugin root, two levels above this SKILL.md. Run librarian commands from the project root.

## 1. Find the rule behind the example

Identify the situation, the required action, and why it matters. A request may name the file or mistake that prompted it; cover the other cases with the same cause without widening the rule beyond the user's intent. State it as "when doing this kind of work, do this". Keep the original case as a short example only when it helps someone apply the rule.

Read existing instructions before writing: the root and target folder `CLAUDE.md`, files under `.claude/rules/` (including subfolders), and any document that explains the command involved. Revise an existing rule when it already covers the case, and move a rule when its current location gives it the wrong scope. Avoid two copies of the same instruction: they can disagree later. If the reason or intended scope cannot be determined from the request and project, ask the user instead of inventing it.

## 2. Choose the place by scope

| Scope | Place |
| --- | --- |
| Every task in the project | Notes of the root `CLAUDE.md`, or `.claude/rules/<topic>.md` without `paths` |
| One folder | Notes of that folder's `CLAUDE.md` |
| Files matching a pattern across folders | `.claude/rules/<topic>.md` with `paths` frontmatter |
| One command | The document or `SKILL.md` that explains the command |
| A folder's responsibility rather than a working rule | The role section of that folder's `CLAUDE.md` |

Claude Code loads a folder's `CLAUDE.md`, and those of its parent folders, when it reads a file there. Root notes cost context in every session, so prefer the narrowest place that is still loaded when the rule matters.

The Notes heading is `## Notes` for `language: en` and other languages, or `## 메모` for `language: ko` (see `.librarian/config.json`). Write the body in the library language, or in the user's language when there is no library. If the library is not installed, use the project's existing `CLAUDE.md` or `.claude/rules/`; do not create a `.librarian` configuration merely to record a rule. If a folder document is missing from an installed library, run `python <plugin>/scripts/librarian.py scaffold`.

For a path rule, name the file after its topic in English kebab-case and use valid YAML frontmatter:

```markdown
---
paths:
  - 'src/api/**/*.ts'
  - 'config/api.json'
---

# API requests

...
```

`paths` patterns are relative to the project root and load when Claude reads a matching file. A create, edit, or delete without a preceding matching read is not guaranteed to load the rule. Invalid or absent `paths` makes the rule global, so check the frontmatter. See [Claude Code's memory documentation](https://code.claude.com/docs/en/memory).

## 3. Write the rule

Write a rule as a checkable action with a brief reason and a path to the relevant code or document. Record hidden constraints, pitfalls, and decisions; do not list functions or guess what code does from its name. Keep working rules out of the role section. When moving text, replace it in the old place with a short pointer instead of keeping a second copy.

## 4. Keep documents within the line limit

`maxDocLines` in `.librarian/config.json` (default 60) applies to the human-written text of folder documents (subfolder table rows excluded) and to Markdown files under `.claude/rules/`. The `SessionStart` hook and `python <plugin>/scripts/librarian.py check` report overlong documents. Do not delete or weaken an operative rule just to fit the limit. When a document is over the limit:

1. Group rules that apply to the same class of work. Do not cut at an arbitrary line or create one file per rule.
2. Move each group to the narrowest place in the table above, preserving its scope.
3. Leave a short pointer where details were moved, update other pointers that named the old location, and remove the old full text.
4. Run `python <plugin>/scripts/librarian.py check`. If a warning remains because the rule cannot be shortened safely, report that.

## 5. Verify and report

Run the project's Markdown formatter or linter when one is configured, then `python <plugin>/scripts/librarian.py check` for an installed library. Report the file and scope of the rule, how the example became a general rule, and any topics moved during a split.
