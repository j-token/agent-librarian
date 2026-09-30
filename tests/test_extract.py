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
        ("only_typing", 3, 3), ("handler", 7, 9), ("A", 11, 15), ("A.maybe", 13, 13),
        ("A.fallback", 15, 15)]


def test_python_syntax_error_raises(tmp_path):
    f = tmp_path / "bad.py"
    f.write_text("def broken(:\n", encoding="utf-8")
    with pytest.raises(SyntaxError):
        extract_symbols(f)


def test_bom_and_crlf(tmp_path):
    f = tmp_path / "w.py"
    f.write_bytes("\ufeffimport os\r\n\r\ndef f():\r\n    pass\r\n".encode("utf-8"))
    assert extract_symbols(f) == [("f", 3, 4)]
    g = tmp_path / "w.ts"
    g.write_bytes(b"// c\r\nexport function g() {\r\n}\r\nclass K {\r\n  m() {}\r\n}\r\n")
    assert extract_symbols(g) == [("g", 2, 3), ("K", 4, 6), ("K.m", 5, 5)]


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
    assert names(src, "javascript") == [("real", 6, 8)]


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
    assert names(src, "javascript") == [("f", 4, 4), ("h", 5, 5), ("k", 6, 8), ("g", 10, 10)]


@pytest.mark.parametrize("lang", ["javascript", "typescript", "tsx"])
def test_js_test_callbacks_have_titles_and_exact_body_ranges(lang):
    src = (
        "test('한국어 테스트', async ({\n"
        "  game\n"
        "}) => {\n"
        "  const ignored = () => {};\n"
        "  if (game) { game.run({ value: '}' }); }\n"
        "});\n"
        "it(\n"
        '  "second test",\n'
        "  function (done) {\n"
        "    done();\n"
        "  }\n"
        ");\n"
        "test(`static title`, async function () {\n"
        "  await run();\n"
        "});\n"
        "const runTest = async () => {\n"
        "  await run();\n"
        "};\n"
        "function named() {}\n"
    )
    assert names(src, lang) == [
        ("test('한국어 테스트')", 1, 6), ('it("second test")', 7, 11),
        ("test(`static title`)", 13, 15), ("runTest", 16, 18), ("named", 19, 19)]


@pytest.mark.parametrize("callee", [
    "test", "it", "test.only", "test.skip", "test.fixme", "test.fail", "it.fails",
    "test.concurrent.only", "it.sequential.skip"])
def test_js_test_modifiers_keep_the_callee_and_title(callee):
    assert names(f"{callee}('case', () => {{\n  run();\n}});\n", "javascript") == [
        (f"{callee}('case')", 1, 3)]


@pytest.mark.parametrize("callee", [
    "describe", "describe.only", "describe.skip", "describe.concurrent",
    "describe.sequential", "test.describe", "test.describe.serial.only", "test.describe.parallel"])
def test_js_suites_expose_nested_tests_and_close_at_their_own_brace(callee):
    src = (
        f"{callee}('suite', () => {{\n"
        "  describe('nested', function () {\n"
        "    it('one', () => { run(); });\n"
        "  });\n"
        "  test('two', async () => {\n"
        "    await run();\n"
        "  });\n"
        "});\n"
        "function after() {}\n"
    )
    assert names(src, "typescript") == [
        (f"{callee}('suite')", 1, 8), ("describe('nested')", 2, 4),
        ("it('one')", 3, 3), ("test('two')", 5, 7), ("after", 9, 9)]


def test_ts_test_details_comments_and_callback_types_keep_body_ranges():
    src = (
        "test /* before title */ (\n"
        "  /* title */ 'typed', /* details */\n"
        "  { tag: ['@smoke'], annotation: { type: 'issue' } },\n"
        "  async ({ game }: { game: Game }): Promise<void> => {\n"
        "    await game.run();\n"
        "  },\n"
        ");\n"
        "test('plain', done => { done(); }, 1000);\n"
    )
    assert names(src, "typescript") == [
        ("test('typed')", 1, 6), ("test('plain')", 8, 8)]


@pytest.mark.parametrize("lang", ["typescript", "tsx"])
@pytest.mark.parametrize("signature", [
    "function (): void", "async function (): Promise<void>",
    "function (): { value: number }", "async function (): Promise<{ value: number }>",
    "function (): { value: number } | { error: string }"])
def test_ts_test_function_return_annotations_do_not_open_the_callback_early(lang, signature):
    src = (
        f"test('typed function', {signature} {{\n"
        "  run();\n"
        "});\n"
        "function after() {}\n"
    )
    assert names(src, lang) == [
        ("test('typed function')", 1, 3), ("after", 4, 4)]


