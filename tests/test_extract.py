import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from extract import extract_symbols, extract_text  # noqa: E402


def names(src, lang):
    return extract_text(src, lang)


# ---------------------------------------------------------------- Python


def test_python_rules():
    src = (
        "import typing\n"
        "if typing.TYPE_CHECKING:\n"
        "    def only_typing(): pass\n"
        "\n"
        "@decorator\n"
        "@other(1)\n"
        "async def handler(x):\n"
        "    def inner(): pass\n"
        "    class Local: pass\n"
        "\n"
        "class A:\n"
        "    try:\n"
        "        def maybe(self): pass\n"
        "    except ImportError:\n"
        "        def fallback(self): pass\n"
    )
    assert names(src, "python") == [
        ("only_typing", 3), ("handler", 7), ("A", 11), ("A.maybe", 13), ("A.fallback", 15)]


def test_python_syntax_error_raises(tmp_path):
    f = tmp_path / "bad.py"
    f.write_text("def broken(:\n", encoding="utf-8")
    with pytest.raises(SyntaxError):
        extract_symbols(f)


def test_bom_and_crlf(tmp_path):
    f = tmp_path / "w.py"
    f.write_bytes("\ufeffimport os\r\n\r\ndef f():\r\n    pass\r\n".encode("utf-8"))
    assert extract_symbols(f) == [("f", 3)]
    g = tmp_path / "w.ts"
    g.write_bytes(b"// c\r\nexport function g() {\r\n}\r\nclass K {\r\n  m() {}\r\n}\r\n")
    assert extract_symbols(g) == [("g", 2), ("K", 4), ("K.m", 5)]


# ---------------------------------------------------------------- JS / TS


def test_js_strings_comments_regex_templates():
    src = (
        "const s = '{ function fake() {'\n"
        "// function commented() {\n"
        "/* class Fake { */\n"
        "const re = /[{]function x\\/{/g\n"
        "const t = `${ `${'}'}` } { function tpl() {`\n"
        "function real() {\n"
        "  return 1\n"
        "}\n"
    )
    assert names(src, "javascript") == [("real", 6)]


def test_js_asi_and_arrows():
    src = (
        "import x from 'y'\n"
        "const a = 1\n"
        "const b = \"str\"\n"
        "function f() {}\n"
        "export const h = () => 1\n"
        "export const k = async (x) => {\n"
        "  const nested = () => 2\n"
        "}\n"
        "const notFn = cond ? () => 1 : 2\n"
        "let g = function () {}\n"
        "const obj = { a: 1 }\n"
    )
    assert names(src, "javascript") == [("f", 4), ("h", 5), ("k", 6), ("g", 10)]


def test_js_classes_and_objects():
    src = (
        "export default class Store extends Base {\n"
        "  static #count = 0\n"
        "  handler = () => {}\n"
        "  @observable\n"
        "  get size() { return 1 }\n"
        "  async *items() {}\n"
        "  #secret() {}\n"
        "  [Symbol.iterator]() {}\n"
        "}\n"
        "export default {\n"
        "  data() { return {} },\n"
        "  methods: {\n"
        "    save() {},\n"
        "    arrow: () => {},\n"
        "  },\n"
        "}\n"
    )
    assert names(src, "javascript") == [
        ("Store", 1), ("Store.size", 5), ("Store.items", 6), ("Store.#secret", 7),
        ("data", 11), ("save", 13)]


def test_ts_types_generics_and_jsx():
    src = (
        "interface Props { run(): void; name: string }\n"
        "export enum Color { Red }\n"
        "type Obj = { f(): void }\n"
        "function typed(x: { a: number }): { b: string } {\n"
        "  return { b: '' }\n"
        "}\n"
        "export const Card = ({ title }: Props) => (\n"
        "  <div className={title}>Don't {title}</div>\n"
        ")\n"
        "abstract class Repo<T> {\n"
        "  abstract find(): T;\n"
        "  public save<U extends T>(x: U): void {}\n"
        "  opt?(): void {}\n"
        "}\n"
        "namespace NS { export function inner() {} }\n"
    )
    assert names(src, "tsx") == [
        ("Props", 1), ("Color", 2), ("typed", 4), ("Card", 7), ("Repo", 10),
        ("Repo.save", 12), ("Repo.opt", 13), ("inner", 15)]


# ---------------------------------------------------------------- Go / Rust


