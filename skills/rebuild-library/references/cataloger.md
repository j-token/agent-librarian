# Folder document rules (cataloger)

Follow these rules when you are assigned a folder document (`CLAUDE.md` in that folder).

Write everything in the **library language** (the `language` value in `.librarian/config.json`).

## Where you write (edit only these)

1. **The folder role section** (e.g. `## What this folder is for`): replace the placeholder (e.g. `_(to be written)_`) with 1–3 sentences stating **what this folder is for**: its responsibility and boundaries.
2. **The role cells of the subfolder table** (e.g. `## Subfolders`): read each subfolder document's role section and condense it into one line. These cells are signposts for choosing which subfolder to enter.

Keep it short. Claude Code loads this document, and every document above it, whenever a file in the folder is read.

## How to decide

- Base your judgment on the file names in the folder and on the code itself where needed. List the files with Glob and read only what you need to tell the folder's purpose.
- A subfolder's role comes from what its own document already says. Do not invent one.
- If you are not sure, write only what you have verified, e.g. "Contains the `payment` modules." Do not speculate.

## Never

- Describe what a function or file does, or list functions. Write only the role of the folder as a whole; definitions are looked up in the catalog.
- Edit the Notes section (`## Notes` or `## 메모`); it is outside this role-writing assignment.
- Change the first line (the parent link) or the rows of the subfolder table (adding, removing, reordering). The script manages the rows.
- Repeat what a parent document already says, such as restating the purpose of the whole repository in a subfolder.
- Pull a subfolder's details up into its parent. The parent's table gets a one-line summary only.
- Edit documents of folders you were not assigned.
