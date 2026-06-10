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
import textwrap
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


@dataclass
class LayoutBlock:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    max_font_size: float


def module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"(?<=\w)-\n(?=\w)", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def text_score(text: str) -> float:
    """Score text content while penalizing broken visual-layout extraction."""
    if not text.strip():
        return 0.0

    length = len(text)
    compact_length = len(re.sub(r"\s+", "", text))
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
    whitespace_penalty = sum(
        max(0, len(match.group(0)) - 3)
        for match in re.finditer(r"[ \t]{4,}", text)
    )
    long_line_penalty = sum(
        max(0, len(line) - 180) for line in text.splitlines()
    )

    return max(
        0.0,
        compact_length
        + useful_ratio * 120
        + printable_ratio * 80
        - replacement * 30
        - controls * 20
        - whitespace_penalty * 1.5
        - long_line_penalty * 0.75,
    )


HEADING_RE = re.compile(
    r"^(?:"
    r"(?:\d+(?:\.\d+)*\.)\s+[A-Z][^\n]{0,100}"
    r"|Abstract"
    r"|References"
    r"|Acknowledg(?:e)?ments?"
    r"|Appendix(?:\s+[A-Z])?"
    r")$",
    re.IGNORECASE,
)
CAPTION_RE = re.compile(r"^(?:Figure|Fig\.|Table)\s+\d+[.:]\s*", re.IGNORECASE)


def clean_layout_block(text: str, heading_size: bool = False) -> str:
    """Turn PDF line fragments from one layout block into readable Markdown."""
    raw_lines = text.replace("\r", "\n").splitlines()
    lines = [re.sub(r"\s+", " ", line).strip() for line in raw_lines]
    lines = [
        re.sub(r"^(\d+(?:\.\d+)*\.?)(?=[A-Z])", r"\1 ", line)
        for line in lines
    ]
    lines = [re.sub(r"^([•*-])(?=\S)", r"\1 ", line) for line in lines]
    lines = [line for line in lines if line]
    if not lines:
        return ""

    if len(lines) == 1 and re.fullmatch(r"\d{1,3}", lines[0]):
        return ""

    paragraphs: list[str] = []
    current = ""

    def flush() -> None:
        nonlocal current
        if current:
            cleaned_current = current.strip()
            if (
                paragraphs
                and paragraphs[-1].rstrip().endswith("-")
                and cleaned_current[:1].islower()
            ):
                paragraphs[-1] = (
                    paragraphs[-1].rstrip()[:-1] + cleaned_current
                )
            else:
                paragraphs.append(cleaned_current)
            current = ""

    for line in lines:
        is_heading = bool(HEADING_RE.match(line)) or (
            heading_size and len(line) <= 120
        )
        if is_heading:
            flush()
            level = "##" if re.match(r"^\d+\.\s+", line) else "###"
            paragraphs.append(f"{level} {line}")
            continue
        if CAPTION_RE.match(line):
            flush()
            paragraphs.append(f"> {line}")
            continue
        if re.match(r"^(?:[-*•]|\d+[.)])\s+", line):
            flush()
            paragraphs.append(line)
            continue

        if not current:
            current = line
        elif current.endswith("-") and line[:1].islower():
            current = current[:-1] + line
        else:
            current += " " + line

    flush()
    wrapped = []
    for paragraph in paragraphs:
        if paragraph.startswith("#"):
            wrapped.append(paragraph)
        elif paragraph.startswith("> "):
            content = paragraph[2:]
            wrapped.append(
                "\n".join(
                    f"> {line}"
                    for line in textwrap.wrap(
                        content,
                        width=100,
                        break_long_words=False,
                        break_on_hyphens=False,
                    )
                )
            )
        else:
            wrapped.append(
                textwrap.fill(
                    paragraph,
                    width=100,
                    break_long_words=False,
                    break_on_hyphens=False,
                )
            )
    return "\n\n".join(wrapped)


