"""Dependency-free symbol extractor for agent-librarian.

extract_symbols(path) returns [(name, start_line, end_line)] with 1-based, inclusive lines.
The start line is the line that holds the declaration's name; the end line is the last line
of the declaration. Methods are prefixed with their container ("Class.method").

- Python uses the standard `ast` module (end line: the node's end_lineno).
- Brace languages (JS/TS, Go, Rust, Java, C#, C, C++) use a small scanner: comments and
  string literals are blanked out (newlines kept, so offsets and lines stay valid), the
  remaining text is tokenized, and declarations are recognized statement by statement
  while a scope stack tracks braces. A declaration with a body ends at the line of the `}`
  that closes it (the last line of the file when it is never closed); a declaration without
  a body ends at its terminating `;`, or at its last token when nothing terminates it.
"""
from __future__ import annotations

import ast
import re
import warnings
from bisect import bisect_right
from pathlib import Path

EXT_LANG = {
    ".py": "python",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript", ".jsx": "javascript",
    ".ts": "typescript", ".mts": "typescript", ".cts": "typescript",
    ".tsx": "tsx",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".c": "c", ".h": "c",
    ".cc": "cpp", ".cpp": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp", ".hxx": "cpp",
    ".cs": "csharp",
}
JS_LANGS = {"javascript", "typescript", "tsx"}
_CPP_HINT = re.compile(r"^\s*(?:namespace\s+\w|class\s+\w+\s*[:{]|template\s*<)|\w::\w", re.MULTILINE)


def language_of(path: Path, text: str) -> str | None:
    lang = EXT_LANG.get(path.suffix.lower())
    if lang == "c" and path.suffix.lower() == ".h" and _CPP_HINT.search(_Masker(text, "c").run()):
        return "cpp"  # a C++ header with the .h extension
    return lang


def extract_symbols(path: Path) -> list[tuple[str, int, int]]:
    if path.suffix.lower() not in EXT_LANG:
        return []
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    return extract_text(text, language_of(path, text))


def extract_text(text: str, lang: str) -> list[tuple[str, int, int]]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if text.startswith("\ufeff"):
        text = text[1:]
    if lang == "python":
        return _python(text)
    if lang in ("c", "cpp", "csharp"):
        text = _first_branch_only(text, lang)
    return _Scanner(text, lang).run()


_PP_DIRECTIVE = re.compile(r"[ \t]*#[ \t]*(\w+)")


def _first_branch_only(text: str, lang: str) -> str:
    """Blank the #elif/#else branches of a preprocessor conditional when its branches do not
    each balance their braces (lengths are kept).

    `#ifdef X / if (a) { / #else / if (b) { / #endif` repeats an opening line: keeping only the
    first branch keeps the braces balanced. When every branch is balanced (for example two
    complete implementations of a function), all branches are kept.
    """
    lines = text.split("\n")
    masked = _Masker(text, lang).run().split("\n")  # same line layout, literals blanked
    stack: list[dict] = []  # per open #if: branch start lines and net braces per branch
    blank: list[tuple[int, int]] = []
    for k, line in enumerate(lines):
        m = _PP_DIRECTIVE.match(line)
        word = m.group(1) if m else None
        if word in ("if", "ifdef", "ifndef"):
            stack.append({"starts": [k + 1], "nets": [0]})
        elif word in ("elif", "else", "elifdef", "elifndef") and stack:
            stack[-1]["starts"].append(k + 1)
            stack[-1]["nets"].append(0)
        elif word == "endif" and stack:
            frame = stack.pop()
            if any(frame["nets"]) and len(frame["starts"]) > 1:
                blank.append((frame["starts"][1] - 1, k))  # from the first #elif/#else line
            if stack:
                stack[-1]["nets"][-1] += frame["nets"][0]  # only the first branch counts
        elif not m and stack:
            stack[-1]["nets"][-1] += masked[k].count("{") - masked[k].count("}")
    for a, b in blank:
        for k in range(a, b):
            if not _PP_DIRECTIVE.match(lines[k]):
                lines[k] = " " * len(lines[k])
    return "\n".join(lines)


# ---------------------------------------------------------------- Python


def _python(text: str) -> list[tuple[str, int, int]]:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tree = ast.parse(text)
    except (RecursionError, MemoryError) as exc:
        raise SyntaxError(f"too deeply nested to parse ({type(exc).__name__})") from None
    lines = text.split("\n")
    out: list[tuple[str, int, int]] = []

    def name_line(node) -> int:
        # `def \` + newline + `name():` puts the name on a later line
        ln = node.lineno
        while ln < len(lines) and lines[ln - 1].rstrip().endswith("\\") and not re.search(
                r"\b(?:def|class)\s+\w", lines[ln - 1]):
            ln += 1
        return ln

    def visit(body, scope: list[str]) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out.append((".".join(scope + [node.name]), name_line(node), node.end_lineno))
            elif isinstance(node, ast.ClassDef):
                out.append((".".join(scope + [node.name]), name_line(node), node.end_lineno))
                visit(node.body, scope + [node.name])
            else:
                # descend into if/try/with/for/while/match blocks in source order,
                # never into functions
                visit(getattr(node, "body", None) or [], scope)
                for handler in getattr(node, "handlers", None) or []:
                    visit(handler.body, scope)
                for case in getattr(node, "cases", None) or []:
                    visit(case.body, scope)
                for field in ("orelse", "finalbody"):
                    visit(getattr(node, field, None) or [], scope)

    visit(tree.body, [])
    return out


# ---------------------------------------------------------------- masking

def _mark_class() -> str:
    """Combining marks (Mn/Mc) in the BMP plus ZWNJ/ZWJ: valid in identifiers, not in \\w."""
    import unicodedata
    parts, start, prev = [], None, None
    for cp in range(0x300, 0x10000):
        if unicodedata.category(chr(cp)) in ("Mn", "Mc"):
            if start is None:
                start = cp
            prev = cp
        elif start is not None:
            parts.append(chr(start) if start == prev else f"{chr(start)}-{chr(prev)}")
            start = None
    return "".join(parts) + "\u200c\u200d"


_ID_CONT = r"\w$" + _mark_class()
_IDENT_CHAR = re.compile(f"[{_ID_CONT}]")
_RUST_RAW = re.compile(r'(?:br|r|cr)(#*)"')
_RUST_CHAR = re.compile(r"b?'(?:\\(?:x[0-9a-fA-F]{2}|u\{[0-9a-fA-F]{1,6}\}|.)|[^\\'\n])'")
_CPP_RAW = re.compile(r'(?:u8|[uUL])?R"([^()\\\s"]{0,16})\(')
_JS_REGEX_PREV_WORDS = {"return", "typeof", "case", "do", "else", "in", "of", "new", "delete",
                        "void", "throw", "instanceof", "yield", "await"}
_JS_REGEX_PREV_CHARS = set("(,=:[!&|?{;+-*%~^")  # not "}": `x={1} />` in JSX


