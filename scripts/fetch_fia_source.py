"""Install the FIA 2026 Technical Regulations (Section C, Issue 20) locally. Never runs automatically.

The regulation is not part of this repository (fia_rules/source/README.md). This script downloads the PDF from the
official URL recorded in fia_rules/source/SOURCE.md (or takes a copy you downloaded yourself with --pdf), checks
its SHA-256 against the recorded value, stores it under the exact recorded file name and extracts the text used
for snippet retrieval (PyMuPDF, one "===== PAGE n =====" marker per page). The FIA's own terms of use apply.

    python scripts/fetch_fia_source.py                  # download, verify, extract
    python scripts/fetch_fia_source.py --pdf my.pdf     # use a PDF you downloaded yourself
    python scripts/fetch_fia_source.py --no-extract     # PDF only (no PyMuPDF needed; fewer snippets)

Text extraction needs PyMuPDF (`python -m pip install pymupdf`). A different issue of the regulations has a
different hash on purpose: it is refused, because the rule records cite Issue 20.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = REPO_ROOT / "fia_rules" / "source"
PDF_NAME = "fia_2026_f1_regulations_section_c_technical_iss20_2026-08-05.pdf"
TXT_NAME = "fia_2026_section_c_iss20.txt"
URL = ("https://www.fia.com/system/files/documents/"
       "fia_2026_f1_regulations_-_section_c_technical_-_iss_20_-_2026-08-05.pdf")
PDF_SHA256 = "cf0b919eef5eecc27497fb6de012f8d27e200f6dbd34d62b7e5385f7274ff652"
# SHA-256 of the text as extracted with PyMuPDF 1.26 (LF line endings); another PyMuPDF version may differ slightly.
TXT_SHA256 = "922c4929397ee6045fdc496d5474e7e33e64b90d8b73072a48bc0e64418025e1"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "race-car-agent-fetch/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)


def extract_text(pdf: Path) -> str:
    try:
        import fitz  # PyMuPDF
    except ImportError:
        raise SystemExit("PyMuPDF is not installed: python -m pip install pymupdf (or use --no-extract)")
    with fitz.open(str(pdf)) as doc:
        return "".join(f"\n===== PAGE {i} =====\n{page.get_text()}" for i, page in enumerate(doc, 1))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pdf", type=Path, help="use this local PDF instead of downloading")
    ap.add_argument("--no-extract", action="store_true", help="install the PDF only, no text extraction")
    args = ap.parse_args(argv)

    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    target = SOURCE_DIR / PDF_NAME
    with tempfile.TemporaryDirectory() as tmp:
        src = args.pdf
        if src is None:
            src = Path(tmp) / PDF_NAME
            print(f"Downloading {URL}")
            download(URL, src)
        if not src.is_file():
            print(f"not a file: {src}", file=sys.stderr)
            return 2
        got = sha256(src)
        if got != PDF_SHA256:
            print(f"SHA-256 mismatch: got {got}, expected {PDF_SHA256} (Issue 20). Nothing was installed.\n"
                  "A different issue of the regulations is refused on purpose; see fia_rules/source/README.md.",
                  file=sys.stderr)
            return 1
        if src.resolve() != target.resolve():
            shutil.copyfile(src, target)
    print(f"PDF installed and verified: {target.relative_to(REPO_ROOT)}")

    if args.no_extract:
        print("Text not extracted: only the structured rules' quotations will be retrieved.")
        return 0
    text = extract_text(target)
    txt = SOURCE_DIR / TXT_NAME
    txt.write_text(text, encoding="utf-8", newline="\n")
    note = "matches the reference extraction" if sha256(txt) == TXT_SHA256 else \
        "differs from the reference extraction (another PyMuPDF version?); retrieval still works"
    print(f"Text extracted: {txt.relative_to(REPO_ROOT)} ({note})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
