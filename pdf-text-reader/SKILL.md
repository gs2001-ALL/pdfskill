---
name: pdf-text-reader
description: >
  Extract, clean, and structure text from PDF files. Use when the user asks to
  read, summarize, search, quote, classify, or convert the text content of a
  PDF into TXT, Markdown, or JSON. Prefer this skill for text-first PDF work
  where reliable extraction matters more than visual layout recreation. If the
  PDF appears scanned or image-only, switch to the OCR fallback in
  references/ocr-fallback.md before claiming the file has no text.
license: MIT
metadata:
  version: "0.1"
  category: productivity
  sources:
    - https://pypdf.readthedocs.io/
    - https://pymupdf.readthedocs.io/
    - https://ocrmypdf.readthedocs.io/
---

# pdf-text-reader

Extract the document text first, then do the downstream task.

Read `references/ocr-fallback.md` when:

- extracted text is empty or extremely short
- the PDF is obviously scanned
- the extracted text is badly garbled

## Default route

Use the helper script to extract page-aware text:

```bash
python scripts/extract_pdf_text.py input.pdf --format markdown --output output.md
```

Use JSON when another script or workflow needs structured page output:

```bash
python scripts/extract_pdf_text.py input.pdf --format json --output output.json
```

## Rules

1. Preserve page boundaries when the user needs citations, quotes, auditing, or
   traceability.
2. Prefer Markdown for human review and JSON for automation.
3. Do not say "this PDF has no text" until you have checked the OCR fallback.
4. If the user asks for a summary, extract first and summarize from the result.
5. If the PDF is form-heavy or design-heavy, extract text here first, then hand
   off to a more specialized PDF workflow if needed.

## Suggested workflow

1. Run `scripts/extract_pdf_text.py`.
2. Check `likely_scanned` or the warning message.
3. If extraction is weak, follow `references/ocr-fallback.md`.
4. Continue with the user's real task: summarize, search, quote, classify,
   translate, or convert.

## Environment

Install dependencies before running the helper script:

```bash
pip install -r scripts/requirements.txt
```

The script is designed for text extraction from digital PDFs. OCR is a fallback,
not the default path.