class _Masker:
    """Blank out comments and literals. Output has the same length as the input."""

    def __init__(self, text: str, lang: str):
        self.t = text
        self.n = len(text)
        self.lang = lang
        self.out = list(text)
        self.literals: list[int] = []  # start offsets of masked literals (not comments)
        self.comments: list[tuple[int, int]] = []  # (start, end) of comments

    def blank(self, a: int, b: int) -> None:
        out = self.out
        for k in range(a, min(b, self.n)):
            if out[k] != "\n":
                out[k] = " "

    def line_end(self, i: int) -> int:
        """End of the line at i, following `\\` line continuations."""
        t, n = self.t, self.n
        j = i
        while True:
            end = t.find("\n", j)
            if end < 0:
                return n
            if end > 0 and t[end - 1] == "\\":
                j = end + 1
                continue
            return end

    def open_comment_on_line(self, i: int, j: int) -> int | None:
        """Start of a `/*` in t[i:j] (outside quotes) that is still open at j, if any."""
        t = self.t
        k, opened = i, None
        while k < j:
            c = t[k]
            if opened is None and c in "\"'":
                end = t.find(c, k + 1, j)
                while end > 0 and t[end - 1] == "\\":
                    end = t.find(c, end + 1, j)
                k = j if end < 0 else end + 1
                continue
            if opened is None and t.startswith("//", k):
                return None
            if t.startswith("/*", k) and opened is None:
                opened = k
                k += 2
                continue
            if t.startswith("*/", k) and opened is not None:
                opened = None
                k += 2
                continue
            k += 1
        return opened

    def in_number(self, i: int) -> bool:
        k = i
        while k > 0 and (self.t[k - 1].isalnum() or self.t[k - 1] in "'._"):
            k -= 1
        return self.t[k].isdigit()

    def ident_before(self, i: int) -> bool:
        return i > 0 and bool(_IDENT_CHAR.match(self.t[i - 1]))

    # -- literal scanners: each returns the index just past the literal

    def quoted(self, i: int, q: str, multiline: bool, escapes: bool = True) -> int:
        t, n = self.t, self.n
        j = i + 1
        while j < n:
            c = t[j]
            if c == "\\" and escapes:
                j += 2
                continue
            if c == q:
                return j + 1
            if c == "\n" and not multiline:
                return j
            j += 1
        return n

    def block_comment(self, i: int) -> int:
        t = self.t
        if self.lang != "rust":
            end = t.find("*/", i + 2)
            return self.n if end < 0 else end + 2
        depth, j = 0, i
        while j < self.n:
            if t.startswith("/*", j):
                depth += 1
                j += 2
            elif t.startswith("*/", j):
                depth -= 1
                j += 2
                if depth == 0:
                    return j
            else:
                j += 1
        return self.n

    def js_template(self, i: int) -> int:
        """Template literal starting at i, including nested ${ `...` } holes (iterative)."""
        t, n = self.t, self.n
        stack: list = [None]  # None: template text; [depth, prev]: code inside ${ }
        j = i + 1
        while j < n and stack:
            top = stack[-1]
            c = t[j]
            if top is None:
                if c == "\\":
                    j += 2
                elif c == "`":
                    stack.pop()
                    j += 1
                elif c == "$" and j + 1 < n and t[j + 1] == "{":
                    stack.append([1, "("])
                    j += 2
                else:
                    j += 1
                continue
            if c in "\"'":
                j = self.quoted(j, c, multiline=False)
                top[1] = "a"
            elif c == "`":
                stack.append(None)
                j += 1
            elif t.startswith("//", j):
                end = t.find("\n", j)
                j = n if end < 0 else end
            elif t.startswith("/*", j):
                j = self.block_comment(j)
            elif c == "/" and top[1] in _JS_REGEX_PREV_CHARS:
                end = self.js_regex(j)
                j, top[1] = (j + 1, "/") if end is None else (end, "a")
            elif c == "{":
                top[0] += 1
                top[1] = "{"
                j += 1
            elif c == "}":
                top[0] -= 1
                j += 1
                if top[0] == 0:
                    stack.pop()
                else:
                    top[1] = "}"
            elif c in " \t\n":
                j += 1
            else:
                top[1] = "=" if c == ">" and t[j - 1] == "=" else ("a" if _IDENT_CHAR.match(c) else c)
                j += 1
        return n if stack else j

    def js_regex(self, i: int) -> int | None:
        t, n = self.t, self.n
        j, in_class = i + 1, False
        while j < n:
            c = t[j]
            if c == "\n":
                return None
            if c == "\\":
                j += 2
                continue
            if c == "[":
                in_class = True
            elif c == "]":
                in_class = False
            elif c == "/" and not in_class:
                j += 1
                while j < n and (t[j].isalpha()):
                    j += 1
                return j
            j += 1
        return None

    def cs_open(self, j: int):
        """At a C# string start (prefix + quote): ("raw", end) or ("str", after_quote, interp, verbatim)."""
        t, n = self.t, self.n
        interp = verbatim = False
        while j < n and t[j] in "$@":
            interp |= t[j] == "$"
            verbatim |= t[j] == "@"
            j += 1
        if not verbatim and t.startswith('"""', j):  # raw literal: closes with the same run of quotes
            k = j
            while k < n and t[k] == '"':
                k += 1
            end = t.find('"' * (k - j), k)
            return ("raw", n if end < 0 else end + (k - j))
        return ("str", j + 1, interp, verbatim)

    def cs_string(self, i: int) -> int:
        """C# string starting at i, with nested interpolation holes (iterative)."""
        t, n = self.t, self.n
        first = self.cs_open(i)
        if first[0] == "raw":
            return first[1]
        stack: list = [["s", first[2], first[3]]]  # ["s", interp, verbatim] or ["h", depth]
        j = first[1]
        while j < n and stack:
            top = stack[-1]
            c = t[j]
            nxt = t[j + 1] if j + 1 < n else ""
            if top[0] == "s":
                interp, verbatim = top[1], top[2]
                if c == "\\" and not verbatim:
                    j += 2
                elif c == '"':
                    if verbatim and nxt == '"':
                        j += 2
                    else:
                        stack.pop()
                        j += 1
                elif c == "\n" and not verbatim:
                    stack.pop()  # unterminated: the string ends at the line end
                elif interp and c == "{":
                    if nxt == "{":
                        j += 2
                    else:
                        stack.append(["h", 1])
                        j += 1
                else:
                    j += 1
                continue
            if c == '"' or (c in "$@" and nxt and nxt in '"$@'):
                opened = self.cs_open(j)
                if opened[0] == "raw":
                    j = opened[1]
                else:
                    stack.append(["s", opened[2], opened[3]])
                    j = opened[1]
            elif c == "'":
                j = self.quoted(j, "'", multiline=False)
            elif c == "/" and nxt == "/":
                end = t.find("\n", j)
                j = n if end < 0 else end
            elif c == "/" and nxt == "*":
                j = self.block_comment(j)
            elif c == "{":
                top[1] += 1
                j += 1
            elif c == "}":
                top[1] -= 1
                j += 1
                if top[1] == 0:
                    stack.pop()
            else:
                j += 1
        return n if stack else j

    def run(self) -> str:
        t, n, lang = self.t, self.n, self.lang
        js = lang in JS_LANGS
        c_like = lang in ("c", "cpp", "csharp")
        at_line_start = True
        prev_sig, prev_word = "", ""
        i = 0
        while i < n:
            c = t[i]
            if c == "\n":
                at_line_start = True
                i += 1
                continue
            if c in " \t\f\v":
                i += 1
                continue
            if c == "#" and c_like and at_line_start:
                j = self.line_end(i)
                # a block comment opened on the directive line may run past it
                opened = self.open_comment_on_line(i, j)
                if opened is not None:
                    j = self.block_comment(opened)
                self.blank(i, j)
                i = j
                continue
            if c == "#" and lang == "rust" and i == 0 and t.startswith("#!") and not t.startswith("#!["):
                j = self.line_end(i)  # shebang
                self.blank(i, j)
                i = j
                continue
            at_line_start = False
            nxt = t[i + 1] if i + 1 < n else ""
            j = None
            if c == "/" and nxt == "/":
                # in C/C++ a line comment ending with `\` continues on the next line
                j = self.line_end(i) if lang in ("c", "cpp") else (
                    n if t.find("\n", i) < 0 else t.find("\n", i))
            elif c == "/" and nxt == "*":
                j = self.block_comment(i)
            elif lang == "rust" and c in "brc" and not self.ident_before(i) and _RUST_RAW.match(t, i):
                m = _RUST_RAW.match(t, i)
                close = '"' + m.group(1)
                end = t.find(close, m.end())
                j = n if end < 0 else end + len(close)
            elif lang == "cpp" and c in "uULR" and not self.ident_before(i) and _CPP_RAW.match(t, i):
                m = _CPP_RAW.match(t, i)
                close = ")" + m.group(1) + '"'
                end = t.find(close, m.end())
                j = n if end < 0 else end + len(close)
            elif lang == "csharp" and (c == '"' or (c in "$@" and nxt in '"$@')):
                j = self.cs_string(i)
            elif c == '"':
                if lang == "java" and t.startswith('"""', i):
                    j = i + 3
                    while j < n and not t.startswith('"""', j):
                        j += 2 if t[j] == "\\" else 1
                    j = min(n, j + 3)
                else:
                    j = self.quoted(i, '"', multiline=(lang == "rust"))
            elif c == "'":
                if lang == "rust":
                    m = _RUST_CHAR.match(t, i)
                    j = m.end() if m else None  # otherwise a lifetime: leave it
                elif lang == "cpp" and i > 0 and t[i - 1].isalnum() and self.in_number(i):
                    j = None  # digit separator 1'000
                else:
                    j = self.quoted(i, "'", multiline=False)
            elif c == "`" and js:
                j = self.js_template(i)
            elif c == "`" and lang == "go":
                end = t.find("`", i + 1)
                j = n if end < 0 else end + 1
            elif c == "/" and js and (prev_sig in _JS_REGEX_PREV_CHARS or prev_sig == ""
                                      or (prev_sig == "w" and prev_word in _JS_REGEX_PREV_WORDS)):
                j = self.js_regex(i)
            if j is not None:
                self.blank(i, j)
                if c != "/" or nxt not in "/*":
                    self.literals.append(i)
                else:
                    self.comments.append((i, j))
                i = j
                prev_sig, prev_word = "a", ""  # a literal is an operand
                continue
            if _IDENT_CHAR.match(c):
                k = i + 1
                while k < n and _IDENT_CHAR.match(t[k]):
                    k += 1
                prev_sig, prev_word = "w", t[i:k]
                i = k
                continue
            # `=>` counts as "=" so that a regex may follow an arrow
            prev_sig, prev_word = ("=" if c == ">" and i > 0 and t[i - 1] == "=" else c), ""
            i += 1
        return "".join(self.out)


