from __future__ import annotations

import importlib
import importlib.util
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from app.db import db_connection
from app.services.document_ingest import DocumentIngestService, SUPPORTED_FILE_TYPES
from app.services.ocr import OCRBackend
from app.services.semantic import SQLiteSemanticIndex


logger = logging.getLogger(__name__)


REQUIRED_OCR_MODULES = ("numpy", "pypdfium2", "rapidocr_onnxruntime")
AUTO_INSTALL_OFF_VALUES = {"0", "false", "no", "off"}
DEFAULT_DOCUMENT_NAMES = (
    "worksheet_question3.md",
    "python_loops_notes.txt",
    "spanish_python_loops.md",
    "french_algebra_note.md",
    "swahili_classroom_instructions.md",
)


def ensure_ocr_requirements(settings) -> bool:
    """Install OCR extras into the active Python environment when missing."""
    if getattr(settings, "ocr_enabled", "auto") == "off":
        return False
    if _modules_available(REQUIRED_OCR_MODULES):
        return False
    auto_install = os.getenv("ACCESSLAB_AUTO_INSTALL_OCR_REQUIREMENTS", "on").strip().lower()
    if auto_install in AUTO_INSTALL_OFF_VALUES:
        return False

    requirements_path = Path(settings.base_dir) / "requirements-ocr.txt"
    if not requirements_path.exists():
        logger.warning("OCR requirements file is missing: %s", requirements_path)
        return False

    logger.info("Installing missing OCR dependencies from %s.", requirements_path)
    completed = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", str(requirements_path)],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        logger.warning(
            "Automatic OCR dependency install failed with code %s: %s",
            completed.returncode,
            (completed.stderr or completed.stdout).strip(),
        )
        return False

    importlib.invalidate_caches()
    missing = [module for module in REQUIRED_OCR_MODULES if importlib.util.find_spec(module) is None]
    if missing:
        logger.warning("OCR install completed but modules are still missing: %s", ", ".join(missing))
        return False
    logger.info("OCR dependencies are installed and importable.")
    return True


def seed_default_documents(
    settings,
    *,
    ocr_backend: OCRBackend | None = None,
    semantic_index: SQLiteSemanticIndex | None = None,
) -> list[dict[str, Any]]:
    """Make bundled classroom materials available in a fresh active class space."""
    sample_dir = Path(settings.sample_data_dir)
    if not sample_dir.exists():
        return []

    existing_names = _existing_document_names(settings.db_path, class_space=settings.class_space)
    service = DocumentIngestService(
        uploads_dir=settings.uploads_dir,
        db_path=settings.db_path,
        ocr_backend=ocr_backend,
        semantic_index=semantic_index,
        ocr_min_chars_per_page=settings.ocr_min_chars_per_page,
    )

    seeded: list[dict[str, Any]] = []
    for source_path in _default_document_paths(sample_dir):
        if source_path.name in existing_names:
            seeded.append({"file_name": source_path.name, "created": False, "chunks_created": None})
            continue
        try:
            summary = service.ingest_upload(
                file_name=source_path.name,
                content=source_path.read_bytes(),
                uploader_role="teacher",
                visibility_scope="class",
                class_space=settings.class_space,
            )
        except Exception as exc:  # pragma: no cover - startup bootstrap should never block the app
            logger.warning("Default document %s could not be seeded: %s", source_path.name, exc)
            seeded.append(
                {
                    "file_name": source_path.name,
                    "created": False,
                    "chunks_created": None,
                    "error": str(exc),
                }
            )
            continue
        existing_names.add(source_path.name)
        seeded.append(
            {
                "file_name": summary.file_name,
                "created": True,
                "chunks_created": summary.chunks_created,
            }
        )
    return seeded


def ensure_semantic_backfill(semantic_index: SQLiteSemanticIndex | None) -> int:
    """Backfill missing embeddings when the local embedding provider is ready."""
    if semantic_index is None:
        return 0
    try:
        return semantic_index.ensure_embeddings()
    except Exception as exc:  # pragma: no cover - defensive startup/status path
        logger.warning("Semantic embedding backfill could not complete: %s", exc)
        return 0


def _modules_available(module_names: tuple[str, ...]) -> bool:
    return all(importlib.util.find_spec(module_name) is not None for module_name in module_names)


def _default_document_paths(sample_dir: Path) -> list[Path]:
    paths = [sample_dir / name for name in DEFAULT_DOCUMENT_NAMES]
    return [
        path
        for path in paths
        if path.is_file() and path.suffix.lower() in SUPPORTED_FILE_TYPES
    ]


def _existing_document_names(db_path: Path, *, class_space: str) -> set[str]:
    with db_connection(db_path) as connection:
        rows = connection.execute(
            "SELECT file_name FROM documents WHERE class_space = ?",
            (class_space,),
        ).fetchall()
    return {str(row["file_name"]) for row in rows}