@pytest.mark.parametrize("src", [
    "run('ordinary', () => {});",
    "testName('ordinary', () => {});",
    "obj.test('ordinary', () => {});",
    "obj.describe('ordinary', () => { test('hidden', () => {}); });",
    "run(test('nested argument', () => {}));",
    "test.beforeEach('setup', () => {});",
    "test.describe.configure('settings', () => {});",
    "test.unknown('ordinary', () => {});",
    "test.skip(true, 'reason');",
    "test(title, () => {});",
    "test('prefix' + suffix, () => {});",
    "test(`${title}`, () => {});",
    "test('callback reference', callback);",
    "test('computed callback', makeCallback(() => {}));",
    "test('named callback', function named() {});",
    "test.each([1, 2])('parameterized', () => {});",
    "test('expression body', () => run());",
    "// test('comment', () => {})\n/* it('comment', () => {}) */",
    'const example = "test(\'string\', () => {})";',
])
def test_js_ordinary_callbacks_and_unsupported_test_forms_are_not_indexed(src):
    assert names(src + "\nfunction after() {}\n", "javascript") == [
        ("after", src.count("\n") + 2, src.count("\n") + 2)]


def test_js_test_title_escapes_do_not_change_callback_brace_matching():
    src = r'''test('it\'s { escaped }', () => {});''' + "\n"
    assert names(src, "javascript") == [(r"test('it\'s { escaped }')", 1, 1)]


def test_js_multiline_test_callee_and_literal_preserve_the_title_and_call_start():
    src = (
        "test\n"
        "  .only\n"
        "  (\n"
        "    'keeps  two spaces',\n"
        "    () => {\n"
        "      run();\n"
        "    }\n"
        "  );\n"
        "it\n"
        "(\n"
        "  `multiple\n"
        "lines`, () => {});\n"
    )
    assert names(src, "typescript") == [
        ("test.only('keeps  two spaces')", 1, 7), ("it(`multiple lines`)", 9, 12)]


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
        ("Store", 1, 9), ("Store.size", 5, 5), ("Store.items", 6, 6), ("Store.#secret", 7, 7),
        ("data", 11, 11), ("save", 13, 13)]


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
        ("Props", 1, 1), ("Color", 2, 2), ("typed", 4, 6), ("Card", 7, 9), ("Repo", 10, 14),
        ("Repo.save", 12, 12), ("Repo.opt", 13, 13), ("inner", 15, 15)]


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
        ("ID", 5, 5), ("User", 6, 8), ("List", 10, 10), ("List.Push", 11, 11), ("New", 12, 15),
        ("asm", 16, 16)]


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
        ("tests", 2, 2), ("Unit", 3, 3), ("P", 4, 4), ("P<'a>", 5, 7), ("P<'a>.new", 6, 6),
        ("P<'_><fmt::Display>", 8, 10), ("P<'_><fmt::Display>.fmt", 9, 9), ("Shape", 11, 14),
        ("Shape.area", 12, 12), ("Shape.name", 13, 13), ("c_func", 16, 16), ("run", 20, 20)]


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
        ("Svc", 2, 19), ("Svc.anon", 5, 5), ("Svc.Svc", 8, 8), ("Svc.map", 9, 11),
        ("Svc.todo", 12, 12), ("Svc.Kind", 14, 14), ("Svc.Kind.over", 14, 14),
        ("Svc.Kind.Kind", 14, 14), ("Svc.Pair", 18, 18)]


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
        ("Repo", 4, 16), ("Repo.Repo", 8, 8), ("Repo.Add", 9, 9), ("Repo.AllAsync", 12, 12),
        ("Repo.Dispose", 13, 13), ("Point", 17, 17), ("Color", 18, 18), ("IRepo", 19, 19),
        ("IRepo.Save", 19, 19)]


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
    assert names(src, "c") == [("make_point", 5, 5), ("main", 7, 10), ("helper", 11, 11)]


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
        ("Widget", 4, 14), ("Widget.Widget", 6, 6), ("Widget.~Widget", 7, 7),
        ("Widget.operator==", 8, 8), ("Widget.operator bool", 9, 9), ("Widget.size", 10, 10),
        ("Widget.Inner", 13, 13), ("Widget.Inner.f", 13, 13), ("Widget::declared", 15, 15),
        ("hash<Widget>", 16, 16), ("hash<Widget>.operator()", 16, 16), ("c_api", 18, 18)]


