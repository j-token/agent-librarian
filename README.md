# About this project

[Korean version](README.ko.md)

This plugin is inspired by libraries. It lets you organize your codebase and folder structure the way a library organizes its books.

I built it because I believe that, as AI takes over writing code, the human role shifts to managing and making use of that code.

## Why a library?

Humanity has produced, accumulated, and managed an enormous amount of knowledge.

A librarian's job is to classify and arrange countless books so that they are as easy as possible to tell apart.

That means keeping duplicate books to a minimum and grouping similar ones. Someone will eventually come looking for those books, so they also have to be easy to find.

This plugin makes AI follow the rules that humans built libraries on.

## What the library looks like

The library has two parts, like a real one: the **shelves**, where each folder says what it holds, and the **catalog**, which you query to find a particular book.

### Shelves: one `CLAUDE.md` per code folder

The root and every folder that holds code have a `CLAUDE.md`. Folders with only documents or assets get none.

```markdown
# Parent: ../CLAUDE.md

## What this folder is for
Holds the billing and invoicing code.              ← written by an agent or a human

## Notes
Amounts are stored as integer cents.              ← written by an agent or a human

## Subfolders
| Folder | Role |
|---|---|
| tax/ | Tax calculation |                         ← row kept by the script, role written by an agent or a human
```

The first thing the install commands ask is the **library language**: the language the folder documents are written in. English and Korean have built-in headings. Any other language is accepted too; the headings then stay in English and the roles are written in that language. You can change the language later by running `/rebuild-library` again. Roles that are already written are kept.

- The root subfolder table describes only top-level folders. Each other subfolder table describes only the folders directly beneath it.
- The Notes section holds context that the code alone does not explain, and folder working rules.
- Claude Code loads a folder's `CLAUDE.md`, and every `CLAUDE.md` above it, whenever it reads a file in that folder. That is why these documents stay short: `maxDocLines` (default 60) limits the human-written text, not counting subfolder table rows.

### Catalog: definitions looked up on demand

A script records every definition as `file · symbol · start line · end line` in `.librarian/catalog.json`. The catalog is derived data: it is rebuilt from the code, kept out of git by `.librarian/.gitignore`, and never written into `CLAUDE.md`. At session start, a hook tells the agent how to query it:

```text
$ python scripts/librarian.py find '^onscary$'
[src/] The platform-independent C source of the game itself.
src/monmove.c:135-182 onscary
   135	onscary(x, y, mtmp)
   136	int x, y;
   ...

$ python scripts/librarian.py outline src/pray.c
[src/] The platform-independent C source of the game itself.
src/pray.c
  102-141 critically_low_hp
  183-269 in_trouble
  ...

$ python scripts/librarian.py grep 'u\.uluck = 0' src
[src/] The platform-independent C source of the game itself.
src/pray.c:923-1228 pleased
  1117: u.uluck = 0;
src/pray.c:1327-1792 dosacrifice
  1706: u.uluck = 0;
  1740: u.uluck = 0;
  1778: u.uluck = 0;
src/pray.c:1846-1883 dopray
  1862: u.uluck = 0;
```

- When at most 3 definitions match, `find` prints their code too (up to 60 lines each), so a lookup costs one tool call instead of two; otherwise the agent reads only the reported line range instead of the whole file. **The catalog never describes what a function does**, so an AI cannot write down a wrong description of it.
- Each result carries its folder's role, so the agent gets the shelf's context without loading every document on the way.
- The catalog refreshes itself when queried: a file is parsed again only when its modification time or size changed.
- `grep` searches the code files for a regex and puts each matching line under the definition that holds it, so finding who calls a function or writes a field takes one call instead of a Grep followed by reads. Use Grep for documents and other non-code files. The design reasoning is in the [knowledge management research notes](docs/research/knowledge-management.md) (in Korean).

### Hooks

- **Session start**: injects the lookup instructions, refreshes the catalog in the background, and warns about folder documents or Markdown rule files longer than `maxDocLines`.
- **End of each turn**: creates documents for new code folders, updates subfolder tables, and asks the agent to fill in empty roles. It lists at most 10 folders at a time.

JavaScript/TypeScript catalogs also include anonymous block callbacks in `test`, `it`,
`describe`, and `test.describe` calls with literal titles, such as `test('example')`.
Entries start at the callee and end at the callback's closing brace; suites include their
nested test entries. Quoted strings and static template literals are supported, along with
`only`, `skip`, `concurrent`, and `sequential`; tests also accept `fixme`, `fail`, and
`fails`, while suites accept `serial` and `parallel`. Async arrows, anonymous functions,
and `test(title, details, callback)` are supported. Imports and aliases are not resolved:
the scanner recognizes these callee names by syntax. Dynamic titles, `each` factories,
expression callbacks, callback references, and hooks such as `beforeEach` are omitted.
C catalogs include K&R-style definitions, whose parameter declarations sit between `)` and `{`.
Python catalogs include definitions nested in functions, named `outer.inner`. In the other languages, definitions inside a function body are not cataloged; use the `grep` command for those. `find '^name$'` also matches methods, whose catalog names carry their class (`Class.name`).

