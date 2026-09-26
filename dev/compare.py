"""Compare the built-in extractor (scripts/extract.py) with the tree-sitter oracle.

Usage: python dev/compare.py <dir> [<dir> ...] [--examples N] [--lang LANG]

For each language prints files, symbols found by each extractor, precision/recall of names
(multiset match per file) and how many matched names are on the same line.
Development only; requires tree-sitter-language-pack.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "dev"))

import extract  # noqa: E402
import treesitter_oracle as oracle  # noqa: E402

SKIP_DIRS = {".git", "node_modules", "target", "build", "dist", "vendor", "__pycache__", "bin", "obj"}


def files_under(d: Path):
    for p in d.rglob("*"):
        if p.is_file() and p.suffix.lower() in extract.EXT_LANG and not (SKIP_DIRS & set(p.parts)):
            yield p


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("--examples", type=int, default=5)
    ap.add_argument("--lang")
    args = ap.parse_args()

    stats = defaultdict(Counter)
    examples = defaultdict(list)
    for d in args.dirs:
        for f in files_under(Path(d)):
            lang = extract.language_of(f, f.read_text(encoding="utf-8-sig", errors="replace"))
            if args.lang and lang != args.lang:
                continue
            try:
                # the oracle has start lines only, so compare (name, start line)
                ours = [(name, start) for name, start, _ in extract.extract_symbols(f)]
            except Exception as exc:  # built-in extractor must never raise except Python syntax
                stats[lang]["errors"] += 1
                examples[lang].append(f"ERROR {f}: {exc!r}")
                continue
            try:
                ref = oracle.extract_symbols(f, lang)
            except Exception:
                continue
            st = stats[lang]
            st["files"] += 1
            st["oracle"] += len(ref)
            st["ours"] += len(ours)
            ref_names = Counter(n for n, _ in ref)
            our_names = Counter(n for n, _ in ours)
            st["matched"] += sum((ref_names & our_names).values())
            ref_lines = defaultdict(list)
            for n, ln in ref:
                ref_lines[n].append(ln)
            for n, ln in ours:
                if ln in ref_lines.get(n, []):
                    st["same_line"] += 1
            missing = ref_names - our_names
            extra = our_names - ref_names
            if (missing or extra) and len(examples[lang]) < args.examples:
                examples[lang].append(
                    f"{f}\n    missing: {sorted(missing.elements())[:8]}\n    extra:   {sorted(extra.elements())[:8]}")

    print(f"{'lang':<11}{'files':>6}{'oracle':>8}{'ours':>8}{'recall':>8}{'precis':>8}{'line=':>8}{'err':>5}")
    for lang, st in sorted(stats.items()):
        rec = st["matched"] / st["oracle"] if st["oracle"] else 1.0
        pre = st["matched"] / st["ours"] if st["ours"] else 1.0
        same = st["same_line"] / st["matched"] if st["matched"] else 1.0
        print(f"{lang:<11}{st['files']:>6}{st['oracle']:>8}{st['ours']:>8}{rec:>8.1%}{pre:>8.1%}"
              f"{same:>8.1%}{st['errors']:>5}")
    for lang, ex in sorted(examples.items()):
        if ex:
            print(f"\n== {lang}")
            for e in ex:
                print("  " + e)


if __name__ == "__main__":
    main()
