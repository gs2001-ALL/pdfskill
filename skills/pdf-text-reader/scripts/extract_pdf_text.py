#!/usr/bin/env python3
"""Extract text from PDF files into text, Markdown, or JSON."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from pypdf import PdfReader

try:
    import fitz  # type: ignore
except ImportError:  # pragma: no cover
    fitz = None


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_with_pypdf(path: Path) -> list[str]:
    reader = PdfReader(str(path))
    pages: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        pages.append(normalize_text(text))
    return pages


def extract_with_pymupdf(path: Path) -> list[str]:
    if fitz is None:
        return []

    doc = fitz.open(path)
    try:
        return [normalize_text(page.get_text("text") or "") for page in doc]
    finally:
        doc.close()


def count_chars(pages: list[str]) -> int:
    return sum(len(page) for page in pages)


def looks_scanned(pages: list[str], min_chars: int) -> bool:
    non_empty_pages = [page for page in pages if page.strip()]
    if not pages:
        return True
    if not non_empty_pages:
        return True
    return count_chars(pages) < min_chars


def render_text(pages: list[str]) -> str:
    chunks: list[str] = []
    for index, page in enumerate(pages, start=1):
        chunks.append(f"--- Page {index} ---")
        chunks.append(page)
        chunks.append("")
    return "\n".join(chunks).strip() + "\n"


def render_markdown(source: Path, pages: list[str], engine: str, scanned: bool) -> str:
    lines = [
        f"# Extracted Text: {source.name}",
        "",
        f"- extracted_with: `{engine}`",
        f"- likely_scanned: `{str(scanned).lower()}`",
        "",
    ]
    for index, page in enumerate(pages, start=1):
        lines.extend([f"## Page {index}", "", page or "_No extractable text found on this page._", ""])
    return "\n".join(lines).rstrip() + "\n"


def render_json(source: Path, pages: list[str], engine: str, scanned: bool) -> str:
    payload = {
        "source": str(source),
        "page_count": len(pages),
        "char_count": count_chars(pages),
        "extracted_with": engine,
        "likely_scanned": scanned,
        "pages": [
            {"page": index, "chars": len(page), "text": page}
            for index, page in enumerate(pages, start=1)
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def extract_pages(path: Path) -> tuple[list[str], str]:
    pages = extract_with_pypdf(path)
    if count_chars(pages) > 0:
        return pages, "pypdf"

    fallback_pages = extract_with_pymupdf(path)
    if count_chars(fallback_pages) > 0:
        return fallback_pages, "pymupdf"

    return pages or fallback_pages, "pypdf"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract text from a PDF into text, Markdown, or JSON."
    )
    parser.add_argument("input", help="Path to the input PDF")
    parser.add_argument(
        "--format",
        choices=("text", "markdown", "json"),
        default="markdown",
        help="Output format",
    )
    parser.add_argument("--output", help="Path to the output file")
    parser.add_argument(
        "--min-chars",
        type=int,
        default=80,
        help="Threshold below which the PDF is flagged as likely scanned",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = Path(args.input).expanduser().resolve()
    if not source.exists():
        raise SystemExit(f"ERROR: input PDF not found: {source}")
    if source.suffix.lower() != ".pdf":
        raise SystemExit(f"ERROR: expected a .pdf file, got: {source.name}")

    try:
        pages, engine = extract_pages(source)
    except Exception as exc:  # pragma: no cover
        raise SystemExit(f"ERROR: failed to extract text from {source}: {exc}") from exc

    scanned = looks_scanned(pages, args.min_chars)

    if args.format == "text":
        output_text = render_text(pages)
    elif args.format == "json":
        output_text = render_json(source, pages, engine, scanned)
    else:
        output_text = render_markdown(source, pages, engine, scanned)

    if args.output:
        target = Path(args.output).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(output_text, encoding="utf-8")
    else:
        sys.stdout.write(output_text)

    if scanned:
        sys.stderr.write(
            "WARNING: very little text was extracted. "
            "This PDF is likely scanned or image-only. "
            "Try OCR next; see references/ocr-fallback.md.\n"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
