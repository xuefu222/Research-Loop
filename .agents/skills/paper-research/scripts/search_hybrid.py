"""BM25 与 E5 检索结果通过 RRF 融合。"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from search_compat import main

if __name__ == "__main__":
    raise SystemExit(main("hybrid"))
