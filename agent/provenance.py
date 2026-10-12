"""Deterministic checks on the boundary between the user's words and the AI's interpretation of them.

- A requirement attributed to the user must quote the user's words verbatim.
- Every number in that interpretation must appear in the quoted words (no invented values).
- A critical question must not put engineering values into the user's mouth: it may only repeat numbers the
  user already wrote, and may not offer suggestions ("e.g.", "for example", ...) unless the project policy allows it.
"""
from __future__ import annotations

import re

_NUMBER_WORDS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
                 "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "single": 1, "pair": 2,
                 "double": 2, "twin": 2, "half": 0.5,
                 # Turkish (with the spellings used when typing without Turkish characters). Deliberately NOT
                 # "bir" (also the indefinite article) and "on" (also an English word): either would make many
                 # quotes look as if they contained 1 / 10 and so weaken the invented-number check.
                 "iki": 2, "üç": 3, "uc": 3, "dört": 4, "dort": 4, "beş": 5, "bes": 5, "altı": 6, "alti": 6,
                 "yedi": 7, "sekiz": 8, "dokuz": 9}
_NUM_RE = re.compile(r"(?<![A-Za-z])\d+(?:[.,]\d+)?|(?<=[A-Za-z])\d+(?:[.,]\d+)?")
SUGGESTION_MARKERS = ("e.g", "for example", "for instance", "such as", "typically", "typical value",
                      "something like", "would you accept", "should it be")


def normalize(text: str) -> str:
    t = text.replace(" ", " ").replace("×", "x").replace("’", "'").replace("“", '"').replace("”", '"')
    t = t.replace("İ", "i")              # Python lowercases the Turkish dotted capital I to 'i' + combining dot
    return re.sub(r"\s+", " ", t).strip().lower()


# Project identifiers are references, not engineering values: component ids (BRK-001), record ids (R01, M06,
# A03), rule/material ids with a hyphenated part (FIA26-C2.3.1, DFM-MACH-WALL-MIN, AL6061-T6), the series name
# F1 (also in "F1-inspired") and part numbers written as "Part 001".
_IDENTIFIER_RES = [re.compile(r"\b[A-Z]{2,5}-\d{3}\b"), re.compile(r"\b[RMA]\d{2,3}\b"),
                   re.compile(r"\b[A-Z][A-Z0-9]*\d[A-Z0-9]*(?:-[A-Z0-9.]+)+\b|\b[A-Z][A-Z0-9]*(?:-[A-Z0-9.]+)*-[A-Z0-9.]*\d[A-Z0-9.]*\b"),
                   re.compile(r"\bF1\b"), re.compile(r"\bpart\s+\d{3}\b", re.IGNORECASE)]


def strip_identifiers(text: str) -> str:
    for rx in _IDENTIFIER_RES:
        text = rx.sub(" ", text)
    return text


def number_sources(text: str) -> dict[float, list[str]]:
    """Numeric values written in the text -> the tokens/words they were read from: digits (incl. inside tokens like
    'M6') and simple number words. Project identifiers (BRK-001, R01, F1, FIA26-C2.3.1, ...) are ignored."""
    t = normalize(strip_identifiers(str(text)))
    out: dict[float, list[str]] = {}
    for m in _NUM_RE.finditer(t):
        token = re.search(r"\S*$", t[:m.start()]).group() + m.group() + re.match(r"\S*", t[m.end():]).group()
        out.setdefault(float(m.group().replace(",", ".")), []).append(token.strip(".,;:()[]'\""))
    for word, val in _NUMBER_WORDS.items():
        if re.search(rf"\b{word}\b", t):
            out.setdefault(float(val), []).append(word)
    return out


def numbers_in(text: str) -> set[float]:
    """Numeric values written in the text (see number_sources)."""
    return set(number_sources(text))


def quote_found(quote: str, source_text: str) -> bool:
    return normalize(quote) in normalize(source_text)


def invented_numbers(interpretation: str, quote: str) -> set[float]:
    """Numbers present in the AI interpretation but absent from the quoted user words."""
    return numbers_in(interpretation) - numbers_in(quote)


def describe_numbers(values, text: str) -> list[str]:
    """["2 (from 'two')", ...]: each value with the token(s) of `text` it was read from, for gate feedback."""
    src = number_sources(text)
    return [f"{v:g} (from {', '.join(repr(s) for s in dict.fromkeys(src.get(v, [])))})" for v in sorted(values)]


def question_problems(question: str, user_texts: list[str], allow_suggestions: bool) -> list[str]:
    """Problems with a question that would lead the user towards AI-chosen values."""
    if allow_suggestions:
        return []
    problems = []
    q = normalize(question)
    for marker in SUGGESTION_MARKERS:
        if marker in q:
            problems.append(f"contains a suggestion marker '{marker}'")
    known = set().union(*(numbers_in(t) for t in user_texts)) if user_texts else set()
    new = numbers_in(question) - known
    if new:
        problems.append(f"introduces numeric values not given by the user: {describe_numbers(new, question)}")
    return problems