def test_go():
    src = (
        "package p\n"
        "\n"
        "const tpl = `raw { string`\n"
        "type (\n"
        "\tID string\n"
        "\tUser struct {\n"
        "\t\tName string\n"
        "\t}\n"
        ")\n"
        "type List[T any] struct{ items []T }\n"
        "func (l *List[T]) Push(v T) {}\n"
        "func New(w io.Writer, in interface{}) error {\n"
        "\tf := func() {}\n"
        "\treturn nil\n"
        "}\n"
        "func asm(x int)\n"
    )
    assert names(src, "go") == [
        ("ID", 5), ("User", 6), ("List", 10), ("List.Push", 11), ("New", 12), ("asm", 16)]


def test_rust():
    src = (
        "#[cfg(test)]\n"
        "mod tests;\n"
        "pub(crate) struct Unit;\n"
        "struct P<'a> { s: &'a str }\n"
        "impl<'a> P<'a> {\n"
        "    pub const fn new(s: &'a str) -> Self { let c = '{'; P { s } }\n"
        "}\n"
        "impl fmt::Display for P<'_> {\n"
        "    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result { write!(f, r#\"{\"#) }\n"
        "}\n"
        "pub trait Shape: Send {\n"
        "    fn area(&self) -> f64;\n"
        "    fn name(&self) -> &str { \"x\" }\n"
        "}\n"
        "extern \"C\" {\n"
        "    fn c_func(x: i32) -> i32;\n"
        "}\n"
        "macro_rules! m { () => { fn fake() {} } }\n"
        "/* nested /* comment */ fn fake2() {} */\n"
        "async unsafe fn run() {}\n"
    )
    assert names(src, "rust") == [
        ("tests", 2), ("Unit", 3), ("P", 4), ("P<'a>", 5), ("P<'a>.new", 6),
        ("P<'_><fmt::Display>", 8), ("P<'_><fmt::Display>.fmt", 9), ("Shape", 11),
        ("Shape.area", 12), ("Shape.name", 13), ("c_func", 16), ("run", 20)]


# ---------------------------------------------------------------- Java / C#


def test_java():
    src = (
        "@Entity\n"
        "public class Svc<T> extends Base implements Runnable {\n"
        "  private final Runnable r = () -> { };\n"
        "  private final X x = new X() {\n"
        "    @Override public void anon() {}\n"
        "  };\n"
        "  @SuppressWarnings({\"a\", \"b\"})\n"
        "  public Svc(int a) { super(a); }\n"
        "  public <U> List<U> map(Function<T, U> f) throws IOException {\n"
        "    return null;\n"
        "  }\n"
        "  abstract void todo();\n"
        "  static { init(); }\n"
        "  enum Kind { A(1) { void over() {} }, B(2); Kind(int v) {} }\n"
        "  String s = \"\"\"\n"
        "      { text block }\n"
        "      \"\"\";\n"
        "  record Pair(int a, int b) {}\n"
        "}\n"
    )
    assert names(src, "java") == [
        ("Svc", 2), ("Svc.anon", 5), ("Svc.Svc", 8), ("Svc.map", 9), ("Svc.todo", 12),
        ("Svc.Kind", 14), ("Svc.Kind.over", 14), ("Svc.Kind.Kind", 14), ("Svc.Pair", 18)]


def test_csharp():
    src = (
        "namespace App.Core;\n"
        "#region stuff {\n"
        "[Serializable]\n"
        "public sealed partial class Repo<T> : IRepo where T : class\n"
        "{\n"
        "    private string v = @\"C:\\{dir}\"\"\";\n"
        "    private string w = $\"{(x ? \"}\" : \"{\")} done\";\n"
        "    public Repo(int x) : base(x) { }\n"
        "    public int Add(int a, int b) => a + b;\n"
        "    public int Size => 1;\n"
        "    public int P { get; set; }\n"
        "    public async Task<List<T>> AllAsync<U>() where U : T { return null; }\n"
        "    void IDisposable.Dispose() { }\n"
        "    public static Repo operator +(Repo a, Repo b) { return a; }\n"
        "    ~Repo() { }\n"
        "}\n"
        "public record Point(int X, int Y);\n"
        "public enum Color { Red }\n"
        "interface IRepo { void Save(); }\n"
    )
    assert names(src, "csharp") == [
        ("Repo", 4), ("Repo.Repo", 8), ("Repo.Add", 9), ("Repo.AllAsync", 12),
        ("Repo.Dispose", 13), ("Point", 17), ("Color", 18), ("IRepo", 19), ("IRepo.Save", 19)]