def test_cpp_header_with_h_extension(tmp_path):
    f = tmp_path / "w.h"
    f.write_text("namespace n {\nclass K { void m() {} };\n}\n", encoding="utf-8")
    assert extract_symbols(f) == [("K", 2, 2), ("K.m", 2, 2)]


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
     [("A", 1, 3), ("after", 4, 4)]),
    # regex literal after `=>`
    ("javascript", "const isOpen = c => /[([{]/.test(c)\nfunction after() {}\n",
     [("isOpen", 1, 1), ("after", 2, 2)]),
    ("javascript", "const q = c => /[\"']/.test(c)\nfunction after() {}\n",
     [("q", 1, 1), ("after", 2, 2)]),
    # regex inside a template hole
    ("javascript", "const h = (s) => `${s.replace(/\"/g, '&quot;')}`\nfunction after() {}\nfunction after2() {}\n",
     [("h", 1, 1), ("after", 2, 2), ("after2", 3, 3)]),
    ("javascript", "const h = (s) => `${s.replace(/`/g, '')}`\nfunction after() {}\n",
     [("h", 1, 1), ("after", 2, 2)]),
    # TS object types inside generics / unions
    ("typescript", "export const f = async (): Promise<{ a: number }> => {\n  return { a: 1 }\n}\n",
     [("f", 1, 3)]),
    ("typescript", "const g = (): Array<{\n id: string\n}> => {\n  return []\n}\n", [("g", 1, 5)]),
    ("typescript", "const h = (r: R): { ok: true } | { ok: false } => {\n  return r\n}\n", [("h", 1, 3)]),
    ("typescript", "class A extends B<{ x: number }> {\n  m() {}\n}\n", [("A", 1, 3), ("A.m", 2, 2)]),
    ("typescript", "class A<T extends {}> {\n  m() {}\n}\n", [("A", 1, 3), ("A.m", 2, 2)]),
    ("typescript", "class Z {\n  pick<M extends util.Exactly<{ [k in keyof T]?: true }, M>>(mask: M) {\n  }\n}\n",
     [("Z", 1, 4), ("Z.pick", 2, 3)]),
    ("typescript", "class A {\n  m(): Promise<{ a: 1 }>;\n  m(x?: any) {}\n}\n", [("A", 1, 4), ("A.m", 3, 3)]),
    ("typescript", "export function f(): Array<{ a: 1 }>;\nexport function f() {}\n", [("f", 2, 2)]),
    # method type parameter with a default
    ("typescript", "class A {\n  m<T = string>(x: T) {}\n  n<T = {}>() {}\n}\n",
     [("A", 1, 4), ("A.m", 2, 2), ("A.n", 3, 3)]),
    # values that merely start with `(` are not arrow functions
    ("javascript", "const total = (items ?? []).reduce((a, b) => a + b, 0)\n"
                   "const unsub = (store).subscribe(() => { x() })\n"
                   "const f = (() => { return 1 })()\n"
                   "const real = (a, b) => a + b\n", [("real", 4, 4)]),
    # unicode identifiers with combining marks / ZWNJ
    ("javascript", "const नमस्ते = () => 1\nfunction cafe\u0301() {}\nfunction a\u200cb() {}\n",
     [("नमस्ते", 1, 1), ("cafe\u0301", 2, 2), ("a\u200cb", 3, 3)]),
    # line breaks after declaration keywords
    ("typescript", "export\nfunction\n  foo(\n) {}\n", [("foo", 3, 4)]),
    ("typescript", "export abstract class\n  Foo\n  extends Bar {\n  m() {}\n}\n",
     [("Foo", 2, 5), ("Foo.m", 4, 4)]),
    # BOM passed directly
    ("javascript", "\ufefffunction f(){}\n", [("f", 1, 1)]),
    ("python", "\ufeffdef f(): pass\n", [("f", 1, 1)]),
    # Python: document order in try/except/else, name on a continued line
    ("python", "try:\n  def a(): pass\nexcept E:\n  def b(): pass\nelse:\n  def c(): pass\nfinally:\n  def d(): pass\n",
     [("a", 2, 2), ("b", 4, 4), ("c", 6, 6), ("d", 8, 8)]),
    ("python", "def \\\n    foo():\n    pass\nclass \\\n  Bar:\n  pass\n", [("foo", 2, 3), ("Bar", 5, 6)]),
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
    assert names(src, "javascript") == [("after", 2, 2)]


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
    ("rust", "fn r#match() {}\nstruct r#Foo;\n", [("r#match", 1, 1), ("r#Foo", 2, 2)]),
    ("rust", "impl F<'x'> { fn f() {} }\n", [("F<'x'>", 1, 1), ("F<'x'>.f", 1, 1)]),
    ("rust", "impl Foo<{ 1 + 2 }> { fn f() {} }\n",
     [("Foo<{ 1 + 2 }>", 1, 1), ("Foo<{ 1 + 2 }>.f", 1, 1)]),
    ("rust", "impl !Send for X {}\n", [("X<!Send>", 1, 1)]),
    ("rust", "#!/usr/bin/env rust-script\nfn main() {}\n", [("main", 2, 2)]),
    # Go receivers without a name on generic types
    ("go", "package p\nfunc (List[T]) M() {}\nfunc (*Map[K, V]) N() {}\nfunc (l *List[T]) O() {}\n",
     [("List.M", 2, 2), ("Map.N", 3, 3), ("List.O", 4, 4)]),
    # Java text block ending in an escaped backslash
    ("java", 'class A {\n  String s = """\n    x\\\\""";\n  void a() {}\n}\nclass B {\n  void b() {}\n}\n',
     [("A", 1, 5), ("A.a", 4, 4), ("B", 6, 8), ("B.b", 7, 7)]),
    # Java: static initializers and compact constructors are not class bodies
    ("java", 'class C {\n static {\n  LOG.info("x");\n  class L { void x(){} }\n }\n void m() {}\n}\n',
     [("C", 1, 7), ("C.m", 6, 6)]),
    ("java", "record R(int x) {\n R { Objects.requireNonNull(x); } }\n", [("R", 1, 2)]),
    # Java: a call chained after an anonymous class body
    ("java", "class C {\n Object o = new Object() {\n }.toString();\n}\n", [("C", 1, 4)]),
    # Java: method names that are C# accessor keywords, `? super`, annotations anywhere
    ("java", "class J {\n  Object get(int i) { return null; }\n  void add(int x) {}\n  void remove() {}\n"
             "  static <T> Comparator<? super T> cmp() { return null; }\n"
             "  public @Nullable String n() { return null; }\n  <T> @Nullable T t() { return null; }\n"
             "  List<@NonNull String> l() { return null; }\n}\n",
     [("J", 1, 9), ("J.get", 2, 2), ("J.add", 3, 3), ("J.remove", 4, 4), ("J.cmp", 5, 5),
      ("J.n", 6, 6), ("J.t", 7, 7), ("J.l", 8, 8)]),
    # Java: enum constant bodies after body-less constants
    ("java", "enum E { B, C { void c(){} }; }\n", [("E", 1, 1), ("E.c", 1, 1)]),
    ("java", "enum E { A(1), B(2) { void b(){} }; E(int v) {} }\n",
     [("E", 1, 1), ("E.b", 1, 1), ("E.E", 1, 1)]),
    # C#: tuple and multidimensional array returns, function pointers
    ("csharp", "class C {\n  public (int a, int b) Pair() { return (1, 2); }\n  Task<(bool, string)> T2() => null;\n"
               "  List<(int X,int Y)> P() => null;\n  (int,int)? M() => null;\n  int[,] Grid() => null;\n"
               "  unsafe delegate*<int, void> F() => null;\n}\n",
     [("C", 1, 8), ("C.Pair", 2, 2), ("C.T2", 3, 3), ("C.P", 4, 4), ("C.M", 5, 5),
      ("C.Grid", 6, 6), ("C.F", 7, 7)]),
    # C# 11: newline inside an interpolation hole
    ("csharp", 'class A {\n  string S() => $"{\n    1\n  }";\n  void M() {}\n}\nclass B { void N() {} }\n',
     [("A", 1, 6), ("A.S", 2, 4), ("A.M", 5, 5), ("B", 7, 7), ("B.N", 7, 7)]),
    # BOM passed directly
    ("csharp", "﻿class C { void M() {} }\n", [("C", 1, 1), ("C.M", 1, 1)]),
]