def get_layout_blocks(page: Any) -> list[LayoutBlock]:
    page_dict = page.get_text("dict", sort=False)
    blocks: list[LayoutBlock] = []
    for block in page_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        lines = []
        font_sizes = []
        for line in block.get("lines", []):
            spans = sorted(
                line.get("spans", []),
                key=lambda span: float(span.get("bbox", (0, 0, 0, 0))[0]),
            )
            fragments = []
            previous_x1 = None
            previous_text = ""
            for span in spans:
                span_text = str(span.get("text", ""))
                x0, _, x1, _ = span.get("bbox", (0, 0, 0, 0))
                font_size = float(span.get("size", 0))
                gap = float(x0) - previous_x1 if previous_x1 is not None else 0
                needs_space = (
                    previous_x1 is not None
                    and gap > max(1.2, font_size * 0.12)
                    and previous_text[-1:].isalnum()
                    and span_text[:1].isalnum()
                )
                if needs_space:
                    fragments.append(" ")
                fragments.append(span_text)
                previous_x1 = float(x1)
                previous_text = span_text
            line_text = "".join(fragments)
            if line_text.strip():
                lines.append(line_text)
            font_sizes.extend(
                float(span.get("size", 0))
                for span in spans
                if span.get("text", "").strip()
            )
        text = "\n".join(lines).strip()
        if not text:
            continue
        x0, y0, x1, y1 = block["bbox"]
        blocks.append(
            LayoutBlock(
                float(x0),
                float(y0),
                float(x1),
                float(y1),
                text,
                max(font_sizes, default=0.0),
            )
        )
    return blocks


def looks_like_two_columns(blocks: list[LayoutBlock], page_width: float) -> bool:
    if len(blocks) < 4:
        return False
    midpoint = page_width / 2
    narrow = [block for block in blocks if (block.x1 - block.x0) < page_width * 0.62]
    left = [block for block in narrow if (block.x0 + block.x1) / 2 < midpoint]
    right = [block for block in narrow if (block.x0 + block.x1) / 2 >= midpoint]
    return len(left) >= 2 and len(right) >= 2


def order_layout_blocks(
    blocks: list[LayoutBlock],
    page_width: float,
    two_columns: bool,
) -> list[LayoutBlock]:
    if not two_columns:
        return sorted(blocks, key=lambda block: (block.y0, block.x0))

    midpoint = page_width / 2
    full_width = [
        block
        for block in blocks
        if (block.x1 - block.x0) >= page_width * 0.62
        or (block.x0 < midpoint * 0.55 and block.x1 > midpoint * 1.45)
    ]
    side_blocks = [block for block in blocks if block not in full_width]
    full_width.sort(key=lambda block: (block.y0, block.x0))

    ordered: list[LayoutBlock] = []
    remaining = list(side_blocks)
    previous_y = 0.0

    for full_block in full_width:
        segment = [
            block
            for block in remaining
            if previous_y <= (block.y0 + block.y1) / 2 < full_block.y0
        ]
        left = sorted(
            [
                block
                for block in segment
                if (block.x0 + block.x1) / 2 < midpoint
            ],
            key=lambda block: (block.y0, block.x0),
        )
        right = sorted(
            [
                block
                for block in segment
                if (block.x0 + block.x1) / 2 >= midpoint
            ],
            key=lambda block: (block.y0, block.x0),
        )
        ordered.extend(left + right)
        ordered.append(full_block)
        remaining = [block for block in remaining if block not in segment]
        previous_y = full_block.y1

    left = sorted(
        [
            block
            for block in remaining
            if (block.x0 + block.x1) / 2 < midpoint
        ],
        key=lambda block: (block.y0, block.x0),
    )
    right = sorted(
        [
            block
            for block in remaining
            if (block.x0 + block.x1) / 2 >= midpoint
        ],
        key=lambda block: (block.y0, block.x0),
    )
    ordered.extend(left + right)
    return ordered


