"""Extract page text from every PDF in books/ into data/corpus.jsonl.gz.

Run once after adding a book: python scripts/build_corpus.py
The app loads the compressed corpus at startup, so it never parses PDFs at runtime.
"""
import gzip
import json
import re
import sys
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).resolve().parents[1]


def clean(t: str) -> str:
    t = t.replace("\x00", "")
    t = re.sub(r"(\w)-\n(\w)", r"\1\2", t)
    t = re.sub(r"[ \t]+", " ", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def extract(pdf: Path):
    """Yield (page_number, text) one page at a time; long books don't fit in memory otherwise."""
    with pdfplumber.open(pdf) as p:
        for i, pg in enumerate(p.pages, 1):
            yield i, clean(pg.extract_text() or "")
            pg.flush_cache()
            pg.close()


if __name__ == "__main__":
    pdfs = sorted((ROOT / "books").glob("*.pdf"))
    out = ROOT / "data" / "corpus.jsonl.gz"
    out.parent.mkdir(exist_ok=True)
    with gzip.open(out, "wt", encoding="utf-8") as fh:
        for pdf in pdfs:
            n = 0
            for i, text in extract(pdf):
                n = i
                if len(text) > 40:
                    fh.write(json.dumps({"book": pdf.stem, "page": i, "text": text}, ensure_ascii=False) + "\n")
            print(f"{pdf.name}: {n} pages", file=sys.stderr)
    print(f"wrote {out} ({out.stat().st_size // 1024} KB)", file=sys.stderr)
