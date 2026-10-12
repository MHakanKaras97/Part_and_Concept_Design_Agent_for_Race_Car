"""Token-cheap FIA retrieval for fast mode: a few verbatim snippets per part, never the whole regulation.

Sources, in order: the structured rules (fia_rules/rules/*.yaml, verbatim requirement_text) and the extracted text
fia_rules/source/fia_2026_section_c_iss20.txt, split into articles (page header blocks removed). Snippets are
<= FIA_SNIPPET_CHARS characters of an article, cut at a word boundary, and verbatim: normalize(snippet) is a
substring of normalize(cleaned source). Each carries its article id, page and SHA-256.

The FIA document is NOT part of this repository (fia_rules/source/README.md). The source counts as installed only
when the PDF is present under SOURCE_PDF and its SHA-256 equals SOURCE_PDF_SHA256 (the issue recorded in
SOURCE.md). Not installed: retrieve() returns no snippets and every status is NOT_VERIFIED with NOT_INSTALLED_NOTE.
Installed without the extracted text: only the structured rules' quotations are retrieved.

Statuses (per part and article): VERIFIED only when Fusion measured the part against an unambiguous extent rule
(EXTENT_RULES); NON_COMPLIANT when that measurement fails; everything else NOT_VERIFIED.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

from agent import fast_config
from fia_rules.rules import REPO_ROOT, RuleSet

SOURCE_DIR = REPO_ROOT / "fia_rules" / "source"
SOURCE_PDF = SOURCE_DIR / "fia_2026_f1_regulations_section_c_technical_iss20_2026-08-05.pdf"
SOURCE_PDF_SHA256 = "cf0b919eef5eecc27497fb6de012f8d27e200f6dbd34d62b7e5385f7274ff652"   # SOURCE.md
SOURCE_TXT = SOURCE_DIR / "fia_2026_section_c_iss20.txt"
NOT_INSTALLED_NOTE = "FIA source not installed; run scripts/fetch_fia_source.py"
_ARTICLE_RE = re.compile(r"^(C\d{1,2}(?:\.\d{1,2}){1,3})\s*$")
_PAGE_RE = re.compile(r"^===== PAGE (\d+) =====$")
_HEADER_LINES = {"SECTION C: TECHNICAL REGULATIONS", "2026 Formula 1 Regulations - Section C [Technical]",
                 "05 August 2026", "Issue 20", "0", "C"}
FIRST_BODY_PAGE = 7                               # pages 1-6: title page and table of contents

# Article ids of rules whose limit is an unambiguous extent that a single part's world bbox can be checked against.
EXTENT_RULES = {"C2.3.1": {"quantity": "max_abs_y_mm", "max": 950.0,
                           "note": "no part of the car may lie more than 950mm from the plane Y=0 (wheels excepted)"}}

# Keywords per part-id prefix (matched case-insensitively; a title hit weighs more).
ROLE_KEYWORDS = {
    "MON": ["Survival Cell", "Cockpit", "Front Impact Structure", "cockpit opening", "monocoque"],
    "FWG": ["Front Wing", "Front Wing Profiles", "Front Wing Endplate", "FW"],
    "FLR": ["Floor Body", "Floor Bodywork", "Plank", "Diffuser", "Floor Fence", "Floor"],
    "RWG": ["Rear Wing", "Rear Wing Profiles", "Rear Wing Endplate", "Beam Wing", "RW"],
}
COMMON_ARTICLES = ["C2.3.1"]                     # vehicle width: applies to every part's extent
COMMON_EXEMPT = {"C2.3.1": ("WHL",)}              # ... wheels excepted (C2.3.1 text)
EXCLUDED_PREFIXES = ("C18.",)                     # appendix lists of parts, not geometric rules


def normalize(s: str) -> str:
    """The verbatim test's normalisation (tests/test_rules.py): ligatures, quotes, minus, whitespace."""
    s = s.replace("ﬁ", "fi").replace("ﬂ", "fl").replace("−", "-").replace("’", "'")
    s = s.replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", s).strip()


@dataclass(frozen=True)
class Article:
    article: str
    title: str
    page: int
    text: str                                     # normalised article text incl. id and title


@dataclass(frozen=True)
class Snippet:
    article: str
    title: str
    page: Optional[int]
    text: str
    sha256: str
    source: str                                   # "rules:<rule id>" or the source text file

    def as_dict(self) -> dict:
        return {"article": self.article, "title": self.title, "page": self.page, "text": self.text,
                "sha256": self.sha256, "source": self.source}


def _clean_lines(raw: str) -> list[tuple[int, str]]:
    """(page, line) with the page header blocks removed."""
    out, page, in_header = [], 0, False
    for line in raw.splitlines():
        m = _PAGE_RE.match(line.strip())
        if m:
            page, in_header = int(m.group(1)), True
            continue
        s = line.strip()
        if in_header:
            # header block: title, blank lines, page label (C31), regulation name, copyright, date, issue, 0, C
            if not s or s in _HEADER_LINES or s.startswith("©") or re.fullmatch(r"C\d{1,3}", s):
                if s == "C":
                    in_header = False
                continue
            in_header = False
        out.append((page, line))
    return out


@lru_cache(maxsize=8)
def _pdf_matches(path: str, expected: str, mtime_ns: int, size: int) -> bool:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest() == expected


