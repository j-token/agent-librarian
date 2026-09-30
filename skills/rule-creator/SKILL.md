---
name: rule-creator
description: Record a reusable project rule or missing context where the relevant agent will find it. Use when the user says to remember a constraint, prevent a recurring mistake, or follow an instruction whenever a kind of work is done.
---

# Create or revise a rule

`<plugin>` is the plugin root, two levels above this SKILL.md. Run librarian commands from the project root.

## 1. Find the rule behind the example

Identify the situation, the required action, and why it matters. A request may name the file or mistake that prompted it; cover the other cases with the same cause without widening the rule beyond the user's intent. State it as "when doing this kind of work, do this". Keep the original case as a short example only when it helps someone apply the rule.

Read existing instructions before writing. Revise an existing rule when it already covers the case, and move a rule when its current location gives it the wrong scope. Avoid two copies of the same instruction: they can disagree later. If the reason or intended scope cannot be determined from the request and project, ask the user instead of inventing it.

## 2. Identify the document mode and scope

Read `.librarian/config.json` if it exists. Its `docName` chooses the managed folder document:

| `docName` | Managed folder document |
| --- | --- |
| `CLAUDE.md` | `CLAUDE.md` |
| `AGENTS.md` | `AGENTS.md` |
| `both` | `AGENTS.md`; the matching `CLAUDE.md` is only an `@AGENTS.md` alias |

If the library is not installed, inspect the project's existing instruction files and the agent the user uses before choosing a file. Do not create a `.librarian` configuration merely to record a rule.

First decide who must follow the rule:

| Audience and content | Place |
| --- | --- |
| Codex, another non-Claude agent, or both Claude Code and non-Claude agents | Notes in the project-root `AGENTS.md`. State any folder, file, or command scope in the rule body. |
| Claude Code only, needed for every task or one topic | Root `CLAUDE.md` Notes in `CLAUDE.md` mode, or `.claude/rules/<topic>.md` without `paths` |
| Claude Code only, for one folder | Notes in that folder's `CLAUDE.md` in `CLAUDE.md` mode, or a `.claude/rules/<topic>.md` file with `paths` |
| Claude Code only, for matching paths | `.claude/rules/<topic>.md` with `paths` frontmatter |
| Claude Code only, for a command | The existing document or `SKILL.md` that explains the command |
| A folder's responsibility rather than a working rule | The role section of its managed folder document |

For a non-Claude or shared rule, keep the actionable instruction in the **root** `AGENTS.md` even when it applies to one file, folder, or command. State that scope explicitly, for example "When editing `src/api/**/*.ts`, ...". Do not put its only copy in a nested folder document, `.claude/rules/`, or a new agent-specific rules directory. In `both` mode, edit root `AGENTS.md` and leave its generated `CLAUDE.md` alias alone. `.claude/rules/` and its `paths` frontmatter are Claude Code features, not a Codex rule mechanism.

If `docName` is `CLAUDE.md` but the user needs a non-Claude rule, use or create a standalone root `AGENTS.md` without changing `docName` or overwriting the existing document. If the rule needs a long procedure, put the core action and an explicit instruction to read the relevant ordinary document in root `AGENTS.md`; keep the procedure in that document.

## 3. Inspect and edit the chosen location

Read root `AGENTS.md` and `CLAUDE.md` when present, the target folder's managed document, relevant command documentation, and existing files under `.claude/rules/` (including subfolders). Search before adding a new topic file or root rule.

For a non-Claude or shared rule, write under the root `AGENTS.md` Notes heading: `## Notes` for `language: en`, `## 메모` for `language: ko`, or `## Notes` for other library languages. If the file is unmanaged and has no Notes section, add one while preserving its existing content. For a Claude-only folder rule, use the same Notes heading in that folder's `CLAUDE.md` when the document mode is `CLAUDE.md`. Write the body in the configured library language, or in the user's language when there is no library. Keep working rules out of the role section, whose job is to summarize the folder's responsibility.

If a Claude-only folder document is missing from an installed `CLAUDE.md` library, run `python <plugin>/scripts/librarian.py scaffold`. If a managed Notes heading is missing because the library is old, add it between the role and subfolder sections. Do not change the configured document mode while recording a rule. In `both` mode, edit root `AGENTS.md`, never its generated `CLAUDE.md` alias.

Never edit the `<!-- librarian:index:start -->` through `<!-- librarian:index:end -->` block, a generated `index.md`, or files in the generated `index/` folder. The librarian rewrites those indexes.

For a Claude-only path rule, name the file after its topic in English kebab-case and use valid YAML frontmatter, for example:

```markdown
---
paths:
  - 'src/api/**/*.ts'
  - 'config/api.json'
---

# API requests

...
```

Claude Code's `paths` patterns are relative to the project root and load when it reads a matching file. A create, edit, or delete operation without a preceding matching read is not guaranteed to load the rule. Invalid or absent `paths` makes the rule global, so check the frontmatter and scope. See [Claude Code's memory documentation](https://code.claude.com/docs/en/memory).

Write a rule as a checkable action with a brief reason and a path to the relevant code or document. Record hidden constraints, pitfalls, and decisions; do not repeat a function list or guess what code does from its name. When moving text, replace it in the old place with a short pointer instead of keeping a second copy.

## 4. Keep documents within the line limit

Use `maxDocLines` from `.librarian/config.json` (default 200). The limit applies to root `AGENTS.md` and other managed folder-document prose (excluding generated index blocks), plus Markdown rule files under `.claude/rules/`. The `SessionStart` hook and `python <plugin>/scripts/librarian.py check` report overlong documents. Keep documents concise, but do not delete or weaken an operative rule just to fit the limit.

Split by topic and scope when a document is over the limit or would become so:

1. Group rules that apply to the same class of work. Do not cut at an arbitrary line or create one file per rule.
2. For Claude-only rules, move each group to the appropriate folder Notes, command document, or `.claude/rules/` file. Preserve its path scope.
3. For non-Claude or shared rules, keep the core action in root `AGENTS.md`: condense wording, group related cases, and remove duplicates. Move lengthy background or procedures to ordinary documentation only when the root rule explicitly tells the agent when to read it. Do not move the only operative instruction to a nested folder or agent-specific rules directory.
4. Leave a short pointer wherever details were moved and update other pointers that name the old location. Remove the old full text. Do not move or edit generated indexes; the librarian splits and rejoins them automatically.
5. Run `python <plugin>/scripts/librarian.py check`. If a warning remains because the rule cannot be shortened safely, report that limit and preserve the full requirement in root `AGENTS.md`.

## 5. Verify and report

Run the project's Markdown formatter or linter when one is configured, then run `python <plugin>/scripts/librarian.py check` for an installed library. Report the file and audience of the rule, how the example became a general rule, and any topics moved during a split. For a Claude-only rule, verify its loading against a matching file in Claude Code; `check` validates the library's documents and length, not the host's instruction-loading behavior.
