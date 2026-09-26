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
- **Support both Claude Code and Codex.** The plugin follows the [Agent Plugins](https://agent-plugins.org/) layout and runs on both agents. When you add or change a hook in `hooks/hooks.json`:
  - Read the plugin root from `CLAUDE_PLUGIN_ROOT` or `PLUGIN_ROOT`.
  - Keep the `python3 ... || python ...` fallback, since either name may be missing.
  - Copy the command format of the existing hooks.
- **Hooks never break the session.** A hook must not raise an error that stops the user's work. Catch failures, report them on stderr, and let the session continue (see `cmd_hook` in `scripts/librarian.py`).

## Library principles

These rules are the core of the project. Changes that break them will not be accepted.

- **Generated documents never describe what a function or file does.** The index lists only file, function, start line and end line. Describing behavior invites wrong descriptions (hallucination).
- **Only the script writes the index block.** Nothing else may edit the content between `<!-- librarian:index:start -->` and `<!-- librarian:index:end -->`.
- **Roles written by people or agents are never lost.** Any change to document generation must keep existing role text.

## Language

- Write skills, agents, templates, code, and code comments in English.
- If you change the README, update both `README.md` and `README.ko.md`. If you cannot write Korean, say so in the pull request and a maintainer will translate.

## Tests

- Every change to behavior needs a test in `tests/`.
- Test through the real entry points instead of internal helpers: the CLI (`lb.main`) and the hook helper `hook()` in `tests/test_librarian.py`.
- Name each test after the situation and the expected result, for example `test_rules_off_changes_only_its_own_key`.
- If you change the symbol extractor (`scripts/extract.py`), run `python dev/compare.py <dir>` on real code before and after your change, and include both results in the pull request.

## Commits

- **One change per commit.** Do not mix unrelated changes; split them into separate commits.
- **Start the subject with a prefix:**

  | Prefix | Use for |
  |---|---|
  | `feat:` | a new feature |
  | `bug:` | a bug fix |
  | `perf:` | a performance improvement |
  | `refactor:` | a structural change with no change in behavior |
  | `misc:` | small changes that fit none of the above |

- Write the message in English or Korean.

## Pull requests

- Open pull requests against `main`.
- Keep each pull request to one topic.
- In the description, explain what changed and why, and how you tested it.
- Make sure `python -m pytest tests -q` passes before asking for review.
