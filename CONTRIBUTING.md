# Contributing to agent-librarian

Thank you for helping. This guide lists the rules a change must follow before it can be merged.

By submitting a contribution, you agree that it is licensed under the [Apache License 2.0](LICENSE), the same license as this project.

## Getting started

1. Install Python 3.9 or later.
2. Install pytest for running the tests: `pip install pytest`.
3. Run the tests from the repository root:

   ```bash
   python -m pytest tests -q
   ```

To try your change in a real session, load the plugin from your checkout:

```bash
claude --plugin-dir /path/to/agent-librarian
```

## Runtime rules

- **Standard library only.** Code under `scripts/` must run on Python 3.9+ with nothing but the standard library. Do not add runtime dependencies. Keep `from __future__ import annotations` at the top of each module so newer type syntax stays 3.9-compatible.
- **Development tools are the exception.** Files under `dev/` may use extra packages (for example `tree-sitter-language-pack`), because they are never run by users.
- **Claude Code only.** The plugin ships one manifest, `.claude-plugin/plugin.json`, and Claude Code discovers `hooks/hooks.json` at its default path. When you add or change a hook:
  - Reference the plugin with `"${CLAUDE_PLUGIN_ROOT}/scripts/librarian.py"`.
  - Keep the `python3 ... || python ...` fallback, since either name may be missing.
  - Copy the command format of the existing hooks.
- **Keep hook output small.** Hook text goes into the model's context. Cap lists (see `PENDING_LIST_LIMIT`), and do not report problems the agent cannot act on.
- **Hooks never break the session.** A hook must not raise an error that stops the user's work. Catch failures, report them on stderr, and let the session continue (see `cmd_hook` in `scripts/librarian.py`).

## Library principles

These rules are the core of the project. Changes that break them will not be accepted.

- **Generated output never describes what a function or file does.** The catalog lists only file, symbol, start line and end line. Describing behavior invites wrong descriptions (hallucination).
- **Folder documents hold only what people and agents write.** Derived data (the catalog) lives under `.librarian/`, out of git and out of `CLAUDE.md`, because Claude Code loads a folder's `CLAUDE.md` and its parents' whenever it reads a file there. Query it on demand with `find`, `grep`, and `outline`.
- **The catalog must not silently miss definitions.** An agent trusts a lookup more than a grep; a definition the extractor skips is worse than no catalog. Test extractor changes on real legacy code (see Tests).
- **Roles written by people or agents are never lost.** Any change to document generation must keep existing role text.

## Language

- Write skills, agents, templates, code, and code comments in English.
- If you change the README, update both `README.md` and `README.ko.md`. If you cannot write Korean, say so in the pull request and a maintainer will translate.

## Tests

- Every change to behavior needs a test in `tests/`.
- Test through the real entry points instead of internal helpers: the CLI (`lb.main`) and the hook helper `hook()` in `tests/test_librarian.py`.
- Name each test after the situation and the expected result, for example `test_scaffold_does_not_overwrite`.
- If you change the symbol extractor (`scripts/extract.py`), run `python dev/compare.py <dir>` on real code before and after your change, and include both results in the pull request.

## Branches

- **Write branch names in English**, in lowercase words joined by hyphens.
- **Start the name with a prefix:**

  | Prefix | Use for | Example |
  |---|---|---|
  | `feat/` | a new feature | `feat/user-login` |
  | `bug/` | a bug fix | `bug/login-token-expiry` |
  | `perf/` | a performance improvement | `perf/list-query-optimization` |
  | `refactor/` | a structural change with no change in behavior | `refactor/split-auth-module` |
  | `misc/` | only for grouping small changes that fit none of the above | `misc/fix-typos` |

- Do not use any other prefix.

## Commits

- **Write commit messages in English.**
- **One change per commit.** Each commit holds exactly one piece of work with its own message, so a reviewer can look at one change at a time. If the working tree mixes unrelated changes, stage and commit them separately instead of bundling them.
- **Start the subject with a prefix:**

  | Prefix | Use for |
  |---|---|
  | `feat:` | a new feature |
  | `bug:` | a bug fix |
  | `perf:` | a performance improvement |
  | `refactor:` | a structural change with no change in behavior |
  | `misc:` | only for grouping small changes that fit none of the above |

- Do not use any other prefix.

## Pull requests

- Open pull requests against `main`.
- Keep each pull request to one topic.
- In the description, explain what changed and why, and how you tested it.
- Make sure `python -m pytest tests -q` passes before asking for review.