# ---------------------------------------------------------------- scanning

_TOKEN = re.compile(r"r#[^\W\d][" + _ID_CONT + r"]*|(?:[^\W\d]|\$)[" + _ID_CONT
                    + r"]*|\d[\w.]*|=>|::|->|\S")
_IDENT = re.compile(r"(?:r#)?(?:[^\W\d]|\$)[" + _ID_CONT + r"]*")


def _is_ident(s: str) -> bool:
    return bool(_IDENT.fullmatch(s))


class _Scope:
    __slots__ = ("kind", "name", "ctype", "nest", "saved", "symbol_index", "eff", "prefix",
                 "cont")

    def __init__(self, kind: str, parent: "_Scope | None" = None, name: str | None = None,
                 ctype: str = "", saved=None, symbol_index: int | None = None):
        self.kind = kind          # file, container, transparent, func, opaque, inline, gotypes, jsobject
        self.name = name
        self.ctype = ctype        # e.g. class, trait, impl
        self.nest = 0
        self.saved = saved        # inline: (header, paren depth) to restore on close
        self.symbol_index = symbol_index  # position in the output of the symbol owning this body
        # cached so that lookups stay O(1) however deep the nesting is
        self.eff = parent.eff if kind == "transparent" and parent else kind
        base = parent.prefix if parent else ()
        self.prefix = base + (name,) if kind == "container" and name else base
        self.cont = self if kind == "container" else (parent.cont if parent else None)


# Token tuple layout: (text, line, start, end)
T, LN, ST, EN = 0, 1, 2, 3


def _close_index(h, i: int, open_: str, close: str) -> int:
    depth = 0
    for k in range(i, len(h)):
        if h[k][T] == open_:
            depth += 1
        elif h[k][T] == close:
            depth -= 1
            if depth == 0:
                return k
    return -1


def _open_index(h, i: int, open_: str, close: str) -> int:
    depth = 0
    for k in range(i, -1, -1):
        if h[k][T] == close:
            depth += 1
        elif h[k][T] == open_:
            depth -= 1
            if depth == 0:
                return k
    return -1


def _close_angle(h, i: int) -> int:
    """Index of the '>' matching the '<' at i; brackets inside () and [] are ignored."""
    depth = paren = 0
    for k in range(i, len(h)):
        s = h[k][T]
        if s in ("(", "["):
            paren += 1
        elif s in (")", "]"):
            paren -= 1
            if paren < 0:
                return -1
        elif paren == 0 and s == "<":
            depth += 1
        elif paren == 0 and s == ">":
            depth -= 1
            if depth == 0:
                return k
        elif paren == 0 and s in (";", "{}"):
            return -1
    return -1


def _open_angle(h, i: int, limit: int = 256) -> int:
    """Index of the '<' matching the '>' at i, scanning backwards (at most `limit` tokens)."""
    depth = paren = 0
    for k in range(i, max(-1, i - limit), -1):
        s = h[k][T]
        if s in (")", "]"):
            paren += 1
        elif s in ("(", "["):
            paren -= 1
            if paren < 0:
                return -1
        elif paren == 0 and s == ">":
            depth += 1
        elif paren == 0 and s == "<":
            depth -= 1
            if depth == 0:
                return k
    return -1


def _top_indices(h, targets: set[str], angle: bool = False) -> list[int]:
    """Indices of tokens in targets that sit outside (), [] (and <> if angle)."""
    res, depth, adepth = [], 0, 0
    for k, tok in enumerate(h):
        s = tok[T]
        # closers are compared at the depth they return to, openers at the depth they start at
        if s in (")", "]"):
            depth = max(0, depth - 1)
        elif angle and s == ">" and adepth > 0:
            adepth -= 1
        if s in targets and depth == 0 and adepth == 0:
            res.append(k)
        if s in ("(", "["):
            depth += 1
        elif (angle and s == "<" and k > 0 and h[k - 1][T] != "operator"
              and (_is_ident(h[k - 1][T]) or h[k - 1][T] in ("::", "template"))):
            adepth += 1
    return res


