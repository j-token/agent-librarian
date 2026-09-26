"""Print both extractors' output for one file side by side (development only)."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts")); sys.path.insert(0, str(ROOT / "dev"))
import extract, treesitter_oracle as oracle  # noqa: E402
f = Path(sys.argv[1])
lang = extract.language_of(f, f.read_text(encoding="utf-8-sig", errors="replace"))
ours = set(extract.extract_symbols(f)); ref = set(oracle.extract_symbols(f, lang))
for n, ln in sorted(ours | ref, key=lambda x: (x[1], x[0])):
    tag = "  " if (n, ln) in ours and (n, ln) in ref else ("+ " if (n, ln) in ours else "- ")
    print(f"{tag}{ln:>5} {n}")