Installing the library adds the following to your project:

```
.librarian/config.json      # library language, excluded paths, folder depth warning threshold (maxDepth),
                            # document line limit (maxDocLines, default 60), plugin version (libraryVersion)
.librarian/.gitignore       # keeps catalog.json out of git
.librarian/catalog.json     # derived; rebuilt automatically
<every code folder>/CLAUDE.md
```

## Rule-creator skill

The `rule-creator` skill records a rule or a piece of missing context when a mistake is likely to recur. It finds the general situation behind a specific example, checks for an existing rule, and writes one actionable instruction with its reason. It places the rule in the narrowest spot Claude Code still loads when the rule matters: root or folder `CLAUDE.md` Notes, or `.claude/rules/` with optional `paths` frontmatter. When a document grows past `maxDocLines`, it groups and moves rules by topic; the script only warns and never rewrites human rules.

## Requirements

- Claude Code.
- Python 3.9 or later. Nothing else to install: the catalog is built with the Python standard library only.
- Supported languages: Python, JavaScript/TypeScript/TSX, Go, Rust, Java, C/C++ (including K&R C), C#, CSS. `outline` also lists the headings of a Markdown file.

## Instructions for humans

### Install

You only need Python 3.9 or later. Run these inside Claude Code, then run `/reload-plugins`.

```
/plugin marketplace add j-token/agent-librarian
/plugin install agent-librarian@agent-librarian
```

You can also do the same from a terminal:

```bash
claude plugin marketplace add j-token/agent-librarian
claude plugin install agent-librarian@agent-librarian
```

Once the plugin is installed, build your "library" with one of the commands below.

### If you have an existing codebase

> Warning! This command runs the plugin's Sonnet agents to write a role for every folder that holds code. This may incur additional charges, so please be careful!

1. Enter the following command.

    `/rebuild-library`

2. Answer the questions it asks, starting with the library language.

3. Check that the folder roles written in each CLAUDE.md look right to you.

### If you are starting without a codebase

1. Enter the following command.

    `/build-library`

2. Answer the questions it asks, starting with the library language.

3. Check the root CLAUDE.md and the settings in `.librarian/config.json`.

### After updating the plugin

Use `/plugin update agent-librarian@agent-librarian`, then reload the plugins or restart Claude Code.

Updating the plugin does not change a library that already exists. Run `/update-library` after updating the plugin; the end-of-turn hook also reminds you if the library was built with an older version. The skill updates the config keys, rewrites every folder document in the current format while keeping the roles you wrote, and builds the catalog.

Upgrading from 0.6 or earlier: the generated index leaves every `CLAUDE.md`, and generated `index.md` and `index/` files are deleted; definitions move to the catalog. Folder documents kept in `AGENTS.md` move to `CLAUDE.md`. Documents older versions wrote in folders without code are reported, not deleted. Libraries built with older versions also had a rules skill (`librarian-guide`); `/update-library` removes its links and `.gitignore` entries, and tells you to delete `.librarian/skills/librarian-guide` yourself once you have kept anything you added there.

## Instructions for agents

This section is for AI agents asked to install or use this plugin for a user.

### Installing for a user

1. Check that `python --version` reports 3.9 or later. If Python is missing, ask the user to install it; the plugin has no other dependencies.
2. Install the plugin with the `claude plugin …` terminal commands from "Install" above.
3. Some steps need the user and you cannot do them yourself. Ask the user to:
   - run `/reload-plugins`;
   - run `/rebuild-library` (existing codebase) or `/build-library` (new project). These skills cannot be invoked by a model, and they ask the user questions such as the library language.
4. Tell the user that `/rebuild-library` costs tokens in proportion to the number of folders that hold code.

### Working in a project that has a library

A project has a library if `.librarian/config.json` exists at its root. The hooks tell you when something needs your attention. The essentials:

- To find a definition by name, use the `find` command from the session-start instructions; to see what a file or folder defines, use `outline`. Then read the indicated range. Never infer what a function does from its name.
- Use the `grep` command for call sites, field writes, and strings in code: it shows the function holding each match. Use Grep for other files. Reverse references are not recorded anywhere.
- Never write what a function or file does in a document, and never edit `.librarian/catalog.json`.
- When you create a code folder, fill in its role section and its role cell in the parent's subfolder table, in the library language (`language` in `.librarian/config.json`). If the end-of-turn hook asks you to fill in empty roles, read the code and write about the folder's role only.
- If a hook warns that folders are nested too deep, tell the user. Do not restructure folders on your own.
- If a hook warns that human-written document text is too long, use `rule-creator` to shorten and group it while preserving each rule's scope.
- If the end-of-turn hook says the library was built with an older plugin version, ask the user to run `/update-library`. It cannot be invoked by a model.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[Apache License 2.0](LICENSE)