# ---------------------------------------------------------------- C / C++


def test_c():
    src = (
        "#define OPEN {\n"
        "#include <stdio.h>\n"
        "static const char *s = \"{\";\n"
        "struct point { int x; };\n"
        "struct point make_point(int x) { struct point p = {x}; return p; }\n"
        "int\n"
        "main(int argc, char **argv)\n"
        "{\n"
        "  if (argc) { return 0; }\n"
        "}\n"
        "static __attribute__((unused)) int helper(void) { return '}'; }\n"
        "int proto(int);\n"
    )
    assert names(src, "c") == [("make_point", 5), ("main", 7), ("helper", 11)]


def test_cpp():
    src = (
        "MACRO_WITHOUT_SEMICOLON(x)\n"
        "namespace a::b {\n"
        "template <typename T, typename = decltype(std::declval<T>() << 1)>\n"
        "class API_EXPORT Widget final : public Base<T> {\n"
        " public:\n"
        "  Widget() : x_{1}, y_(2) {}\n"
        "  ~Widget() {}\n"
        "  bool operator==(const Widget&) const { return true; }\n"
        "  operator bool() const { return true; }\n"
        "  auto size() const -> int { return 0; }\n"
        "  void declared();\n"
        " private:\n"
        "  struct Inner { void f() {} };\n"
        "};\n"
        "void Widget::declared() { auto s = R\"x({)x\"; int n = 1'000; }\n"
        "template <> struct hash<Widget> { size_t operator()(const Widget&) const { return 0; } };\n"
        "enum class Mode { A };\n"
        "extern \"C\" { int c_api(void) { return 0; } }\n"
        "}\n"
    )
    assert names(src, "cpp") == [
        ("Widget", 4), ("Widget.Widget", 6), ("Widget.~Widget", 7), ("Widget.operator==", 8),
        ("Widget.operator bool", 9), ("Widget.size", 10), ("Widget.Inner", 13),
        ("Widget.Inner.f", 13), ("Widget::declared", 15), ("hash<Widget>", 16),
        ("hash<Widget>.operator()", 16), ("c_api", 18)]


def test_cpp_header_with_h_extension(tmp_path):
    f = tmp_path / "w.h"
    f.write_text("namespace n {\nclass K { void m() {} };\n}\n", encoding="utf-8")
    assert extract_symbols(f) == [("K", 2), ("K.m", 2)]


# ---------------------------------------------------------------- robustness


@pytest.mark.parametrize("lang", ["javascript", "typescript", "tsx", "go", "rust", "java",
                                  "csharp", "c", "cpp"])
def test_never_raises_on_garbage(lang):
    samples = ["}}}} {{{{ ((((", "\"unterminated\n'x", "/* open comment", "`${`${",
               "r#\"never closed", "class", "fn", "func (", "@\"", "#define X \\\n{",
               "\x00\ufeff\u200b", "a" * 5000, "{" * 2000 + "}" * 2000]
    for s in samples:
        assert isinstance(names(s, lang), list)


# ---------------------------------------------------------------- QA round 1 regressions


