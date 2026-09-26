---
name: library-rules
description: Turns the injection of the library rules at session start on or off, or shows whether it is on. Argument - on, off, or status.
disable-model-invocation: true
---

# Library rules at session start

`<plugin>` is the plugin root, two levels above this SKILL.md. Run the command from the project root.

When this is on (the default), a SessionStart hook adds the `librarian-guide` rules to the context at the start of every session, including after `/clear` and compaction.

## 1. Run

The argument is `on`, `off`, or `status`. If no argument was given, use `status`.

```bash
python <plugin>/scripts/librarian.py rules <on|off|status>
```

The command saves `injectRules` in `.librarian/config.json` and prints `[rules] on` or `[rules] off`.

## 2. Report

- Tell the user the current state from the output.
- If it changed, tell them it takes effect from the next session (or after `/clear`).
- If the command says `.librarian/config.json` was not found, the project has no library yet; suggest `/build-library` or `/rebuild-library`.