def _strip_groups(h, start: str, open_: str, close: str):
    """Remove leading groups such as #[...] or [Attr] or @Anno(...)."""
    k, n = 0, len(h)
    while k < n:
        if start == "#[" and h[k][T] == "#" and k + 1 < n:
            b = k + 1 + (h[k + 1][T] == "!")
            if b < n and h[b][T] == "[":
                end = _close_index(h, b, "[", "]")
                k = end + 1 if end > 0 else n
                continue
        elif start == "[" and h[k][T] == "[":
            end = _close_index(h, k, "[", "]")
            k = end + 1 if end > 0 else n
            continue
        elif start == "@" and h[k][T] == "@" and k + 1 < n and h[k + 1][T] != "interface":
            k += 2
            while k + 1 < n and h[k][T] == "." and _is_ident(h[k + 1][T]):
                k += 2
            if k < n and h[k][T] == "(":
                end = _close_index(h, k, "(", ")")
                k = end + 1 if end > 0 else n
            continue
        break
    return h[k:]


def _strip_annotations(h):
    """Remove Java annotations anywhere in a header: `public @Nullable String`, `List<@A T>`."""
    out, k, n = [], 0, len(h)
    while k < n:
        if h[k][T] == "@" and k + 1 < n and _is_ident(h[k + 1][T]) and h[k + 1][T] != "interface":
            k += 2
            while k + 1 < n and h[k][T] == "." and _is_ident(h[k + 1][T]):
                k += 2
            if k < n and h[k][T] == "(":
                end = _close_index(h, k, "(", ")")
                k = end + 1 if end > 0 else n
            continue
        out.append(h[k])
        k += 1
    return out


def _is_macro_name(name: str) -> bool:
    """ALL_CAPS names with an underscore, such as GTEST_LOCK_EXCLUDED_ or API_EXPORT."""
    return "_" in name and name.upper() == name and any(c.isalpha() for c in name)


def _drop_leading(h, words: set[str]):
    k = 0
    while k < len(h) and h[k][T] in words:
        k += 1
    return h[k:]


