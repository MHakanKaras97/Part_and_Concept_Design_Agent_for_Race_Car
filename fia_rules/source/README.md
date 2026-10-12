# FIA regulation source (not included)

The **FIA 2026 Formula 1 Technical Regulations (Section C, Issue 20)** are **not included** in this repository.
They are published by the FIA on its website, and the FIA's own terms of use apply to them. `SOURCE.md` records
which document the rule records cite: file name, issue, date, official URL and SHA-256.

## Without the regulation (default)

Everything works without it: the unit tests, the strict mode, fast-mode design runs, rebuilds and revisions.
FIA snippet retrieval returns nothing, and **every fast-mode FIA status stays `NOT_VERIFIED`** with the note
"FIA source not installed; run scripts/fetch_fia_source.py".

## Installing it

Either way, the file is checked against the SHA-256 recorded in `SOURCE.md` before it is used.

1. **Script:** `python scripts/fetch_fia_source.py` downloads the PDF from the official URL, verifies the hash,
   stores it here and extracts its text (needs `python -m pip install pymupdf`). Use `--pdf <file>` to install a
   copy you downloaded yourself, or `--no-extract` to install the PDF only.
2. **Manual:** download the PDF from the FIA website and save it in this folder under the exact file name given
   in `SOURCE.md`. Optionally, put its plain text into `fia_2026_section_c_iss20.txt` (UTF-8), with a line
   `===== PAGE n =====` before the text of each page.

Both files are ignored by git and are never committed.

## What it changes

- With the PDF (hash verified), the quotations stored in `fia_rules/rules/*.yaml` are retrieved as snippets, and
  the width rule C2.3.1 can be measured: each part's world bounding box is compared with |Y| ≤ 950 mm.
- With the extracted text as well, a few short excerpts of the relevant articles are retrieved per part and
  passed to the planning step as context.
- Another issue of the regulations has a different hash. It is refused on purpose, because the rule records cite
  Issue 20.

Nothing in this project is an FIA compliance check, and no compliance is claimed. The width measurement is a
per-part proxy at concept level, and the rule transcriptions have not been reviewed by a person.