QA1 = [
    # JSX self-closing tag after `}` is not a regex
    ("tsx", "export function A() {\n  return <p>{ok ? <B x={1} /> : null}</p>\n}\nexport function after() {}\n",
     [("A", 1), ("after", 4)]),
    # regex literal after `=>`
    ("javascript", "const isOpen = c => /[([{]/.test(c)\nfunction after() {}\n",
     [("isOpen", 1), ("after", 2)]),
    ("javascript", "const q = c => /[\"']/.test(c)\nfunction after() {}\n", [("q", 1), ("after", 2)]),
    # regex inside a template hole
    ("javascript", "const h = (s) => `${s.replace(/\"/g, '&quot;')}`\nfunction after() {}\nfunction after2() {}\n",
     [("h", 1), ("after", 2), ("after2", 3)]),
    ("javascript", "const h = (s) => `${s.replace(/`/g, '')}`\nfunction after() {}\n", [("h", 1), ("after", 2)]),
    # TS object types inside generics / unions
    ("typescript", "export const f = async (): Promise<{ a: number }> => {\n  return { a: 1 }\n}\n", [("f", 1)]),
    ("typescript", "const g = (): Array<{\n id: string\n}> => {\n  return []\n}\n", [("g", 1)]),
    ("typescript", "const h = (r: R): { ok: true } | { ok: false } => {\n  return r\n}\n", [("h", 1)]),
    ("typescript", "class A extends B<{ x: number }> {\n  m() {}\n}\n", [("A", 1), ("A.m", 2)]),
    ("typescript", "class A<T extends {}> {\n  m() {}\n}\n", [("A", 1), ("A.m", 2)]),
    ("typescript", "class Z {\n  pick<M extends util.Exactly<{ [k in keyof T]?: true }, M>>(mask: M) {\n  }\n}\n",
     [("Z", 1), ("Z.pick", 2)]),
    ("typescript", "class A {\n  m(): Promise<{ a: 1 }>;\n  m(x?: any) {}\n}\n", [("A", 1), ("A.m", 3)]),
    ("typescript", "export function f(): Array<{ a: 1 }>;\nexport function f() {}\n", [("f", 2)]),
    # method type parameter with a default
    ("typescript", "class A {\n  m<T = string>(x: T) {}\n  n<T = {}>() {}\n}\n", [("A", 1), ("A.m", 2), ("A.n", 3)]),
    # values that merely start with `(` are not arrow functions
    ("javascript", "const total = (items ?? []).reduce((a, b) => a + b, 0)\n"
                   "const unsub = (store).subscribe(() => { x() })\n"
                   "const f = (() => { return 1 })()\n"
                   "const real = (a, b) => a + b\n", [("real", 4)]),
    # unicode identifiers with combining marks / ZWNJ
    ("javascript", "const नमस्ते = () => 1\nfunction cafe\u0301() {}\nfunction a\u200cb() {}\n",
     [("नमस्ते", 1), ("cafe\u0301", 2), ("a\u200cb", 3)]),
    # line breaks after declaration keywords
    ("typescript", "export\nfunction\n  foo(\n) {}\n", [("foo", 3)]),
    ("typescript", "export abstract class\n  Foo\n  extends Bar {\n  m() {}\n}\n", [("Foo", 2), ("Foo.m", 4)]),
    # BOM passed directly
    ("javascript", "\ufefffunction f(){}\n", [("f", 1)]),
    ("python", "\ufeffdef f(): pass\n", [("f", 1)]),
    # Python: document order in try/except/else, name on a continued line
    ("python", "try:\n  def a(): pass\nexcept E:\n  def b(): pass\nelse:\n  def c(): pass\nfinally:\n  def d(): pass\n",
     [("a", 2), ("b", 4), ("c", 6), ("d", 8)]),
    ("python", "def \\\n    foo():\n    pass\nclass \\\n  Bar:\n  pass\n", [("foo", 2), ("Bar", 5)]),
]


@pytest.mark.parametrize("lang,src,expected", QA1, ids=[f"{c[0]}-{i}" for i, c in enumerate(QA1)])
def test_qa_round1(lang, src, expected):
    assert names(src, lang) == expected


def test_python_pathological_depth_is_syntax_error():
    with pytest.raises(SyntaxError):
        names("x = " + "+".join(["1"] * 200_000) + "\n", "python")
    with pytest.raises(SyntaxError):
        names("x = " + "-" * 200_000 + "1\n", "python")


def test_deep_templates_do_not_recurse():
    src = "x = " + "`${" * 2000 + "}`" * 2000 + "\nfunction after() {}\n"
    assert names(src, "javascript") == [("after", 2)]


@pytest.mark.parametrize("src", [
    "export const rows = [\n" + "{ id: 0, name: \"x\", tags: [\"a\"] },\n" * 40_000 + "]\n",
    "foo(" + "function(){}," * 40_000 + ")\n",
    "{" * 40_000 + "}" * 40_000,
], ids=["rows", "calls", "braces"])
def test_linear_time(src):
    import time
    start = time.perf_counter()
    names(src, "typescript")
    assert time.perf_counter() - start < 5


# ---------------------------------------------------------------- QA round 2 regressions

