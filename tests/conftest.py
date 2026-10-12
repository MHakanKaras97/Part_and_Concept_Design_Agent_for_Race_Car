"""Shared test setup.

Optional imports: a test module or test that needs a package which is not installed is reported as SKIPPED with
the install command, instead of failing at collection (OPTIONAL_IMPORTS).

FIA source: the FIA regulations are not part of the repository (fia_rules/source/README.md). Every test runs
against a SYNTHETIC stand-in by default (tests/fixtures/fia_synthetic/: invented text, not FIA), so retrieval,
planning and design runs are tested without the document; the source check (hash of the "PDF") still runs, on a
stub file. Tests marked `fia_source` use the real installed document instead and skip when it is absent.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import fia_rules.retrieval as _retrieval

OPTIONAL_IMPORTS = {"PIL": "Pillow"}                  # module -> pip package

SYNTHETIC_DIR = Path(__file__).resolve().parent / "fixtures" / "fia_synthetic"
SYNTHETIC_TXT = SYNTHETIC_DIR / "synthetic_regulation.txt"
SYNTHETIC_STUB = SYNTHETIC_DIR / "synthetic_source_stub.bin"
SYNTHETIC_STUB_SHA256 = "375e186acf49bf8bb1767f13bf6d7d4a7a0201da2050eba0787712d84710f891"
REAL_SOURCE_PDF, REAL_SOURCE_SHA256 = _retrieval.SOURCE_PDF, _retrieval.SOURCE_PDF_SHA256   # before any patching


def _missing_optional(exc: BaseException) -> str | None:
    name = (getattr(exc, "name", None) or "").split(".")[0]
    return OPTIONAL_IMPORTS.get(name) if isinstance(exc, ModuleNotFoundError) else None


def _skip_reason(pkg: str) -> str:
    return f"optional package {pkg} not installed (python -m pip install -e .[dev])"


@pytest.hookimpl(wrapper=True)
def pytest_make_collect_report(collector):
    report = yield
    if report.failed and isinstance(collector, pytest.Module) and report.longrepr is not None:
        for module, pkg in OPTIONAL_IMPORTS.items():
            if f"No module named '{module}'" in str(report.longrepr):
                report.outcome = "skipped"
                report.longrepr = (str(collector.path), 0, f"Skipped: {_skip_reason(pkg)}")
                break
    return report


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item):
    try:
        return (yield)
    except ModuleNotFoundError as e:
        pkg = _missing_optional(e)
        if pkg:
            pytest.skip(_skip_reason(pkg))
        raise


def use_fia_source(monkeypatch, pdf: Path, sha256: str, txt: Path) -> None:
    monkeypatch.setattr(_retrieval, "SOURCE_PDF", pdf)
    monkeypatch.setattr(_retrieval, "SOURCE_PDF_SHA256", sha256)
    monkeypatch.setattr(_retrieval, "SOURCE_TXT", txt)


@pytest.fixture(autouse=True)
def _fia_source(request, monkeypatch):
    """Synthetic FIA source for every test; the real one (or a skip) for tests marked fia_source."""
    if request.node.get_closest_marker("fia_source"):
        if not (_retrieval.source_installed() and _retrieval.SOURCE_TXT.is_file()):
            pytest.skip("FIA regulation not installed (python scripts/fetch_fia_source.py)")
        return
    use_fia_source(monkeypatch, SYNTHETIC_STUB, SYNTHETIC_STUB_SHA256, SYNTHETIC_TXT)


@pytest.fixture
def no_fia_source(monkeypatch, tmp_path):
    """The state of a fresh clone: no FIA document installed."""
    use_fia_source(monkeypatch, tmp_path / "missing.pdf", SYNTHETIC_STUB_SHA256, tmp_path / "missing.txt")
