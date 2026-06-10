#!/usr/bin/env python3
"""Extract page-aware text from digital or scanned PDF files.

Exit codes:
  0 success
  1 invalid arguments or missing input
  2 missing dependency
  3 PDF read, extraction, OCR, or write failure
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


EXIT_USAGE = 1
EXIT_DEPENDENCY = 2
EXIT_RUNTIME = 3


@dataclass
class PageText:
    page: int
    text: str
    engine: str
    score: float


def module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"(?<=\w)-\n(?=\w)", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def text_score(text: str) -> float:
    """Score extracted text using length and character-quality heuristics."""
    if not text.strip():
        return 0.0

    length = len(text)
    replacement = text.count("\ufffd")
    controls = sum(
        1
        for char in text
        if unicodedata.category(char).startswith("C") and char not in "\n\t"
    )
    useful = sum(1 for char in text if char.isalnum())
    printable = sum(1 for char in text if char.isprintable() or char in "\n\t")
    useful_ratio = useful / length
    printable_ratio = printable / length

    return max(
        0.0,
        length
        + useful_ratio * 120
        + printable_ratio * 80
        - replacement * 30
        - controls * 20,
    )


def parse_page_spec(spec: Optional[str], page_count: int) -> list[int]:
    """Return zero-based page indexes from a 1-based expression such as 1-3,7."""
    if not spec:
        return list(range(page_count))

    selected: set[int] = set()
    for part in spec.split(","):
        token = part.strip()
        if not token:
            continue
        if "-" in token:
            start_text, end_text = token.split("-", 1)
            if not start_text.isdigit() or not end_text.isdigit():
                raise ValueError(f"Invalid page range: {token}")
            start, end = int(start_text), int(end_text)
            if start > end:
                raise ValueError(f"Page range starts after it ends: {token}")
            selected.update(range(start - 1, end))
        elif token.isdigit():
            selected.add(int(token) - 1)
        else:
            raise ValueError(f"Invalid page number: {token}")

    invalid = sorted(index + 1 for index in selected if index < 0 or index >= page_count)
    if invalid:
        raise ValueError(
            f"Page selection is outside this {page_count}-page PDF: {invalid}"
        )
    return sorted(selected)


def read_pypdf(
    path: Path,
    password: Optional[str],
    page_spec: Optional[str],
    layout: bool,
) -> tuple[list[PageText], dict[str, Any], int]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    if reader.is_encrypted:
        if not password:
            raise ValueError("PDF is encrypted; provide --password")
        if reader.decrypt(password) == 0:
            raise ValueError("PDF password is incorrect")

    page_count = len(reader.pages)
    indexes = parse_page_spec(page_spec, page_count)
    results: list[PageText] = []

    for index in indexes:
        page = reader.pages[index]
        if layout:
            try:
                raw = page.extract_text(extraction_mode="layout") or ""
            except (KeyError, TypeError):
                raw = page.extract_text() or ""
        else:
            raw = page.extract_text() or ""
        text = normalize_text(raw)
        results.append(PageText(index + 1, text, "pypdf", text_score(text)))

    metadata = {}
    if reader.metadata:
        metadata = {
            str(key).lstrip("/"): str(value)
            for key, value in reader.metadata.items()
            if value is not None
        }
    return results, metadata, page_count


def read_pymupdf(
    path: Path,
    password: Optional[str],
    page_spec: Optional[str],
    layout: bool,
) -> tuple[list[PageText], dict[str, Any], int]:
    import fitz

    document = fitz.open(path)
    try:
        if document.needs_pass:
            if not password:
                raise ValueError("PDF is encrypted; provide --password")
            if not document.authenticate(password):
                raise ValueError("PDF password is incorrect")

        page_count = document.page_count
        indexes = parse_page_spec(page_spec, page_count)
        results: list[PageText] = []

        for index in indexes:
            page = document[index]
            raw = page.get_text("text", sort=layout) or ""
            text = normalize_text(raw)
            results.append(PageText(index + 1, text, "pymupdf", text_score(text)))

        metadata = {
            str(key): str(value)
            for key, value in (document.metadata or {}).items()
            if value
        }
        return results, metadata, page_count
    finally:
        document.close()


def choose_best_pages(candidates: list[list[PageText]]) -> list[PageText]:
    by_page: dict[int, list[PageText]] = {}
    for engine_pages in candidates:
        for page in engine_pages:
            by_page.setdefault(page.page, []).append(page)

    return [
        max(by_page[page_number], key=lambda item: item.score)
        for page_number in sorted(by_page)
    ]


def extract_pdf(
    path: Path,
    engine: str,
    password: Optional[str],
    page_spec: Optional[str],
    layout: bool,
) -> tuple[list[PageText], dict[str, Any], int, list[str]]:
    available = {
        "pypdf": module_available("pypdf"),
        "pymupdf": module_available("fitz"),
    }
    requested = list(available) if engine == "auto" else [engine]
    missing = [name for name in requested if not available[name]]

    if engine != "auto" and missing:
        package = "PyMuPDF" if engine == "pymupdf" else "pypdf"
        raise ModuleNotFoundError(
            f"{package} is not installed; run pip install -r scripts/requirements.txt"
        )

    candidates: list[list[PageText]] = []
    metadata: dict[str, Any] = {}
    page_count = 0
    warnings: list[str] = []
    failures: list[str] = []

    for name in requested:
        if not available[name]:
            warnings.append(f"{name} is unavailable and was skipped")
            continue
        try:
            if name == "pypdf":
                pages, engine_metadata, count = read_pypdf(
                    path, password, page_spec, layout
                )
            else:
                pages, engine_metadata, count = read_pymupdf(
                    path, password, page_spec, layout
                )
            candidates.append(pages)
            if not metadata:
                metadata = engine_metadata
            page_count = max(page_count, count)
        except Exception as exc:
            if engine != "auto":
                raise
            failure = f"{name} failed: {exc}"
            warnings.append(failure)
            failures.append(failure)

    if not candidates:
        if missing and len(missing) == len(requested):
            raise ModuleNotFoundError(
                "No PDF extraction engine is installed; run "
                "pip install -r scripts/requirements.txt"
            )
        detail = "; ".join(failures) or "no extraction result was produced"
        raise RuntimeError(f"All available PDF extraction engines failed: {detail}")

    return choose_best_pages(candidates), metadata, page_count, warnings


def build_quality(pages: list[PageText]) -> dict[str, Any]:
    selected_count = len(pages)
    char_count = sum(len(page.text) for page in pages)
    empty_pages = [page.page for page in pages if not page.text.strip()]
    readable_pages = selected_count - len(empty_pages)
    readable_ratio = readable_pages / selected_count if selected_count else 0.0

    if char_count == 0 or readable_ratio < 0.25:
        status = "poor"
    elif char_count < max(80, selected_count * 30) or readable_ratio < 0.75:
        status = "partial"
    else:
        status = "good"

    return {
        "status": status,
        "char_count": char_count,
        "selected_page_count": selected_count,
        "readable_page_count": readable_pages,
        "empty_pages": empty_pages,
    }


def find_ocrmypdf_command() -> Optional[list[str]]:
    executable = shutil.which("ocrmypdf")
    if executable:
        return [executable]
    if module_available("ocrmypdf"):
        return [sys.executable, "-m", "ocrmypdf"]
    return None


def run_ocr(
    source: Path,
    target: Path,
    language: str,
    deskew: bool,
    force_ocr: bool,
) -> None:
    command = find_ocrmypdf_command()
    if not command:
        raise ModuleNotFoundError(
            "OCRmyPDF is not installed; see references/ocr-fallback.md"
        )

    args = command + ["--language", language, "--skip-text"]
    if deskew:
        args.append("--deskew")
    if force_ocr:
        args = [item for item in args if item != "--skip-text"]
        args.append("--force-ocr")
    args.extend([str(source), str(target)])

    completed = subprocess.run(args, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"OCR failed: {detail}")


def make_payload(
    source: Path,
    pages: list[PageText],
    metadata: dict[str, Any],
    page_count: int,
    warnings: list[str],
    ocr_used: bool,
) -> dict[str, Any]:
    quality = build_quality(pages)
    return {
        "status": "ok",
        "source": str(source),
        "page_count": page_count,
        "selected_pages": [page.page for page in pages],
        "engines_used": sorted({page.engine for page in pages}),
        "ocr_used": ocr_used,
        "quality": quality,
        "metadata": metadata,
        "warnings": warnings,
        "pages": [
            {
                "page": page.page,
                "chars": len(page.text),
                "engine": page.engine,
                "text": page.text,
            }
            for page in pages
        ],
    }


def render_text(payload: dict[str, Any]) -> str:
    chunks = []
    for page in payload["pages"]:
        chunks.extend([f"--- Page {page['page']} ---", page["text"], ""])
    return "\n".join(chunks).rstrip() + "\n"


def render_markdown(payload: dict[str, Any]) -> str:
    source_name = Path(payload["source"]).name
    quality = payload["quality"]
    engines = ", ".join(payload["engines_used"]) or "none"
    lines = [
        f"# Extracted Text: {source_name}",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Quality | {quality['status']} |",
        f"| Characters | {quality['char_count']} |",
        f"| Pages extracted | {quality['selected_page_count']} |",
        f"| Engines | {engines} |",
        f"| OCR used | {str(payload['ocr_used']).lower()} |",
        "",
    ]
    if payload["warnings"]:
        lines.extend(["## Warnings", ""])
        lines.extend(f"- {warning}" for warning in payload["warnings"])
        lines.append("")

    for page in payload["pages"]:
        text = page["text"] or "_No extractable text found on this page._"
        lines.extend([f"## Page {page['page']}", "", text, ""])
    return "\n".join(lines).rstrip() + "\n"


def render_payload(payload: dict[str, Any], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if output_format == "text":
        return render_text(payload)
    return render_markdown(payload)


def write_output(content: str, output: Optional[str]) -> None:
    if not output:
        sys.stdout.write(content)
        return
    target = Path(output).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def command_check() -> int:
    checks = {
        "python": True,
        "pypdf": module_available("pypdf"),
        "pymupdf": module_available("fitz"),
        "ocrmypdf_optional": find_ocrmypdf_command() is not None,
        "tesseract_optional": shutil.which("tesseract") is not None,
        "ghostscript_optional": any(
            shutil.which(name) is not None for name in ("gs", "gswin64c", "gswin32c")
        ),
    }
    print(json.dumps(checks, indent=2))
    return 0 if checks["pypdf"] or checks["pymupdf"] else EXIT_DEPENDENCY


def command_ocr(args: argparse.Namespace) -> int:
    source = validate_pdf_path(args.input)
    target = Path(args.output).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    run_ocr(source, target, args.language, args.deskew, args.force_ocr)
    print(json.dumps({"status": "ok", "output": str(target)}, ensure_ascii=False))
    return 0


def validate_pdf_path(value: str) -> Path:
    source = Path(value).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"Input PDF not found: {source}")
    if not source.is_file() or source.suffix.lower() != ".pdf":
        raise ValueError(f"Expected a .pdf file: {source}")
    return source


def command_extract(args: argparse.Namespace) -> int:
    source = validate_pdf_path(args.input)
    ocr_used = False
    warnings: list[str] = []

    with tempfile.TemporaryDirectory(prefix="pdf-text-reader-") as temp_dir:
        extraction_source = source
        if args.ocr == "always":
            extraction_source = Path(temp_dir) / "ocr.pdf"
            run_ocr(
                source,
                extraction_source,
                args.ocr_language,
                args.deskew,
                args.force_ocr,
            )
            ocr_used = True

        pages, metadata, page_count, engine_warnings = extract_pdf(
            extraction_source,
            args.engine,
            args.password,
            args.pages,
            args.layout,
        )
        warnings.extend(engine_warnings)
        quality = build_quality(pages)

        if args.ocr == "auto" and quality["status"] == "poor":
            ocr_source = Path(temp_dir) / "ocr.pdf"
            try:
                run_ocr(
                    source,
                    ocr_source,
                    args.ocr_language,
                    args.deskew,
                    args.force_ocr,
                )
                pages, metadata, page_count, engine_warnings = extract_pdf(
                    ocr_source,
                    args.engine,
                    args.password,
                    args.pages,
                    args.layout,
                )
                warnings.extend(engine_warnings)
                ocr_used = True
            except Exception as exc:
                warnings.append(f"Automatic OCR was unavailable or failed: {exc}")

    payload = make_payload(
        source, pages, metadata, page_count, warnings, ocr_used
    )
    write_output(render_payload(payload, args.format), args.output)

    if payload["quality"]["status"] == "poor":
        print(
            "WARNING: extraction quality is poor; review OCR guidance.",
            file=sys.stderr,
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract page-aware text from digital or scanned PDF files."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("check", help="Check extraction and optional OCR tools")

    extract_parser = subparsers.add_parser("extract", help="Extract PDF text")
    extract_parser.add_argument("input", help="Input PDF path")
    extract_parser.add_argument("-o", "--output", help="Output file; stdout if omitted")
    extract_parser.add_argument(
        "--format",
        choices=("markdown", "text", "json"),
        default="markdown",
    )
    extract_parser.add_argument(
        "--engine",
        choices=("auto", "pypdf", "pymupdf"),
        default="auto",
    )
    extract_parser.add_argument("--pages", help='Page selection such as "1-3,7"')
    extract_parser.add_argument("--password", help="Password for encrypted PDFs")
    extract_parser.add_argument(
        "--layout",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Preserve reading order and layout where supported",
    )
    extract_parser.add_argument(
        "--ocr",
        choices=("never", "auto", "always"),
        default="never",
    )
    extract_parser.add_argument("--ocr-language", default="eng")
    extract_parser.add_argument("--deskew", action="store_true")
    extract_parser.add_argument("--force-ocr", action="store_true")

    ocr_parser = subparsers.add_parser(
        "ocr", help="Create a searchable PDF with OCRmyPDF"
    )
    ocr_parser.add_argument("input", help="Input PDF path")
    ocr_parser.add_argument("output", help="Searchable output PDF path")
    ocr_parser.add_argument("--language", default="eng")
    ocr_parser.add_argument("--deskew", action="store_true")
    ocr_parser.add_argument("--force-ocr", action="store_true")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.command == "check":
            return command_check()
        if args.command == "ocr":
            return command_ocr(args)
        return command_extract(args)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except ModuleNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_DEPENDENCY
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_RUNTIME


if __name__ == "__main__":
    raise SystemExit(main())
