"""Local OCR fallback for scanned / image-based PDFs.

This module is the narrow OCR entry point for AccessLab's ingest pipeline.
It is deliberately small and optional: if the OCR dependencies
(``rapidocr-onnxruntime`` and ``pypdfium2``) are not installed, everything
still works for text PDFs — scanned PDFs will simply report that OCR is
unavailable instead of silently indexing empty pages.

Why this shape:
    * ``OCRBackend`` protocol — the ingest service only sees a minimal
      surface (``is_available``, ``unavailable_reason``, ``ocr_pdf_page``),
      so it is trivial to mock in tests and trivial to swap the
      implementation later if a different lightweight OCR path is chosen.
    * ``RapidOCRBackend`` — production backend. Uses ONNX-Runtime (not
      PyTorch) and ``pypdfium2`` (bundled pdfium; no system poppler).
      All imports are lazy so the package is never loaded on servers that
      do not need OCR.
    * ``NullOCRBackend`` — explicit "OCR disabled" sentinel. Returned when
      ``ACCESSLAB_OCR_ENABLED=off`` or when the optional dependencies are
      missing. It always reports ``is_available() is False`` and, if
      accidentally called, raises a clearly-named error instead of
      producing empty text.

Rationale for picking this stack is captured in
``reports/ocr_decision_memo.md``.
"""

from __future__ import annotations

import logging
import os
import importlib.util
from pathlib import Path
from typing import Protocol


logger = logging.getLogger(__name__)


OCR_ENABLED_VALUES = ("auto", "on", "off")
DEFAULT_OCR_ENABLED = "auto"

DEFAULT_OCR_DPI = 200
MIN_OCR_DPI = 72
MAX_OCR_DPI = 600


class OCRUnavailableError(RuntimeError):
    """Raised when OCR was requested but the backend cannot serve it.

    This is distinct from ``Exception`` subclasses that indicate an OCR
    run failed mid-way: those should be caught locally and logged so the
    rest of the document still has a chance to ingest normally.
    """


class OCRBackend(Protocol):
    """Minimal surface the ingest service depends on.

    Implementations must be safe to construct lazily — callers may build
    them at app startup even when OCR is never used. Expensive work (model
    loading, rasteriser init) should happen on first ``is_available()``
    or ``ocr_pdf_page`` call, not in ``__init__``.
    """

    def is_available(self) -> bool: ...

    def unavailable_reason(self) -> str: ...

    def ocr_pdf_page(self, pdf_path: Path, page_number: int) -> str: ...

    def describe(self) -> str: ...


class NullOCRBackend:
    """Sentinel backend that always reports unavailable.

    Used when ``ACCESSLAB_OCR_ENABLED=off`` (explicitly disabled) and as a
    fallback when the optional OCR packages cannot be imported. The ingest
    service checks ``is_available()`` before calling ``ocr_pdf_page``, so
    this class simply needs to refuse clearly.
    """

    def __init__(self, reason: str) -> None:
        self._reason = reason

    def is_available(self) -> bool:
        return False

    def unavailable_reason(self) -> str:
        return self._reason

    def ocr_pdf_page(self, pdf_path: Path, page_number: int) -> str:
        raise OCRUnavailableError(self._reason)

    def describe(self) -> str:
        return f"null ({self._reason})"