class _Scanner:
    def __init__(self, text: str, lang: str):
        self.lang = lang
        self.src = text
        self.ctor_hdr = None  # header whose '{' are member initializers (C++)
        masker = _Masker(text, lang)
        self.masked = masker.run()
        self.literals = masker.literals
        self.comments = masker.comments
        self.comment_starts = [a for a, _ in masker.comments]
        self.line_starts = [0] + [m.end() for m in re.finditer("\n", self.masked)]
        self.out: list[tuple[str, int, int]] = []
        self.stack = [_Scope("file")]

    # -- helpers

    def line(self, pos: int) -> int:
        return bisect_right(self.line_starts, pos)

    def span(self, h, a: int, b: int) -> str:
        """Source text of tokens h[a:b] with whitespace collapsed."""
        if a >= b:
            return ""
        lo, hi = h[a][ST], h[b - 1][EN]
        parts, pos = [], lo
        k = bisect_right(self.comment_starts, lo) - 1
        k = max(k, 0)
        while k < len(self.comments) and self.comments[k][0] < hi:
            c0, c1 = self.comments[k]
            if c1 > pos:
                parts.append(self.src[pos:max(pos, c0)])
                pos = max(pos, c1)
            k += 1
        parts.append(self.src[pos:hi] if pos < hi else "")
        return re.sub(r"\s+", " ", "".join(parts)).strip()

    def push(self, kind: str, **kw) -> None:
        self.stack.append(_Scope(kind, self.stack[-1], **kw))

    def emit(self, name: str, line: int, end_line: int) -> int:
        """Record a symbol and return its position in the output."""
        self.out.append((".".join(self.stack[-1].prefix + (name,)), line, end_line))
        return len(self.out) - 1

    def close(self, scope: _Scope, end_line: int) -> None:
        """A body has closed: its symbol, if it has one, ends on end_line."""
        if scope.symbol_index is not None:
            name, line, _ = self.out[scope.symbol_index]
            self.out[scope.symbol_index] = (name, line, end_line)

    def pop_scope(self, end_line: int) -> None:
        """Leave the innermost scope; every pop goes through here so no symbol keeps its
        placeholder end line."""
        self.close(self.stack.pop(), end_line)

    def container(self):
        return self.stack[-1].cont

    # -- main loop

    def run(self) -> list[tuple[str, int, int]]:
        header: list = []
        pdepth = 0
        prev_line = 0
        asi = self.lang in JS_LANGS or self.lang == "go"
        for m in _TOKEN.finditer(self.masked):
            tok = (m.group(), self.line(m.start()), m.start(), m.end())
            s = tok[T]
            top = self.stack[-1]
            if top.kind in ("func", "opaque", "inline"):
                if s == "{":
                    top.nest += 1
                elif s == "}":
                    if top.nest == 0:
                        self.pop_scope(tok[LN])
                        if top.kind == "inline":
                            header, pdepth = top.saved
                            header.append(("{}", tok[LN], tok[ST], tok[EN]))
                        else:
                            header, pdepth = [], 0
                    else:
                        top.nest -= 1
                prev_line = tok[LN]
                continue

            if (asi and header and pdepth == 0 and tok[LN] != prev_line
                    and self.soft_boundary(header, tok)):
                self.bodiless(header)
                header = []
            prev_line = tok[LN]

            if top.kind == "gotypes" and s == ")" and pdepth == 0:
                self.bodiless(header)
                self.pop_scope(tok[LN])
                header = []
                continue
            if (self.lang == "go" and s == "(" and top.kind == "file"
                    and [x[T] for x in header] == ["type"]):
                self.push("gotypes")
                header = []
                continue

            if s == "{":
                if pdepth > 0 or self.inline_brace(header, tok):
                    self.push("inline", saved=(header, pdepth))
                else:
                    self.open_block(header)
                header, pdepth = [], 0
            elif s == "}":
                self.bodiless(header)
                header, pdepth = [], 0
                if len(self.stack) > 1:
                    self.pop_scope(tok[LN])
            elif s == ";" and pdepth == 0:
                self.bodiless(header, tok[LN])
                header = []
            elif s == "," and pdepth == 0 and top.kind == "jsobject":
                header = []
            else:
                header.append(tok)
                if s in "([":
                    pdepth += 1
                elif s in ")]":
                    pdepth = max(0, pdepth - 1)
        if header and self.stack[-1].kind not in ("func", "opaque", "inline"):
            self.bodiless(header)
        last_line = self.src.rstrip().count("\n") + 1
        for scope in self.stack:  # bodies never closed run to the end of the file
            self.close(scope, last_line)
        return self.out

    # -- boundaries

    _JS_DECL_WORDS = {"export", "default", "function", "class", "abstract", "async", "declare",
                      "interface", "enum", "namespace", "const", "let", "var", "static",
                      "public", "private", "protected", "readonly", "override"}
    _JS_CONT_END = {",", "=", "(", "[", ".", "=>", "&", "|", "?", ":", "+", "-", "*", "/", "%",
                    "<", "!", "~", "^", "extends", "implements", "new", "in", "of",
                    "instanceof", "typeof", "await", "@"}
    _JS_CONT_START = {".", ")", "]", "=>", "?", ":", ",", "=", "*", "/", "&", "|", ">", "+",
                      "-", "%", "extends", "implements", "{", "<", "as", "satisfies", "in",
                      "instanceof"}

    def soft_boundary(self, header, tok) -> bool:
        nxt = tok[T]
        last = header[-1][T]
        if self.literal_between(header, tok):
            last = "0"  # a (masked) literal ends the line: it is an operand
        if self.lang == "go":
            return (_is_ident(last) and last not in ("func", "type", "struct", "interface",
                                                     "map", "chan")) \
                or last[:1].isdigit() or last in (")", "]", "{}", "}")
        if last in self._JS_CONT_END or nxt in self._JS_CONT_START:
            return False
        before = header[-2][T] if len(header) > 1 else ""
        if last in self._JS_DECL_WORDS and before not in (".", "let", "const", "var"):
            return False  # `export` + newline + `function f`, but not `x.default` or `let async`
        return True

    def literal_between(self, header, tok) -> bool:
        """Was a (masked) literal the last thing before tok? It then acts as an operand."""
        k = bisect_right(self.literals, header[-1][EN] - 1)
        return k < len(self.literals) and self.literals[k] < tok[ST]

    def inline_brace(self, header, tok) -> bool:
        """A '{' that belongs to the declaration being read rather than opening its body."""
        if not header:
            return False
        last = header[-1][T]
        if last in (":", "|", "&") and self.literal_between(header, tok):
            last = "0"  # `): "a" | "b" {`: the literal type ends the header
        if self.lang in ("typescript", "tsx"):
            if last == ":" and self.stack[-1].kind != "jsobject":
                return True  # object type annotation, e.g. `): { a: number } {`
            if last in ("|", "&"):
                return True  # union / intersection of object types
            if self._open_angle_count(header) > 0:
                return True  # object type inside generics: `Promise<{`, `extends B<{`
        if self.lang == "rust" and self._open_angle_count(header) > 0:
            return True  # const generic block: `impl Foo<{ N + 1 }>`
        if self.lang == "cpp" and (_is_ident(last) or last == ">"):
            # member initializer with braces: `C() : x{1}, y{2} {`
            if header is self.ctor_hdr:
                return True  # already known: keeps long initializer lists linear
            h = self._cpp_prep(header)
            if self._cpp_class_start(h) is not None:
                return False
            closes = _top_indices(h, {")"}, angle=True)
            if closes and any(h[k][T] == ":" for k in range(closes[0] + 1, len(h))):
                self.ctor_hdr = header
                return True
        return False

    @staticmethod
    def _open_angle_count(h) -> int:
        depth = paren = 0
        for k, tok in enumerate(h):
            s = tok[T]
            if s in ("(", "["):
                paren += 1
            elif s in (")", "]"):
                paren = max(0, paren - 1)
            elif paren == 0 and s == "<" and k > 0 and (_is_ident(h[k - 1][T]) or h[k - 1][T] == "."):
                depth += 1
            elif paren == 0 and s == ">" and depth > 0:
                depth -= 1
        return depth

    # -- dispatch

    def open_block(self, header) -> None:
        act = getattr(self, "open_" + self.lang_family())(header)
        kind = act[0] if act else "opaque"
        symbol_index = None
        if kind in ("container", "func", "leaf"):
            # the end line is a placeholder until the body's scope is popped
            symbol_index = self.emit(act[1], act[2], act[2])
        if kind == "container":
            self.push("container", name=act[1], ctype=act[3] if len(act) > 3 else "",
                      symbol_index=symbol_index)
        elif kind == "func":
            self.push("func", symbol_index=symbol_index)
        elif kind in ("transparent", "jsobject"):
            self.push(kind)
        else:
            self.push("opaque", symbol_index=symbol_index)  # leaf bodies are opaque

    def bodiless(self, header, end_line: int | None = None) -> None:
        """A declaration without a body; it ends on end_line (its terminating `;`) or, when
        nothing terminates it, on the line of its last token."""
        if not header:
            return
        act = getattr(self, "end_" + self.lang_family())(header)
        if act:
            self.emit(act[0], act[1], header[-1][LN] if end_line is None else end_line)

    def lang_family(self) -> str:
        return "js" if self.lang in JS_LANGS else ("c" if self.lang in ("c", "cpp") else self.lang)

    def scope_kind(self) -> str:
        """Kind of the nearest scope that is not transparent (file, container, gotypes)."""
        return self.stack[-1].eff

    # ---------------------------------------------------------------- JS / TS

    _JS_MODS = {"static", "async", "get", "set", "public", "private", "protected", "readonly",
                "override", "abstract", "declare", "accessor", "*"}
    _JS_CONTROL = {"if", "else", "for", "while", "do", "try", "catch", "finally", "switch",
                   "with", "case", "default"}

    def _js_decorators(self, h):
        return _strip_groups(h, "@", "(", ")")

    def open_js(self, h):
        h = self._js_decorators(h)
        kind = self.scope_kind()
        if kind == "container":
            return self._js_method(h) or ("opaque",)
        texts = [x[T] for x in h]
        if kind == "jsobject":
            # object literal member: shorthand method, or a nested object `key: {`
            if texts[-1:] == [":"]:
                return ("jsobject",)
            return self._js_method(h) or ("opaque",)
        if texts and (texts[-1] == "=" or texts in (["export", "default"], ["module", ".", "exports", "="])):
            return ("jsobject",)
        if not texts:
            return ("transparent",)
        if texts[0] in self._JS_CONTROL:
            return ("transparent",)
        k = 0
        while k < len(texts) and texts[k] in ("export", "default", "declare"):
            k += 1
        rest = texts[k:]
        if not rest:
            return ("opaque",)
        first = rest[0]
        if first == "async" and len(rest) > 1 and rest[1] == "function":
            k += 1
            first = "function"
        if first == "function":
            j = k + 1
            if j < len(h) and h[j][T] == "*":
                j += 1
            if j < len(h) and _is_ident(h[j][T]) and h[j][T] not in ("(",):
                return ("func", h[j][T], h[j][LN])
            return ("opaque",)
        if first == "abstract" and len(rest) > 1 and rest[1] == "class":
            k += 1
            first = "class"
        if first == "class":
            j = k + 1
            if j < len(h) and _is_ident(h[j][T]) and h[j][T] not in ("extends", "implements"):
                return ("container", h[j][T], h[j][LN], "class")
            return ("opaque",)
        if first in ("interface", "enum") or (first == "const" and len(rest) > 1 and rest[1] == "enum"):
            j = k + (2 if first == "const" else 1)
            if j < len(h) and _is_ident(h[j][T]):
                return ("leaf", h[j][T], h[j][LN])
            return ("opaque",)
        if first in ("const", "let", "var"):
            name = self._js_arrow_name(h, k)
            return ("func", name[0], name[1]) if name else ("opaque",)
        if first in ("namespace", "module", "global") and all(
                _is_ident(x) or x == "." for x in rest[1:]):
            return ("transparent",)
        return ("opaque",)

    def _js_arrow_name(self, h, k):
        """`const NAME [: T] = [async] (function | (...) => | <T>(...) => | x =>)` → (name, line)."""
        j = k + 1
        if j >= len(h) or not _is_ident(h[j][T]):
            return None
        eq = [i for i in _top_indices(h, {"="}, angle=True) if i > j]
        if not eq:
            return None
        v = h[eq[0] + 1:]
        while v and v[0][T] == "async":
            v = v[1:]
        if not v:
            return None
        name = (h[j][T], h[j][LN])
        if v[0][T] == "function":
            return name
        if _is_ident(v[0][T]):
            return name if len(v) > 1 and v[1][T] == "=>" else None
        if v[0][T] == "<":
            end = _close_angle(v, 0)
            if end < 0:
                return None
            v = v[end + 1:]
        if not v or v[0][T] != "(":
            return None
        end = _close_index(v, 0, "(", ")")
        rest = v[end + 1:] if end >= 0 else []
        if rest and rest[0][T] == "=>":
            return name
        if rest and rest[0][T] == ":" and _top_indices(rest, {"=>"}, angle=True):
            return name  # return type annotation: `(x): Promise<T> =>`
        return None

    def _js_method(self, h):
        tops = _top_indices(h, {"("}, angle=True)
        if not tops or _top_indices(h[:tops[0]], {"="}, angle=True):
            return None
        p = tops[0]
        n = p - 1
        if n >= 0 and h[n][T] == ">":
            n = _open_angle(h, n) - 1
        if n >= 0 and h[n][T] in ("?", "!"):  # TS optional / definite method: foo?()
            n -= 1
        if n < 0 or not _is_ident(h[n][T]):
            return None
        name = h[n][T]
        pre = [x[T] for x in h[:n]]
        if pre and pre[-1] == "#":
            name = "#" + name
            pre = pre[:-1]
        if any(x not in self._JS_MODS for x in pre):
            return None
        return ("func", name, h[n][LN])

    def end_js(self, h):
        h = self._js_decorators(h)
        if self.scope_kind() == "container":
            return None
        texts = [x[T] for x in h]
        k = 0
        while k < len(texts) and texts[k] in ("export", "declare"):
            k += 1
        if k < len(texts) and texts[k] in ("const", "let", "var"):
            name = self._js_arrow_name(h, k)
            if name and "=>" in texts:
                return name
        return None

    # ---------------------------------------------------------------- Go

    def open_go(self, h):
        if self.stack[-1].kind == "gotypes":
            if h and _is_ident(h[0][T]):
                return ("leaf", h[0][T], h[0][LN])
            return ("opaque",)
        texts = [x[T] for x in h]
        if not texts:
            return ("opaque",)
        if texts[0] == "func":
            r = self._go_func(h)
            return ("func",) + r if r else ("opaque",)
        if texts[0] == "type" and len(h) > 1 and _is_ident(h[1][T]):
            return ("leaf", h[1][T], h[1][LN])
        return ("opaque",)

    def _go_func(self, h):
        if len(h) < 2:
            return None
        if h[1][T] == "(":
            end = _close_index(h, 1, "(", ")")
            if end < 0 or end + 1 >= len(h) or not _is_ident(h[end + 1][T]):
                return None
            toks = [x[T] for x in h[2:end]]
            # (name Type) / (name *Type) / (Type) / (*Type), each optionally generic: List[T]
            if len(toks) >= 2 and _is_ident(toks[0]) and (_is_ident(toks[1]) or toks[1] == "*"):
                toks = toks[1:]
            toks = [x for x in toks if x != "*"]
            recv = toks[0] if toks and _is_ident(toks[0]) else ""
            name = h[end + 1]
            return (f"{recv}.{name[T]}" if recv else name[T], name[LN])
        if _is_ident(h[1][T]):
            return (h[1][T], h[1][LN])
        return None

    def end_go(self, h):
        if self.stack[-1].kind == "gotypes":
            return (h[0][T], h[0][LN]) if _is_ident(h[0][T]) else None
        if self.stack[-1].kind != "file":
            return None
        if h[0][T] == "type" and len(h) > 1 and _is_ident(h[1][T]):
            return (h[1][T], h[1][LN])
        if h[0][T] == "func":
            return self._go_func(h)
        return None

    # ---------------------------------------------------------------- Rust

    _RUST_MODS = {"pub", "default", "unsafe", "async", "const", "extern", "safe", "auto"}

    def _rust_prep(self, h):
        h = _strip_groups(h, "#[", "[", "]")
        out = []
        k = 0
        while k < len(h):
            s = h[k][T]
            if s == "pub" and k + 1 < len(h) and h[k + 1][T] == "(":
                end = _close_index(h, k + 1, "(", ")")
                k = end + 1 if end > 0 else len(h)
                continue
            if s in self._RUST_MODS and not (s == "const" and k + 1 < len(h)
                                             and _is_ident(h[k + 1][T])
                                             and h[k + 1][T] not in ("fn", "unsafe", "async",
                                                                      "extern")):
                k += 1
                continue
            break
        return h[k:]

    def open_rust(self, h):
        h = self._rust_prep(h)
        texts = [x[T] for x in h]
        if not texts:
            return ("transparent",)  # extern "C" { ... } or a bare block
        first = texts[0]
        if first == "fn" and len(h) > 1 and _is_ident(h[1][T]):
            return ("func", h[1][T], h[1][LN])
        if first == "impl":
            name = self._rust_impl(h)
            return ("container", name, h[0][LN], "impl") if name else ("opaque",)
        if first in ("trait", "mod") and len(h) > 1 and _is_ident(h[1][T]):
            return ("container", h[1][T], h[1][LN], first)
        if first in ("struct", "enum") and len(h) > 1 and _is_ident(h[1][T]):
            return ("leaf", h[1][T], h[1][LN])
        return ("opaque",)

    def _rust_impl(self, h):
        k = 1
        if k < len(h) and h[k][T] == "<":
            end = _close_angle(h, k)
            k = end + 1 if end > 0 else len(h)
        stop = len(h)
        for i in _top_indices(h[k:], {"where"}, angle=True):
            stop = k + i
            break
        fors = [k + i for i in _top_indices(h[k:stop], {"for"}, angle=True)]
        if fors:
            trait = self.span(h, k, fors[0])
            typ = self.span(h, fors[0] + 1, stop)
            return f"{typ}<{trait}>" if typ else None
        return self.span(h, k, stop) or None

    def end_rust(self, h):
        h = self._rust_prep(h)
        if not h:
            return None
        first = h[0][T]
        if first == "fn" and len(h) > 1 and _is_ident(h[1][T]):
            return (h[1][T], h[1][LN])
        if first in ("struct", "enum", "mod") and len(h) > 1 and _is_ident(h[1][T]):
            return (h[1][T], h[1][LN])
        return None

    # ---------------------------------------------------------------- Java / C#

    _JAVA_MODS = {"public", "private", "protected", "static", "final", "abstract",
                  "synchronized", "native", "strictfp", "transient", "volatile", "default",
                  "sealed", "non", "-"}
    _CS_MODS = {"public", "private", "protected", "internal", "static", "readonly", "sealed",
                "abstract", "virtual", "override", "extern", "unsafe", "new", "partial", "async",
                "const", "volatile", "ref", "file", "required", "scoped", "fixed", "implicit",
                "explicit"}
    _NOT_NAMES = {"if", "for", "foreach", "while", "switch", "catch", "synchronized", "return",
                  "new", "throw", "super", "this", "base", "try", "do", "else", "assert", "case",
                  "using", "lock", "fixed", "checked", "unchecked", "nameof", "typeof", "sizeof",
                  "default", "when", "operator", "await"}
    _PRE_BAD = {"return", "new", "throw", "if", "else", "for", "while", "switch", "case", "do",
                "try", "await", "="}
    _TYPEISH = {".", "<", ">", ",", "?", "[", "]", "&", "extends", "super", "::", "*"}

    def _jc_prep(self, h):
        if self.lang == "java":
            return _strip_annotations(h)
        return _strip_groups(h, "[", "[", "]")

    def _jc_container(self, h):
        mods = self._JAVA_MODS if self.lang == "java" else self._CS_MODS
        kws = {"class", "interface", "enum", "record"} | ({"struct"} if self.lang == "csharp" else set())
        k = 0
        while k < len(h) and h[k][T] in mods:
            k += 1
        if k < len(h) and h[k][T] in kws:
            kw = h[k][T]
            j = k + 1
            if kw == "record" and j < len(h) and h[j][T] in ("struct", "class"):
                j += 1
            if j < len(h) and _is_ident(h[j][T]):
                return (kw, h[j][T], h[j][LN])
        return None

    def _jc_method(self, h):
        arrow = _top_indices(h, {"=>"})
        if arrow:
            h = h[:arrow[0]]
        eqs = _top_indices(h, {"="}, angle=True)
        limit = eqs[0] if eqs else len(h)
        # the name is at one of the first few '(' (after a tuple return type at most)
        for p in _top_indices(h[:limit], {"("}, angle=True)[:3]:
            found = self._jc_method_at(h, p)
            if found:
                return found
        return None

    def _jc_method_at(self, h, p):
        if any(x[T] == "operator" for x in h[:p]):
            return None
        if self.lang == "csharp" and any(
                x[T] == "delegate" and not (i + 1 < len(h) and h[i + 1][T] == "*")
                for i, x in enumerate(h[:p])):
            return None
        n = p - 1
        if n >= 0 and h[n][T] == ">":
            n = _open_angle(h, n) - 1
        mods = self._JAVA_MODS if self.lang == "java" else self._CS_MODS
        if n < 0 or not _is_ident(h[n][T]) or h[n][T] in self._NOT_NAMES or h[n][T] in mods:
            return None
        if n > 0 and h[n - 1][T] == "~":
            return None
        pre = [x[T] for x in h[:n] if x[T] not in mods]
        if pre and pre[0] == "<":  # method type parameters: <T> List<T> foo(
            depth = 0
            for i, x in enumerate(pre):
                depth += (x == "<") - (x == ">")
                if depth == 0:
                    pre = pre[i + 1:]
                    break
        if not pre:
            container = self.container()
            if container and container.name == h[n][T]:
                return (h[n][T], h[n][LN])  # constructor
            return None
        if pre[0] == "." or not any(_is_ident(x) and x not in ("extends", "super") for x in pre):
            return None  # e.g. `}.toString()` after an anonymous class
        allowed = self._TYPEISH | ({"(", ")"} if self.lang == "csharp" else set())
        if any(not (_is_ident(x) or x in allowed) for x in pre):
            return None
        depth = 0
        for x in pre:  # a comma only appears nested: Map<K, V>, (int a, int b), int[,]
            depth += (x in "<([") - (x in ">)]")
            if x == "," and depth <= 0:
                return None
        if any(x in self._PRE_BAD for x in pre):
            return None
        return (h[n][T], h[n][LN])

    def open_java(self, h):
        h = self._jc_prep(h)
        c = self._jc_container(h)
        if c:
            if c[0] == "enum" and self.lang == "csharp":
                return ("leaf", c[1], c[2])
            return ("container", c[1], c[2], c[0])
        texts = [x[T] for x in h]
        if self.lang == "csharp" and texts[:1] == ["namespace"]:
            return ("transparent",)
        if self.scope_kind() == "container":
            m = self._jc_method(h)
            if m:
                return ("func",) + m
            if self.lang == "java" and self._java_class_body(h):
                return ("transparent",)
        return ("opaque",)

    def _java_class_body(self, h) -> bool:
        """Enum constant body `A(1) {` or anonymous class `x = new T() {`: members count
        toward the enclosing class."""
        commas = _top_indices(h, {","}, angle=True)
        if commas:
            h = h[commas[-1] + 1:]  # `A(1), B(2) {`: the constant that owns the body
        texts = [x[T] for x in h]
        if not texts:
            return False
        if len(texts) == 1:
            container = self.container()
            # not `static {` initializers nor record compact constructors `R {`
            return _is_ident(texts[0]) and texts[0] != "static" and not (
                container and container.name == texts[0])
        if texts[-1] != ")":
            return False
        if _top_indices(h, {"new"}):
            return True
        return _is_ident(texts[0]) and texts[1] == "(" and _close_index(h, 1, "(", ")") == len(h) - 1

    def end_java(self, h):
        h = self._jc_prep(h)
        c = self._jc_container(h)
        if c:
            return (c[1], c[2])
        if self.scope_kind() == "container":
            return self._jc_method(h)
        return None

    open_csharp = open_java
    end_csharp = end_java

    # ---------------------------------------------------------------- C / C++

    _C_SKIP = {"if", "while", "for", "switch", "return", "sizeof", "alignof", "decltype",
               "__attribute__", "__attribute", "__declspec", "alignas", "_Alignas", "__asm__",
               "asm", "noexcept", "throw", "static_assert", "_Static_assert", "typeof",
               "__typeof__", "defined", "requires", "__pragma", "_Pragma", "catch", "new",
               "delete", "else", "do"}

    def _cpp_prep(self, h):
        out = list(h)
        while True:
            # access specifiers: `public:`, `private slots:`
            k = 1 if out and out[0][T] in ("public", "private", "protected", "signals",
                                           "Q_SIGNALS", "Q_SLOTS", "slots") else 0
            if k and k < len(out) and out[k][T] in ("slots", "Q_SLOTS"):
                k += 1
            if k and k < len(out) and out[k][T] == ":":
                out = out[k + 1:]
                continue
            if len(out) >= 2 and out[0][T] == "[" and out[1][T] == "[":
                end = _close_index(out, 0, "[", "]")
                out = out[end + 1:] if end > 0 else []
                continue
            if out and out[0][T] == "template" and len(out) > 1 and out[1][T] == "<":
                end = _close_angle(out, 1)
                out = out[end + 1:] if end > 0 else []
                continue
            if out and out[0][T] in ("typedef", "friend", "export", "inline", "constexpr",
                                     "static", "extern") and not (
                    out[0][T] == "extern" and len(out) == 1):
                if out[0][T] == "inline" and len(out) > 1 and out[1][T] == "namespace":
                    out = out[1:]
                    continue
                if out[0][T] in ("typedef", "friend", "export"):
                    out = out[1:]
                    continue
            break
        return out

    def open_c(self, h):
        cpp = self.lang == "cpp"
        texts = [x[T] for x in h]
        if texts in ([], ["extern"]):
            return ("transparent",)  # extern "C" { ... } or a bare block
        if cpp:
            h = self._cpp_prep(h)
            texts = [x[T] for x in h]
            # a macro invocation without ';' may precede the real declaration:
            # `SOME_MACRO(x) namespace a {`, `EXPORT_MACRO(y) class Foo : Bar {`
            ns = _top_indices(h, {"namespace"}, angle=True)
            if ns and all(_is_ident(x[T]) or x[T] in ("::", "inline") for x in h[ns[-1] + 1:]):
                return ("transparent",)
            if texts == ["extern"]:
                return ("transparent",)
            cls = self._cpp_class_start(h)
            if cls is not None:
                name = self._cpp_class_name(h[cls:])
                return ("container", name[0], name[1], h[cls][T]) if name else ("opaque",)
        parens = _top_indices(h, {"("}, angle=True)
        if not texts or (texts[0] in ("struct", "union", "enum", "typedef", "class") and not parens):
            return ("opaque",)
        f = self._c_func(h)
        return ("func",) + f if f else ("opaque",)

    def _cpp_class_start(self, h):
        """Index of the `class`/`struct` keyword that starts a class definition, if any."""
        for k in reversed(_top_indices(h, {"class", "struct"}, angle=True)):
            if k > 0 and h[k - 1][T] == "enum":
                return None  # enum class
            tail = h[k + 1:]
            colon = _top_indices(tail, {":"}, angle=True)
            head = tail[:colon[0]] if colon else tail
            if _top_indices(head, {"(", "="}, angle=True):
                # `struct S f() {` is a function; only attribute/alignas parens are allowed
                if not all(h2[T] in ("alignas", "__declspec", "__attribute__")
                           for h2 in (head[i - 1] for i in _top_indices(head, {"("}, angle=True) if i > 0)):
                    return None
            return k
        return None

    def _cpp_class_name(self, h):
        stop = len(h)
        for i in _top_indices(h, {":", "final", "<"}):
            if i > 1:
                stop = i
                break
        idents = [i for i in range(1, stop) if _is_ident(h[i][T]) and h[i][T] not in ("alignas", "final")]
        if not idents:
            return None
        # export/attribute macros: `class API_EXPORT Foo`, `class Foo MY_FINAL`
        named = [i for i in idents if not _is_macro_name(h[i][T])]
        n = (named or idents)[-1]
        start = n
        while start >= 2 and h[start - 1][T] == "::" and _is_ident(h[start - 2][T]):
            start -= 2  # qualified: `struct A::C`
        if stop < len(h) and h[stop][T] == "<" and stop == n + 1:
            end = _close_angle(h, stop)
            if end > 0:
                return (self.span(h, start, end + 1), h[n][LN])
        return (self.span(h, start, n + 1).replace(" ", ""), h[n][LN])

    _DECL_WORDS = {"enum", "class", "struct", "union", "namespace", "typedef", "template", "using"}

    def _c_func(self, h):
        tops = _top_indices(h, {"("}, angle=True)
        if not tops:
            return None
        if any(x[T] == "=" for x in h[:tops[0]]) and not any(x[T] == "operator" for x in h):
            return None
        # cut a C++ member initializer list / function-try-block: `) : a(1)`, `) try : a(1)`
        closes = _top_indices(h, {")"}, angle=True)
        limit = len(h)
        for i in range(closes[0] + 1 if closes else len(h), len(h)):
            if h[i][T] == ":" and h[i - 1][T] in (")", "const", "noexcept", "override", "final",
                                                   "volatile", "&", "&&", "{}", "try"):
                limit = i
                break
        last_decl = max((i for i in range(limit) if h[i][T] in self._DECL_WORDS), default=-1)
        cands = []  # (name, line, follows a parameter list)
        for p in tops:
            if p >= limit:
                break
            declarator = self._c_paren_declarator(h, p)
            if declarator:
                cands.append((declarator[0], declarator[1], False))
                continue
            n = self._c_name_start(h, p)
            if n is None:
                continue
            end = _close_index(h, p, "(", ")")
            if end > 0 and last_decl > end:
                continue  # a macro call followed by a real declaration: `MACRO(x) enum class E`
            after_params = n > 0 and h[n - 1][T] in (")", "const", "noexcept", "override",
                                                     "final", "volatile", "&", "&&")
            cands.append((self._c_clean(self.span(h, n, p)), h[n][LN], after_params))
        if not cands:
            return None
        # `void f() ACQUIRE(mu)`: a name right after a parameter list is an annotation macro;
        # `MACRO(x) int f()`: prefer a name that does not look like a macro
        pool = [c for c in cands if not c[2]] or cands
        named = [c for c in pool if not _is_macro_name(c[0].split("::")[-1])]
        best = (named or pool)[-1]
        return (best[0], best[1])

    @staticmethod
    def _c_clean(name: str) -> str:
        name = re.sub(r"\s*::\s*", "::", name)
        name = re.sub(r"~\s+", "~", name)
        return re.sub(r"operator\s+(?=[^\w\s])", "operator", name)

    def _c_paren_declarator(self, h, p):
        """`int (*getfn(int x))(int)`, `int (f)(void)`, `int(ns::f)(FILE*)` → (name, line)."""
        end = _close_index(h, p, "(", ")")
        if end < 0 or p == 0 or not (_is_ident(h[p - 1][T]) or h[p - 1][T] in ("*", "&", ">")):
            return None
        inner = h[p + 1:end]
        if not inner:
            return None
        if inner[0][T] in ("*", "&", "^"):
            k = 0
            while k < len(inner) and inner[k][T] in ("*", "&", "^", "const", "volatile"):
                k += 1
            rest = inner[k:]
            if any(x[T] == "(" for x in rest):
                return self._c_func(rest)
            return None  # a plain function pointer variable
        if end + 1 < len(h) and h[end + 1][T] == "(" and all(
                _is_ident(x[T]) or x[T] == "::" for x in inner):
            return (self.span(h, p + 1, end).replace(" ", ""), inner[0][LN])
        return None

    def _c_name_start(self, h, p):
        """Index of the first token of the declarator name ending right before '(' at p."""
        k = p - 1
        if k < 0:
            return None
        if h[k][T] == "operator":
            return None  # `operator()(`: this '(' is part of the name; the next one is used
        op = self._operator_before(h, k)
        if op is not None:
            start = op
        elif h[k][T] == ")":
            # `operator()(`: name is `operator()`
            if k >= 2 and h[k - 1][T] == "(" and h[k - 2][T] == "operator":
                start = k - 2
            else:
                return None
        elif h[k][T] == ">" and not any(h[i][T] == "operator" for i in range(max(0, k - 3), k)):
            q = _open_angle(h, k) - 1  # explicit specialization: `f<true>(`
            if q < 0 or not _is_ident(h[q][T]) or h[q][T] in self._C_SKIP:
                return None
            start = q
        elif not _is_ident(h[k][T]):
            # `operator==(`, `operator<<(`
            j = k
            while j >= 0 and not _is_ident(h[j][T]) and h[j][T] not in ("(", ")", ";", ",", "{}"):
                j -= 1
            if j >= 0 and h[j][T] == "operator":
                start = j
            else:
                return None
        elif k >= 1 and h[k - 1][T] == "operator":
            start = k - 1  # `operator new(`, `operator bool(`
        else:
            if h[k][T] in self._C_SKIP:
                return None
            start = k
        if start >= 1 and h[start - 1][T] == "operator":
            start -= 1  # conversion operator to a template type: `operator Action<F>(`
        # extend with qualifiers: A::B<T>::~name
        j = start
        while j - 1 >= 0:
            prev = h[j - 1][T]
            if prev == "~":
                j -= 1
            elif prev == "::" and j - 2 >= 0:
                q = j - 2
                if h[q][T] == ">":
                    q = _open_angle(h, q) - 1
                if q >= 0 and _is_ident(h[q][T]):
                    j = q
                else:
                    j -= 1
                    break
            else:
                break
        if j - 1 >= 0 and h[j - 1][T] in (".", "->"):
            return None
        return j

    @staticmethod
    def _operator_before(h, k):
        """Index of `operator` in `operator==`, `operator new[]`, `operator std::vector<int>` …"""
        j, steps, angle = k, 0, 0
        while j >= 0 and steps < 24:
            s = h[j][T]
            if s == "operator":
                return j
            if s == ">":
                angle += 1
            elif s == "<" and angle:
                angle -= 1
            elif s in ("(", ")", ";", "{}") or (
                    s == "," and not angle and not (j >= 1 and h[j - 1][T] == "operator")):
                return None
            j -= 1
            steps += 1
        return None

    def end_c(self, h):
        return None