QA2 = [
    # Rust raw identifiers, generic const args, negative impls, shebang
    ("rust", "fn r#match() {}\nstruct r#Foo;\n", [("r#match", 1), ("r#Foo", 2)]),
    ("rust", "impl F<'x'> { fn f() {} }\n", [("F<'x'>", 1), ("F<'x'>.f", 1)]),
    ("rust", "impl Foo<{ 1 + 2 }> { fn f() {} }\n", [("Foo<{ 1 + 2 }>", 1), ("Foo<{ 1 + 2 }>.f", 1)]),
    ("rust", "impl !Send for X {}\n", [("X<!Send>", 1)]),
    ("rust", "#!/usr/bin/env rust-script\nfn main() {}\n", [("main", 2)]),
    # Go receivers without a name on generic types
    ("go", "package p\nfunc (List[T]) M() {}\nfunc (*Map[K, V]) N() {}\nfunc (l *List[T]) O() {}\n",
     [("List.M", 2), ("Map.N", 3), ("List.O", 4)]),
    # Java text block ending in an escaped backslash
    ("java", 'class A {\n  String s = """\n    x\\\\""";\n  void a() {}\n}\nclass B {\n  void b() {}\n}\n',
     [("A", 1), ("A.a", 4), ("B", 6), ("B.b", 7)]),
    # Java: static initializers and compact constructors are not class bodies
    ("java", 'class C {\n static {\n  LOG.info("x");\n  class L { void x(){} }\n }\n void m() {}\n}\n',
     [("C", 1), ("C.m", 6)]),
    ("java", "record R(int x) {\n R { Objects.requireNonNull(x); } }\n", [("R", 1)]),
    # Java: a call chained after an anonymous class body
    ("java", "class C {\n Object o = new Object() {\n }.toString();\n}\n", [("C", 1)]),
    # Java: method names that are C# accessor keywords, `? super`, annotations anywhere
    ("java", "class J {\n  Object get(int i) { return null; }\n  void add(int x) {}\n  void remove() {}\n"
             "  static <T> Comparator<? super T> cmp() { return null; }\n"
             "  public @Nullable String n() { return null; }\n  <T> @Nullable T t() { return null; }\n"
             "  List<@NonNull String> l() { return null; }\n}\n",
     [("J", 1), ("J.get", 2), ("J.add", 3), ("J.remove", 4), ("J.cmp", 5), ("J.n", 6), ("J.t", 7),
      ("J.l", 8)]),
    # Java: enum constant bodies after body-less constants
    ("java", "enum E { B, C { void c(){} }; }\n", [("E", 1), ("E.c", 1)]),
    ("java", "enum E { A(1), B(2) { void b(){} }; E(int v) {} }\n", [("E", 1), ("E.b", 1), ("E.E", 1)]),
    # C#: tuple and multidimensional array returns, function pointers
    ("csharp", "class C {\n  public (int a, int b) Pair() { return (1, 2); }\n  Task<(bool, string)> T2() => null;\n"
               "  List<(int X,int Y)> P() => null;\n  (int,int)? M() => null;\n  int[,] Grid() => null;\n"
               "  unsafe delegate*<int, void> F() => null;\n}\n",
     [("C", 1), ("C.Pair", 2), ("C.T2", 3), ("C.P", 4), ("C.M", 5), ("C.Grid", 6), ("C.F", 7)]),
    # C# 11: newline inside an interpolation hole
    ("csharp", 'class A {\n  string S() => $"{\n    1\n  }";\n  void M() {}\n}\nclass B { void N() {} }\n',
     [("A", 1), ("A.S", 2), ("A.M", 5), ("B", 7), ("B.N", 7)]),
    # BOM passed directly
    ("csharp", "﻿class C { void M() {} }\n", [("C", 1), ("C.M", 1)]),
]


@pytest.mark.parametrize("lang,src,expected", QA2, ids=[f"{c[0]}-{i}" for i, c in enumerate(QA2)])
def test_qa_round2(lang, src, expected):
    assert names(src, lang) == expected


def test_deep_csharp_interpolation_does_not_recurse():
    src = "class C { string s = " + '$"{' * 2000 + "1" + '}"' * 2000 + "; void M() {} }\n"
    assert names(src, "csharp") == [("C", 1), ("C.M", 1)]


@pytest.mark.parametrize("lang,src", [
    ("java", "enum E {\n" + 'A0(new String[]{"a"}, x -> { return x; }),\n' * 16_000 + "; }\n"),
    ("go", "package p\nvar x = f(" + "T{1}, " * 40_000 + ")\n"),
    ("java", "class C {\n" + "@A({1})\n" * 40_000 + "void m() {}\n}\n"),
    ("rust", "#[a]\n" * 40_000 + "fn f() {}\n"),
    ("csharp", "class C {\n" + "[A]\n" * 40_000 + "void M() {}\n}\n"),
], ids=["java-enum", "go-literals", "java-annotations", "rust-attrs", "cs-attrs"])
def test_linear_time_round2(lang, src):
    import time
    start = time.perf_counter()
    names(src, lang)
    assert time.perf_counter() - start < 5