def source_installed() -> bool:
    """True only if the regulation PDF is present and its SHA-256 is the recorded one (the source check)."""
    try:
        st = SOURCE_PDF.stat()
    except OSError:
        return False
    return _pdf_matches(str(SOURCE_PDF), SOURCE_PDF_SHA256, st.st_mtime_ns, st.st_size)


def _source() -> tuple[str, tuple[Article, ...]]:
    """(clean text, articles) of the extracted text; empty when the text file is missing."""
    try:
        st = SOURCE_TXT.stat()
    except OSError:
        return "", ()
    return _parse_source(str(SOURCE_TXT), st.st_mtime_ns, st.st_size)


@lru_cache(maxsize=4)
def _parse_source(path: str, mtime_ns: int, size: int) -> tuple[str, tuple[Article, ...]]:
    raw = Path(path).read_text(encoding="utf-8")
    lines = _clean_lines(raw)
    clean = normalize("\n".join(ln for _, ln in lines))
    arts, cur = [], None
    for i, (page, line) in enumerate(lines):
        m = _ARTICLE_RE.match(line.strip())
        if m and page >= FIRST_BODY_PAGE:
            if cur:
                arts.append(cur)
            title = lines[i + 1][1].strip() if i + 1 < len(lines) else ""
            cur = [m.group(1), title, page, [line]]
        elif cur:
            cur[3].append(line)
    if cur:
        arts.append(cur)
    articles = tuple(Article(a, t, p, normalize("\n".join(body))) for a, t, p, body in arts)
    return clean, articles


def source_sha256(path: Optional[Path] = None) -> Optional[str]:
    """SHA-256 of the extracted text, or None when it is not installed."""
    path = path or SOURCE_TXT
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def is_verbatim(text: str) -> bool:
    """True if the text occurs in the stored regulation text (normalised, page headers removed)."""
    clean = _source()[0]
    return bool(clean) and normalize(text) in clean


def _cut(text: str, n: int) -> str:
    if len(text) <= n:
        return text
    cut = text[:n]
    return cut[:cut.rfind(" ")] if " " in cut else cut


def _snip(article: str, title: str, page, text: str, source: str) -> Snippet:
    t = _cut(normalize(text), fast_config.get("FIA_SNIPPET_CHARS"))
    return Snippet(article, title, page, t, hashlib.sha256(t.encode("utf-8")).hexdigest(), source)


def _structured(article: str) -> Optional[Snippet]:
    for r in RuleSet.load().rules.values():
        if r.authority == "REGULATION" and r.source.article == article:
            return _snip(article, r.title, r.source.page, r.requirement_text, f"rules:{r.id}")
    return None


def retrieve(part_id: str, extra_keywords: list[str] | None = None, limit: int | None = None) -> list[Snippet]:
    """<= limit verbatim snippets for a part: the common extent rule(s) first, then the best keyword matches."""
    limit = limit or fast_config.get("MAX_FIA_SNIPPETS")
    if not source_installed():
        return []
    prefix = part_id.split("-")[0]
    out: list[Snippet] = [s for s in (_structured(a) for a in COMMON_ARTICLES if prefix not in COMMON_EXEMPT.get(a, ()))
                          if s]
    kws = [k for k in ROLE_KEYWORDS.get(prefix, []) + list(extra_keywords or []) if len(k) >= 2]
    if not kws:
        return out[:limit]
    scored = []
    for art in _source()[1]:
        if art.article in COMMON_ARTICLES or art.article.startswith(EXCLUDED_PREFIXES) or len(art.text) < 80:
            continue
        low, title = art.text.lower(), art.title.lower()
        title_hit, hits = False, 0
        for k in kws:
            kl = k.lower()
            if len(k) <= 3:                               # short tokens ("FW") only as whole words
                rx = re.compile(rf"\b{re.escape(kl)}\b")
                hits += len(rx.findall(low))
                title_hit = title_hit or bool(rx.search(title))
            else:
                hits += low.count(kl)
                title_hit = title_hit or kl in title
        if not hits:
            continue
        score = 4.0 * title_hit + min(hits, 6) / 2.0 + (1.5 if re.search(r"\d\s?mm\b", art.text) else 0.0)
        scored.append((-score, art.article.count("."), art.page, art))
    for _, _, _, art in sorted(scored, key=lambda x: (x[0], x[1], x[2]))[: max(0, limit - len(out))]:
        out.append(_snip(art.article, art.title, art.page, art.text, SOURCE_TXT.name))
    return out


def fia_status(article: str, bbox_world: Optional[list]) -> tuple[str, str]:
    """(status, note) for one FIA ref of a built part. Never VERIFIED without the installed, hash-checked source."""
    if not source_installed():
        return "NOT_VERIFIED", NOT_INSTALLED_NOTE
    rule = EXTENT_RULES.get(article)
    if rule is None:
        return "NOT_VERIFIED", "no automated check for this article at concept level"
    if not bbox_world:
        return "NOT_VERIFIED", "part not measured"
    max_abs_y = max(abs(bbox_world[0][1]), abs(bbox_world[1][1]))
    ok = max_abs_y <= rule["max"] + 1e-9
    return ("VERIFIED" if ok else "NON_COMPLIANT",
            f"measured max |Y| = {max_abs_y:.1f} mm vs limit {rule['max']:g} mm ({rule['note']}); "
            f"rule transcription not human-verified; checks this part's extent only")
