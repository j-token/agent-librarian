---
name: librarian-guide
description: Rules for the per-folder documents (CLAUDE.md/AGENTS.md) in this repository. Use when locating code, when adding, moving, or deleting files or folders, or when editing a folder document.
---

# Library rules

Every folder in this repository has a document (CLAUDE.md or AGENTS.md). Each document has three parts:

| Part | Written by | Content |
|---|---|---|
| Folder role section (e.g. `## What this folder is for`) | agent / human | What this folder is for |
| Subfolder table (e.g. `## Subfolders`) | agent / human (rows are added and removed by the script) | One line per direct subfolder describing its role |
| `<!-- librarian:index:start/end -->` block | script only | File · function · line |

The library language is set in `.librarian/config.json` (`language`). Write every role in that language.

## Rules

1. When the index tells you where something is, open that file at that line and read it. Never guess what a function does from its name in the index.
2. Never write down what a function or file does. Never edit the index marker block by hand; hooks keep the line numbers up to date.
3. When you create a folder, fill in the role section of its document and the role cell for it in the parent document's subfolder table.
4. Do not record who uses a function (reverse references). Look them up with grep or LSP instead.
5. Each piece of information lives in exactly one document. Do not repeat what a parent document says in a child document, and do not pull a child's details up into the parent.
6. If a hook or check warns that folders are nested too deep, tell the user. Do not restructure folders on your own.