# ---------------------------------------------------------------- QA round 3 regressions (C/C++)

QA3 = [
    # annotation macros after the parameter list
    ("cpp", "void f() GTEST_LOCK_EXCLUDED_(mu) {}\nint g(int x) const ABSL_LOCKS_EXCLUDED(m_) { return 0; }\n",
     [("f", 1), ("g", 2)]),
    # conversion operators whose type is not a single word
    ("cpp", "S::operator std::vector<int>() const {}\nS::operator unsigned int() const {}\n"
            "S::operator ns::T() {}\nS::operator const char*() const {}\nS::operator T&() {}\n",
     [("S::operator std::vector<int>", 1), ("S::operator unsigned int", 2), ("S::operator ns::T", 3),
      ("S::operator const char*", 4), ("S::operator T&", 5)]),
    ("cpp", "struct S {\n  operator std::pair<int,int>() { return {}; }\n};\n",
     [("S", 1), ("S.operator std::pair<int,int>", 2)]),
    # parenthesized declarators
    ("c", "int (*getfn(int x))(int) { return 0; }\nint (f)(void) { return 0; }\n", [("getfn", 1), ("f", 2)]),
    ("cpp", "int(test::fileno)(FILE* stream) { return 0; }\n", [("test::fileno", 1)]),
    # function-try-block constructor
    ("cpp", "A::A() try : x(1) { } catch (...) { }\n", [("A::A", 1)]),
    # macro invocation before an enum; macro after the class name
    ("cpp", 'FMT_PRAGMA_CLANG(diagnostic error "-W")\nFMT_BEGIN_NAMESPACE\nFMT_EXPORT\n'
            "enum class range_format { disabled };\nint after() { return 0; }\n", [("after", 5)]),
    ("cpp", "class Foo MY_FINAL { void m() {} };\n", [("Foo", 1), ("Foo.m", 1)]),
    # user-defined literal operator
    ("cpp", 'auto operator""_a(const char* s, size_t) { return 0; }\n', [('operator""_a', 1)]),
    # operator new[] / delete[] / comma
    ("cpp", "void* operator new[](size_t n) { return 0; }\nS operator,(S a, S b) { return a; }\n",
     [("operator new[]", 1), ("operator,", 2)]),
    # qualified class names
    ("cpp", "struct A::C { void m() {} };\n", [("A::C", 1), ("A::C.m", 1)]),
    # #if / #else branches that each open a brace
    ("c", "int f(int a) {\n#ifdef X\n  if (a) {\n#else\n  if (!a) {\n#endif\n    return 1;\n  }\n  return 0;\n}\n"
          "int after(void) { return 0; }\n", [("f", 1), ("after", 11)]),
    ("cpp", "#if A\nclass X : public B {\n#else\nclass X {\n#endif\n void m() {}\n};\nint after() { return 0; }\n",
     [("X", 2), ("X.m", 6), ("after", 8)]),
    # character literal with an encoding prefix is not a digit separator
    ("cpp", "void f() { auto c = u8'{'; auto d = L'{'; }\nint after() { return 0; }\n", [("f", 1), ("after", 2)]),
    ("c", "void f(int c) { switch (c) { case'{': break; } }\nint after(void) { return 0; }\n",
     [("f", 1), ("after", 2)]),
    # preprocessor line ending inside an open block comment
    ("c", "#define FOO 1 /* comment\n   spans { lines */\nint after(void) { return 0; }\n", [("after", 3)]),
    # `// comment \` continues onto the next line
    ("c", "// note \\\nint hidden(void) { return 0; }\nint real(void) { return 0; }\n", [("real", 3)]),
]


@pytest.mark.parametrize("lang,src,expected", QA3, ids=[f"{c[0]}-{i}" for i, c in enumerate(QA3)])
def test_qa_round3(lang, src, expected):
    assert names(src, lang) == expected


def test_c_file_is_never_switched_to_cpp(tmp_path):
    f = tmp_path / "linker.c"
    f.write_text("/* see $data::data */\nstruct lib_entry { int a; };\nint f(void) { return 0; }\n",
                 encoding="utf-8")
    assert extract_symbols(f) == [("f", 3)]