@pytest.mark.parametrize("lang,src,expected", QA2, ids=[f"{c[0]}-{i}" for i, c in enumerate(QA2)])
def test_qa_round2(lang, src, expected):
    assert names(src, lang) == expected


def test_deep_csharp_interpolation_does_not_recurse():
    src = "class C { string s = " + '$"{' * 2000 + "1" + '}"' * 2000 + "; void M() {} }\n"
    assert names(src, "csharp") == [("C", 1, 1), ("C.M", 1, 1)]


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
     [("f", 1, 1), ("g", 2, 2)]),
    # conversion operators whose type is not a single word
    ("cpp", "S::operator std::vector<int>() const {}\nS::operator unsigned int() const {}\n"
            "S::operator ns::T() {}\nS::operator const char*() const {}\nS::operator T&() {}\n",
     [("S::operator std::vector<int>", 1, 1), ("S::operator unsigned int", 2, 2),
      ("S::operator ns::T", 3, 3), ("S::operator const char*", 4, 4), ("S::operator T&", 5, 5)]),
    ("cpp", "struct S {\n  operator std::pair<int,int>() { return {}; }\n};\n",
     [("S", 1, 3), ("S.operator std::pair<int,int>", 2, 2)]),
    # parenthesized declarators
    ("c", "int (*getfn(int x))(int) { return 0; }\nint (f)(void) { return 0; }\n",
     [("getfn", 1, 1), ("f", 2, 2)]),
    ("cpp", "int(test::fileno)(FILE* stream) { return 0; }\n", [("test::fileno", 1, 1)]),
    # function-try-block constructor
    ("cpp", "A::A() try : x(1) { } catch (...) { }\n", [("A::A", 1, 1)]),
    # macro invocation before an enum; macro after the class name
    ("cpp", 'FMT_PRAGMA_CLANG(diagnostic error "-W")\nFMT_BEGIN_NAMESPACE\nFMT_EXPORT\n'
            "enum class range_format { disabled };\nint after() { return 0; }\n", [("after", 5, 5)]),
    ("cpp", "class Foo MY_FINAL { void m() {} };\n", [("Foo", 1, 1), ("Foo.m", 1, 1)]),
    # user-defined literal operator
    ("cpp", 'auto operator""_a(const char* s, size_t) { return 0; }\n', [('operator""_a', 1, 1)]),
    # operator new[] / delete[] / comma
    ("cpp", "void* operator new[](size_t n) { return 0; }\nS operator,(S a, S b) { return a; }\n",
     [("operator new[]", 1, 1), ("operator,", 2, 2)]),
    # qualified class names
    ("cpp", "struct A::C { void m() {} };\n", [("A::C", 1, 1), ("A::C.m", 1, 1)]),
    # #if / #else branches that each open a brace
    ("c", "int f(int a) {\n#ifdef X\n  if (a) {\n#else\n  if (!a) {\n#endif\n    return 1;\n  }\n  return 0;\n}\n"
          "int after(void) { return 0; }\n", [("f", 1, 10), ("after", 11, 11)]),
    ("cpp", "#if A\nclass X : public B {\n#else\nclass X {\n#endif\n void m() {}\n};\nint after() { return 0; }\n",
     [("X", 2, 7), ("X.m", 6, 6), ("after", 8, 8)]),
    # character literal with an encoding prefix is not a digit separator
    ("cpp", "void f() { auto c = u8'{'; auto d = L'{'; }\nint after() { return 0; }\n",
     [("f", 1, 1), ("after", 2, 2)]),
    ("c", "void f(int c) { switch (c) { case'{': break; } }\nint after(void) { return 0; }\n",
     [("f", 1, 1), ("after", 2, 2)]),
    # preprocessor line ending inside an open block comment
    ("c", "#define FOO 1 /* comment\n   spans { lines */\nint after(void) { return 0; }\n",
     [("after", 3, 3)]),
    # `// comment \` continues onto the next line
    ("c", "// note \\\nint hidden(void) { return 0; }\nint real(void) { return 0; }\n",
     [("real", 3, 3)]),
]