def extract_academic_page(page: Any, profile: str) -> tuple[str, bool]:
    blocks = get_layout_blocks(page)
    if not blocks:
        return "", False

    page_width = float(page.rect.width)
    two_columns = profile == "academic" or (
        profile == "auto" and looks_like_two_columns(blocks, page_width)
    )
    ordered = order_layout_blocks(blocks, page_width, two_columns)

    chunks = []
    for block in ordered:
        heading_size = (
            page.number == 0
            and block.y0 < float(page.rect.height) * 0.22
            and block.max_font_size >= 14.0
            and len(block.text) <= 140
        )
        cleaned = clean_layout_block(block.text, heading_size)
        if cleaned:
            if (
                chunks
                and chunks[-1].rstrip().endswith("-")
                and cleaned.lstrip()[:1].islower()
            ):
                chunks[-1] = chunks[-1].rstrip()[:-1] + cleaned.lstrip()
            else:
                chunks.append(cleaned)
    return "\n\n".join(chunks), two_columns


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
    profile: str,
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
            if profile in ("auto", "academic"):
                raw, two_columns = extract_academic_page(page, profile)
                engine_name = "pymupdf-columns" if two_columns else "pymupdf-blocks"
            else:
                raw = page.get_text("text", sort=layout) or ""
                engine_name = "pymupdf"
            text = normalize_text(raw)
            results.append(PageText(index + 1, text, engine_name, text_score(text)))

        metadata = {
            str(key): str(value)
            for key, value in (document.metadata or {}).items()
            if value
        }
        return results, metadata, page_count
    finally:
        document.close()


def choose_best_pages(
    candidates: list[list[PageText]],
    profile: str,
) -> list[PageText]:
    by_page: dict[int, list[PageText]] = {}
    for engine_pages in candidates:
        for page in engine_pages:
            by_page.setdefault(page.page, []).append(page)

    selected = []
    for page_number in sorted(by_page):
        page_candidates = by_page[page_number]
        column_candidate = next(
            (
                item
                for item in page_candidates
                if item.engine == "pymupdf-columns"
            ),
            None,
        )
        block_candidate = next(
            (
                item
                for item in page_candidates
                if item.engine == "pymupdf-blocks"
            ),
            None,
        )
        if profile == "academic" and (column_candidate or block_candidate):
            selected.append(column_candidate or block_candidate)
        elif profile == "auto" and column_candidate:
            selected.append(column_candidate)
        else:
            selected.append(max(page_candidates, key=lambda item: item.score))
    return selected


def extract_pdf(
    path: Path,
    engine: str,
    password: Optional[str],
    page_spec: Optional[str],
    layout: bool,
    profile: str,
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
                    path, password, page_spec, layout, profile
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

    return choose_best_pages(candidates, profile), metadata, page_count, warnings


def build_quality(pages: list[PageText]) -> dict[str, Any]:
    selected_count = len(pages)
    char_count = sum(len(page.text) for page in pages)
    empty_pages = [page.page for page in pages if not page.text.strip()]
    readable_pages = selected_count - len(empty_pages)
    readable_ratio = readable_pages / selected_count if selected_count else 0.0
    lines = [line for page in pages for line in page.text.splitlines()]
    max_line_length = max((len(line) for line in lines), default=0)
    very_long_lines = sum(1 for line in lines if len(line) > 300)
    excessive_space_lines = sum(
        1 for line in lines if re.search(r"[ \t]{12,}", line)
    )
    layout_warnings = []
    if very_long_lines:
        layout_warnings.append(
            f"{very_long_lines} lines exceed 300 characters"
        )
    if excessive_space_lines:
        layout_warnings.append(
            f"{excessive_space_lines} lines contain excessive visual spacing"
        )

    if char_count == 0 or readable_ratio < 0.25:
        status = "poor"
    elif (
        char_count < max(80, selected_count * 30)
        or readable_ratio < 0.75
        or very_long_lines > max(2, len(lines) * 0.03)
        or excessive_space_lines > max(2, len(lines) * 0.03)
    ):
        status = "partial"
    else:
        status = "good"

    return {
        "status": status,
        "char_count": char_count,
        "selected_page_count": selected_count,
        "readable_page_count": readable_pages,
        "empty_pages": empty_pages,
        "max_line_length": max_line_length,
        "very_long_lines": very_long_lines,
        "layout_warnings": layout_warnings,
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
    if quality["layout_warnings"]:
        if not payload["warnings"]:
            lines.extend(["## Warnings", ""])
        lines.extend(f"- {warning}" for warning in quality["layout_warnings"])
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
            args.profile,
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
                    args.profile,
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
    extract_parser.add_argument(
        "--profile",
        choices=("auto", "plain", "academic"),
        default="auto",
        help="Use block and column-aware reading order for academic PDFs",
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