def test_cpp_init_list_linear_time():
    import time
    src = "C::C() : " + ", ".join(f"a{i}{{{i}}}" for i in range(8000)) + " {}\n"
    start = time.perf_counter()
    assert names(src, "cpp") == [("C::C", 1)]
    assert time.perf_counter() - start < 5


# ---------------------------------------------------------------- QA re-verification regressions

QA1B = [
    ("typescript", 'export function f(x: any): "set" | "map" {\n  return "set"\n}\nfunction after() {}\n',
     [("f", 1), ("after", 4)]),
    ("typescript", "class K {\n  m(): 'a' | 'b' {\n    return 'a'\n  }\n}\n", [("K", 1), ("K.m", 2)]),
    ("typescript", "function g(): X & 'a' {\n  return x\n}\n", [("g", 1)]),
    ("javascript", "const x = require('y').default\nfunction f() {}\n", [("f", 2)]),
    ("javascript", "const s = opts.static\nconst a = opts.async\nexport function f() {}\n", [("f", 3)]),
]


@pytest.mark.parametrize("lang,src,expected", QA1B, ids=[f"{c[0]}-{i}" for i, c in enumerate(QA1B)])
def test_qa_reverify_js(lang, src, expected):
    assert names(src, lang) == expected


QA2B = [
    ("java", "class C {\n  BiFunction<A, B, R> f = new BiFunction<A, B, R>() {\n    public R apply(A a, B b) { return null; }\n  };\n}\n",
     [("C", 1), ("C.apply", 3)]),
    ("rust", "impl Foo</* c */T> { fn f(){} }\n", [("Foo<T>", 1), ("Foo<T>.f", 1)]),
    ("rust", "impl<T> Tr for Foo<\n    T, // the element\n> {\n    fn f() {}\n}\n", [("Foo< T, ><Tr>", 1), ("Foo< T, ><Tr>.f", 4)]),
    ("csharp", "class C {\n#if X\n  /*\n   if (a) {\n  */\n  void A() {}\n#else\n  void B() {}\n#endif\n}\n",
     [("C", 1), ("C.A", 6), ("C.B", 8)]),
    ("csharp", 'class C {\n  string s = $"{a /* { */}";\n  void M() {}\n}\n', [("C", 1), ("C.M", 3)]),
    ("java", "class C {\n  T delegate() { return null; }\n  Object o = new Object() {}.x.y();\n}\n",
     [("C", 1), ("C.delegate", 2)]),
]


@pytest.mark.parametrize("lang,src,expected", QA2B, ids=[f"{c[0]}-{i}" for i, c in enumerate(QA2B)])
def test_qa_reverify_jvm(lang, src, expected):
    assert names(src, lang) == expected


QA3B = [
    ("cpp", "void A:: /* c */ m() {}\nbool operator /*x*/ == (A, A) { return 1; }\n",
     [("A::m", 1), ("operator==", 2)]),
    ("cpp", "void B::// x\nn() {}\n", [("B::n", 1)]),
    ("cpp", "template <> struct hash<Foo /* c */> { void f() {} };\n", [("hash<Foo >", 1), ("hash<Foo >.f", 1)]),
    ("c", '#define S "/*"\nvoid f(void) {}\nint after(void) { return 0; }\n', [("f", 2), ("after", 3)]),
    ("c", "#define C '/*'\n#include \"a/*b.h\"\nint after(void) { return 0; }\n", [("after", 3)]),
    ("c", "void f(void) ACQUIRE(m) {}\nvoid MY_FUNC(int a) LOCK_REQUIRED(m) {}\n", [("f", 1), ("MY_FUNC", 2)]),
]


@pytest.mark.parametrize("lang,src,expected", QA3B, ids=[f"{c[0]}-{i}" for i, c in enumerate(QA3B)])
def test_qa_reverify_c(lang, src, expected):
    assert names(src, lang) == expected


def test_macro_series_linear_time():
    import time
    src = "DECLARE_THING(x)\n" * 16_000 + "void f() {}\n"
    start = time.perf_counter()
    assert names(src, "cpp")[-1] == ("f", 16_001)
    assert time.perf_counter() - start < 5


def test_h_detection_ignores_comments(tmp_path):
    f = tmp_path / "s.h"
    f.write_text("// see std::vector\nstruct S { int a; };\nint g(void) { return 0; }\n", encoding="utf-8")
    assert extract_symbols(f) == [("g", 3)]