@pytest.mark.parametrize("lang,src,expected", QA3, ids=[f"{c[0]}-{i}" for i, c in enumerate(QA3)])
def test_qa_round3(lang, src, expected):
    assert names(src, lang) == expected


def test_c_file_is_never_switched_to_cpp(tmp_path):
    f = tmp_path / "linker.c"
    f.write_text("/* see $data::data */\nstruct lib_entry { int a; };\nint f(void) { return 0; }\n",
                 encoding="utf-8")
    assert extract_symbols(f) == [("f", 3, 3)]


def test_cpp_init_list_linear_time():
    import time
    src = "C::C() : " + ", ".join(f"a{i}{{{i}}}" for i in range(8000)) + " {}\n"
    start = time.perf_counter()
    assert names(src, "cpp") == [("C::C", 1, 1)]
    assert time.perf_counter() - start < 5


# ---------------------------------------------------------------- QA re-verification regressions

QA1B = [
    ("typescript", 'export function f(x: any): "set" | "map" {\n  return "set"\n}\nfunction after() {}\n',
     [("f", 1, 3), ("after", 4, 4)]),
    ("typescript", "class K {\n  m(): 'a' | 'b' {\n    return 'a'\n  }\n}\n", [("K", 1, 5), ("K.m", 2, 4)]),
    ("typescript", "function g(): X & 'a' {\n  return x\n}\n", [("g", 1, 3)]),
    ("javascript", "const x = require('y').default\nfunction f() {}\n", [("f", 2, 2)]),
    ("javascript", "const s = opts.static\nconst a = opts.async\nexport function f() {}\n", [("f", 3, 3)]),
]


