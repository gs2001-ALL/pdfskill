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

Extract the document text first, then complete the user's real task.

## Purpose

Use this skill for text-first PDF work. It is designed for cases where the user
needs to:

- read the content of a PDF
- summarize a document
- search for facts or keywords
- quote specific passages
- classify or tag document content
- translate extracted text
- convert PDF text into Markdown, TXT, or JSON

This skill is optimized for extracting readable text, not for reconstructing
complex visual layout.

## Default route

Use the helper script to extract page-aware text first:

```bash
python scripts/extract_pdf_text.py input.pdf --format markdown --output output.md
```

Use JSON when another script or workflow needs machine-readable page output:

```bash
python scripts/extract_pdf_text.py input.pdf --format json --output output.json
```

## When To Read The OCR Fallback

Read `references/ocr-fallback.md` when:

- extracted text is empty or extremely short
- the PDF is obviously scanned
- the extracted text is badly garbled
- the PDF viewer shows pages, but text cannot be selected normally

## Workflow

1. Preserve page boundaries when the user needs citations, quotes, auditing, or
   traceability.
2. Prefer Markdown for human review and JSON for automation.
3. Check extraction quality before saying the task succeeded.
4. Do not say "this PDF has no text" until you have checked the OCR fallback.
5. If the user asks for a summary, extract first and summarize from the result.
6. If the PDF is form-heavy or design-heavy, extract text here first, then hand
   off to a more specialized PDF workflow if needed.

## Quality Checks

Before continuing to downstream work, verify that:

- most pages contain readable text
- the output is not mostly blank
- the text is not heavily garbled
- page order is preserved

If these checks fail, recommend OCR instead of pretending extraction succeeded.

## Output Style

Prefer page-aware output for readability and traceability:

```markdown
# Extracted Text: filename.pdf

## Page 1
Page text here.

## Page 2
Page text here.
```

Use JSON when another tool needs structured page objects for indexing, search,
classification, or later transformation.

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