class RapidOCRBackend:
    """RapidOCR + pypdfium2 backend.

    All heavy imports are deferred to :meth:`_ensure_loaded` so that
    simply *constructing* this class is free. The first call to
    :meth:`is_available` or :meth:`ocr_pdf_page` is what actually pulls
    ``onnxruntime`` / ``opencv`` / ``pypdfium2`` into memory.

    If any import fails (for example because ``pip install -r
    requirements-ocr.txt`` has not been run), the backend transitions to
    a steady "unavailable" state and records the reason for operators to
    inspect via :meth:`unavailable_reason`. Subsequent calls do not retry
    the import — this keeps error handling predictable.
    """

    def __init__(self, *, dpi: int = DEFAULT_OCR_DPI) -> None:
        self.dpi = int(dpi)
        self._attempted = False
        self._engine = None
        self._pdfium = None
        self._numpy = None
        self._load_error: str | None = None

    def _ensure_loaded(self) -> bool:
        if self._attempted:
            if self._engine is not None and self._pdfium is not None:
                return True
            if self._load_error and "not installed" in self._load_error and _ocr_imports_available():
                self._attempted = False
                self._load_error = None
            else:
                return False
        self._attempted = True
        try:
            import numpy as np  # type: ignore
            import pypdfium2 as pdfium  # type: ignore
            from rapidocr_onnxruntime import RapidOCR  # type: ignore
        except ImportError as exc:
            self._load_error = (
                f"OCR dependencies not installed: {exc}. "
                "Run `pip install -r requirements-ocr.txt` to enable OCR fallback."
            )
            logger.warning("RapidOCR backend disabled: %s", exc)
            return False
        except Exception as exc:  # pragma: no cover - unexpected import-time failure
            self._load_error = f"OCR dependencies failed to import: {exc}"
            logger.warning("RapidOCR backend disabled (unexpected): %s", exc)
            return False

        try:
            self._engine = RapidOCR()
        except Exception as exc:  # pragma: no cover - model init failure
            self._load_error = f"RapidOCR engine init failed: {exc}"
            logger.warning("RapidOCR engine init failed: %s", exc)
            return False

        self._pdfium = pdfium
        self._numpy = np
        return True

    def is_available(self) -> bool:
        return self._ensure_loaded()

    def unavailable_reason(self) -> str:
        self._ensure_loaded()
        if self._engine is not None and self._pdfium is not None:
            return ""
        return self._load_error or "OCR backend not available"

    def ocr_pdf_page(self, pdf_path: Path, page_number: int) -> str:
        """Rasterise one PDF page with pypdfium2 and OCR it with RapidOCR.

        ``page_number`` is 1-indexed to match the rest of AccessLab's
        page/chunk/citation bookkeeping. pypdfium2 uses 0-indexed pages
        internally so we translate at the boundary.

        Returns the space-joined OCR text for the page. The caller is
        responsible for normalising whitespace and chunking.
        """
        if not self._ensure_loaded():
            raise OCRUnavailableError(self.unavailable_reason())
        assert self._engine is not None and self._pdfium is not None
        assert self._numpy is not None

        if page_number < 1:
            raise ValueError(f"page_number must be >= 1, got {page_number}")

        scale = max(MIN_OCR_DPI, min(MAX_OCR_DPI, self.dpi)) / 72.0
        pdf = self._pdfium.PdfDocument(str(pdf_path))
        try:
            total_pages = len(pdf)
            if page_number > total_pages:
                raise ValueError(
                    f"page_number {page_number} out of range for document with {total_pages} page(s)"
                )
            page = pdf[page_number - 1]
            pil_image = page.render(scale=scale).to_pil().convert("RGB")
            image_array = self._numpy.asarray(pil_image)
        finally:
            pdf.close()

        result, _elapse = self._engine(image_array)
        if not result:
            return ""
        lines: list[str] = []
        for entry in result:
            if not entry or len(entry) < 2:
                continue
            text = entry[1]
            if isinstance(text, str) and text.strip():
                lines.append(text.strip())
        return " ".join(lines)

    def describe(self) -> str:
        if not self._attempted:
            return f"rapidocr (not loaded yet, dpi={self.dpi})"
        if self._engine is None or self._pdfium is None:
            return f"rapidocr (load failed: {self._load_error or 'unknown'})"
        return f"rapidocr (ready, dpi={self.dpi})"


def create_ocr_backend(
    *,
    enabled: str = DEFAULT_OCR_ENABLED,
    dpi: int = DEFAULT_OCR_DPI,
) -> OCRBackend:
    """Return an appropriate backend for the resolved ``enabled`` value.

    * ``off``  -> ``NullOCRBackend`` (ingest will refuse scanned PDFs with a
      clear "disabled" message; text PDFs unaffected).
    * ``auto`` -> ``RapidOCRBackend`` with lazy load. If the optional deps
      are missing, scanned PDFs fail gracefully with an install hint.
    * ``on``   -> same as ``auto`` but eagerly probes load at startup so
      missing deps surface in server logs immediately.
    """
    normalised = (enabled or "").strip().lower()
    if normalised not in OCR_ENABLED_VALUES:
        normalised = DEFAULT_OCR_ENABLED

    if normalised == "off":
        return NullOCRBackend("OCR disabled via ACCESSLAB_OCR_ENABLED=off")

    backend = RapidOCRBackend(dpi=dpi)
    if normalised == "on":
        if not backend.is_available():
            logger.warning(
                "ACCESSLAB_OCR_ENABLED=on but OCR backend did not load: %s",
                backend.unavailable_reason(),
            )
    return backend


def resolve_ocr_enabled(env_value: str | None = None) -> str:
    """Return one of ``OCR_ENABLED_VALUES`` from the ``ACCESSLAB_OCR_ENABLED`` env var."""
    raw = env_value if env_value is not None else os.getenv("ACCESSLAB_OCR_ENABLED", "")
    value = (raw or "").strip().lower()
    if value in OCR_ENABLED_VALUES:
        return value
    return DEFAULT_OCR_ENABLED


def resolve_ocr_dpi(env_value: str | None = None) -> int:
    """Return a clamped OCR DPI value from ``ACCESSLAB_OCR_DPI``."""
    raw = env_value if env_value is not None else os.getenv("ACCESSLAB_OCR_DPI", "")
    value = (raw or "").strip()
    if not value:
        return DEFAULT_OCR_DPI
    try:
        parsed = int(value)
    except ValueError:
        return DEFAULT_OCR_DPI
    return max(MIN_OCR_DPI, min(MAX_OCR_DPI, parsed))


def _ocr_imports_available() -> bool:
    return all(
        importlib.util.find_spec(module_name) is not None
        for module_name in ("numpy", "pypdfium2", "rapidocr_onnxruntime")
    )