@pytest.mark.parametrize("lang,src,expected", QA1B, ids=[f"{c[0]}-{i}" for i, c in enumerate(QA1B)])
def test_qa_reverify_js(lang, src, expected):
    assert names(src, lang) == expected


QA2B = [
    ("java", "class C {\n  BiFunction<A, B, R> f = new BiFunction<A, B, R>() {\n    public R apply(A a, B b) { return null; }\n  };\n}\n",
     [("C", 1, 5), ("C.apply", 3, 3)]),
    ("rust", "impl Foo</* c */T> { fn f(){} }\n", [("Foo<T>", 1, 1), ("Foo<T>.f", 1, 1)]),
    ("rust", "impl<T> Tr for Foo<\n    T, // the element\n> {\n    fn f() {}\n}\n",
     [("Foo< T, ><Tr>", 1, 5), ("Foo< T, ><Tr>.f", 4, 4)]),
    ("csharp", "class C {\n#if X\n  /*\n   if (a) {\n  */\n  void A() {}\n#else\n  void B() {}\n#endif\n}\n",
     [("C", 1, 10), ("C.A", 6, 6), ("C.B", 8, 8)]),
    ("csharp", 'class C {\n  string s = $"{a /* { */}";\n  void M() {}\n}\n', [("C", 1, 4), ("C.M", 3, 3)]),
    ("java", "class C {\n  T delegate() { return null; }\n  Object o = new Object() {}.x.y();\n}\n",
     [("C", 1, 4), ("C.delegate", 2, 2)]),
]


@pytest.mark.parametrize("lang,src,expected", QA2B, ids=[f"{c[0]}-{i}" for i, c in enumerate(QA2B)])
def test_qa_reverify_jvm(lang, src, expected):
    assert names(src, lang) == expected


QA3B = [
    ("cpp", "void A:: /* c */ m() {}\nbool operator /*x*/ == (A, A) { return 1; }\n",
     [("A::m", 1, 1), ("operator==", 2, 2)]),
    ("cpp", "void B::// x\nn() {}\n", [("B::n", 1, 2)]),
    ("cpp", "template <> struct hash<Foo /* c */> { void f() {} };\n",
     [("hash<Foo >", 1, 1), ("hash<Foo >.f", 1, 1)]),
    ("c", '#define S "/*"\nvoid f(void) {}\nint after(void) { return 0; }\n', [("f", 2, 2), ("after", 3, 3)]),
    ("c", "#define C '/*'\n#include \"a/*b.h\"\nint after(void) { return 0; }\n", [("after", 3, 3)]),
    ("c", "void f(void) ACQUIRE(m) {}\nvoid MY_FUNC(int a) LOCK_REQUIRED(m) {}\n",
     [("f", 1, 1), ("MY_FUNC", 2, 2)]),
]


@pytest.mark.parametrize("lang,src,expected", QA3B, ids=[f"{c[0]}-{i}" for i, c in enumerate(QA3B)])
def test_qa_reverify_c(lang, src, expected):
    assert names(src, lang) == expected


def test_macro_series_linear_time():
    import time
    src = "DECLARE_THING(x)\n" * 16_000 + "void f() {}\n"
    start = time.perf_counter()
    assert names(src, "cpp")[-1] == ("f", 16_001, 16_001)
    assert time.perf_counter() - start < 5


def test_h_detection_ignores_comments(tmp_path):
    f = tmp_path / "s.h"
    f.write_text("// see std::vector\nstruct S { int a; };\nint g(void) { return 0; }\n", encoding="utf-8")
    assert extract_symbols(f) == [("g", 3, 3)]


# ---------------------------------------------------------------- end lines


def test_end_lines_python():
    src = (
        "@cache\n"
        "def cached(x):\n"
        "    y = x\n"
        "    return y\n"
        "\n"
        "class Box:\n"
        "    def get(self):\n"
        "        return 1\n"
        "\n"
        "    size = 2\n"
    )
    assert names(src, "python") == [("cached", 2, 4), ("Box", 6, 10), ("Box.get", 7, 8)]


def test_end_lines_js_function_and_method():
    src = (
        "function load(url) {\n"
        "  if (url) {\n"
        "    return fetch(url)\n"
        "  }\n"
        "}\n"
        "class Cache {\n"
        "  get(key) {\n"
        "    return this.map[key]\n"
        "  }\n"
        "}\n"
    )
    assert names(src, "javascript") == [("load", 1, 5), ("Cache", 6, 10), ("Cache.get", 7, 9)]


