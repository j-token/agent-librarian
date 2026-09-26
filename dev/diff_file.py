"""Compare our extractor with the tree-sitter oracle on one file (development only).

Usage: python dev/diff_file.py <source file>

Prints every symbol in line order as `<mark> <start line> <name>`:
  "  "  both extractors found it
  "+ "  only ours found it (an extra symbol)
  "- "  only the oracle found it (a missed symbol)

Only the name and start line are compared, because the oracle does not report end lines.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "dev"))
import extract  # noqa: E402
import treesitter_oracle as oracle  # noqa: E402

MARK_BOTH = "  "
MARK_OURS_ONLY = "+ "
MARK_ORACLE_ONLY = "- "


def diff_mark(symbol, ours, oracle_symbols) -> str:
    if symbol in ours and symbol in oracle_symbols:
        return MARK_BOTH
    if symbol in ours:
        return MARK_OURS_ONLY
    return MARK_ORACLE_ONLY


def main(path: Path) -> None:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    lang = extract.language_of(path, text)

    ours = {(name, start) for name, start, _end in extract.extract_symbols(path)}
    oracle_symbols = set(oracle.extract_symbols(path, lang))

    by_line = sorted(ours | oracle_symbols, key=lambda symbol: (symbol[1], symbol[0]))
    for name, start in by_line:
        mark = diff_mark((name, start), ours, oracle_symbols)
        print(f"{mark}{start:>5} {name}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python dev/diff_file.py <source file>")
    main(Path(sys.argv[1]))