def test_end_lines_ts_arrow_consts():
    src = (
        "export const add = (a: number, b: number): number =>\n"
        "  a + b\n"
        "const scale = (x: number) => {\n"
        "  return x * 2\n"
        "}\n"
        "const one = () => 1;\n"
    )
    assert names(src, "typescript") == [("add", 1, 2), ("scale", 3, 5), ("one", 6, 6)]


def test_end_lines_go_method_and_bodiless_type():
    src = (
        "package p\n"
        "\n"
        "type ID int\n"
        "\n"
        "func (s *Server) Start(\n"
        "\tport int,\n"
        ") error {\n"
        "\treturn nil\n"
        "}\n"
    )
    assert names(src, "go") == [("ID", 3, 3), ("Server.Start", 5, 9)]


def test_end_lines_rust_trait_and_impl():
    src = (
        "trait Shape {\n"
        "    fn area(&self)\n"
        "        -> f64;\n"
        "}\n"
        "impl Shape for Sq {\n"
        "    fn area(&self) -> f64 {\n"
        "        1.0\n"
        "    }\n"
        "}\n"
    )
    assert names(src, "rust") == [
        ("Shape", 1, 4), ("Shape.area", 2, 3), ("Sq<Shape>", 5, 9), ("Sq<Shape>.area", 6, 8)]


def test_end_lines_java_methods():
    src = (
        "class Svc {\n"
        "  void run(\n"
        "      int n) {\n"
        "    work();\n"
        "  }\n"
        "  abstract void stop();\n"
        "}\n"
    )
    assert names(src, "java") == [("Svc", 1, 7), ("Svc.run", 2, 5), ("Svc.stop", 6, 6)]


def test_end_lines_csharp_methods():
    src = (
        "class K\n"
        "{\n"
        "    public int Twice(int x)\n"
        "    {\n"
        "        return x * 2;\n"
        "    }\n"
        "    public int Add(int a, int b) =>\n"
        "        a + b;\n"
        "}\n"
    )
    assert names(src, "csharp") == [("K", 1, 9), ("K.Twice", 3, 6), ("K.Add", 7, 8)]


def test_end_lines_cpp_class_and_function():
    src = (
        "class Box {\n"
        " public:\n"
        "  int get() const;\n"
        "};\n"
        "int Box::get() const\n"
        "{\n"
        "  return 1;\n"
        "}\n"
    )
    assert names(src, "cpp") == [("Box", 1, 4), ("Box::get", 5, 8)]


def test_end_lines_nested_bodies():
    js = (
        "function outer() {\n"
        "  function inner() {\n"
        "  }\n"
        "  return inner\n"
        "}\n"
    )
    assert names(js, "javascript") == [("outer", 1, 5)]
    java = (
        "class Outer {\n"
        "  class Inner {\n"
        "    void m() {\n"
        "    }\n"
        "  }\n"
        "}\n"
    )
    assert names(java, "java") == [("Outer", 1, 6), ("Outer.Inner", 2, 5), ("Outer.Inner.m", 3, 4)]


def test_end_line_of_unclosed_body_is_last_line():
    src = "function open() {\n  work()\n\n"
    assert names(src, "javascript") == [("open", 1, 2)]


# ---------------------------------------------------------------- Markdown


def test_markdown_sections_include_subsections_and_trim_trailing_blanks():
    src = (
        "# Guide\n\nIntro.\n\n"
        "## Install\nRun it.\n\n"
        "### From source\nmake install\n\n"
        "## Usage ##\nCall it.\n\n"
        "# Appendix\nNotes.\n\n"
    )
    assert names(src, "markdown") == [
        ("# Guide", 1, 12), ("## Install", 5, 9), ("### From source", 8, 9),
        ("## Usage", 11, 12), ("# Appendix", 14, 15)]


def test_markdown_setext_headings_and_inline_markup():
    src = "Project\n=======\n\n###  The `run`   *command*\nText\n\nDetails\n-------\nBody\n"
    assert names(src, "markdown") == [
        ("# Project", 1, 9), ("### The `run` *command*", 4, 5), ("## Details", 7, 9)]


def test_markdown_skips_front_matter_and_fenced_code():
    src = (
        "---\ntitle: Doc\n# yaml comment\n---\n"
        "# Real\n```bash\n# hidden\n```\n"
        "~~~~\n## also hidden\n~~~\nTitle\n---\n~~~~\n"
        "## After\n"
    )
    assert names(src, "markdown") == [("# Real", 5, 15), ("## After", 15, 15)]


def test_markdown_unclosed_fence_and_no_headings():
    assert names("# Top\n```\n## hidden\n", "markdown") == [("# Top", 1, 3)]
    assert names("Just a paragraph.\n\n- item\n\n---\n", "markdown") == []
    assert names("#hashtag is not a heading\n    ## indented code\n", "markdown") == []
    assert names("", "markdown") == []


@pytest.mark.parametrize("indent", ["    ", "\t"])
def test_markdown_indented_backticks_do_not_open_a_fence(indent):
    src = f"# A\n{indent}```\n## B\n"
    assert names(src, "markdown") == [("# A", 1, 3), ("## B", 3, 3)]


@pytest.mark.parametrize("indent", ["    ", "\t"])
def test_markdown_indented_backticks_do_not_close_a_fence(indent):
    src = f"# A\n```\n{indent}```\n## hidden\n```\n## B\n"
    assert names(src, "markdown") == [("# A", 1, 6), ("## B", 6, 6)]


def test_markdown_three_space_fences_still_hide_headings():
    src = "# A\n   ```\n## hidden\n   ``` \t\n## B\n"
    assert names(src, "markdown") == [("# A", 1, 5), ("## B", 5, 5)]


def test_markdown_file_dispatch_normalizes_bom_and_crlf(tmp_path):
    file = tmp_path / "README.MD"
    file.write_bytes("\ufeff# 제목\r\n\r\n본문\r\n".encode("utf-8"))
    assert extract_symbols(file) == [("# 제목", 1, 3)]


# ---------------------------------------------------------------- CSS


def test_css_selectors_and_nested_at_rules_have_inclusive_ranges():
    src = (
        ":root { --gap: 4px; }\n"
        "@media (max-width: 600px) {\n"
        "  .card > .title,\n"
        "  h2.title { color: red; }\n"
        "  .card:hover { color: blue; }\n"
        "}\n"
        ".menu {\n"
        "  &:hover { color: gray; }\n"
        "}\n"
    )
    assert names(src, "css") == [
        (":root", 1, 1),
        ("@media (max-width: 600px)", 2, 6),
        ("@media (max-width: 600px) > .card > .title, h2.title", 3, 4),
        ("@media (max-width: 600px) > .card:hover", 5, 5),
        (".menu", 7, 9), (".menu > &:hover", 8, 8)]


def test_css_declaration_only_at_rules_hide_children():
    src = (
        "@font-face { font-family: X; src: url(x.woff2); }\n"
        "@keyframes spin {\n  from { opacity: 0 }\n  to { opacity: 1 }\n}\n"
        "@supports (display: grid) {\n"
        "  @-webkit-keyframes pulse { to { opacity: 0 } }\n"
        "  .grid { display: grid }\n"
        "}\n"
    )
    assert names(src, "css") == [
        ("@font-face", 1, 1), ("@keyframes spin", 2, 5),
        ("@supports (display: grid)", 6, 9),
        ("@supports (display: grid) > @-webkit-keyframes pulse", 7, 7),
        ("@supports (display: grid) > .grid", 8, 8)]


def test_css_comments_strings_urls_and_custom_properties_do_not_open_rules():
    src = (
        "/* .ghost { */\n"
        ".a::after { content: \"}\"; }\n"
        ".b { background: url(data:image/svg+xml;utf8,<svg>{</svg>); }\n"
        ".c /* inline { */ .d { content: '{' }\n"
        ":root { --json: { \"a\": { \"b\": 1 } }; }\n"
        ".after { color: red }\n"
    )
    assert names(src, "css") == [
        (".a::after", 2, 2), (".b", 3, 3), (".c .d", 4, 4),
        (":root", 5, 5), (".after", 6, 6)]


@pytest.mark.parametrize("src,expected", [
    ("@media screen {\n  .a {\n", [("@media screen", 1, 2), ("@media screen > .a", 2, 2)]),
    ("} } .a { }\n}\n", [(".a", 1, 1)]),
    ("{ } .a { }\n", [(".a", 1, 1)]),
    ("/* never closed\n.a { }\n", []),
    (".a { content: \"open\n}\n.b { }\n", [(".a", 1, 2), (".b", 3, 3)]),
    ("--x: {\n.a { }\n", []),
    ("", []),
])
def test_css_malformed_input_has_stable_ranges(src, expected):
    assert names(src, "css") == expected


def test_css_file_dispatch_normalizes_crlf(tmp_path):
    file = tmp_path / "site.CSS"
    file.write_bytes(b".a {\r\n  color: red;\r\n}\r\n")
    assert extract_symbols(file) == [(".a", 1, 3)]
