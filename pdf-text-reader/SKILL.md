---
name: pdf-text-reader
description: >
  Extract, inspect, clean, and structure text from PDF files, including
  encrypted PDFs and selected page ranges. Use when the user asks to read,
  summarize, search, quote, classify, translate, or convert PDF content into
  Markdown, TXT, or JSON. Preserve page boundaries and report extraction
  quality. For scanned or image-only PDFs, use the optional OCR route before
  claiming that no text is available.
---

# pdf-text-reader

Extract first, verify quality, then complete the user's actual task.

## Route Table

| PDF condition | Route | Command |
|---|---|---|
| Normal digital PDF | **EXTRACT** | `python3 scripts/pdf_text_reader.py extract input.pdf -o output.md` |
| Scanned or image-only PDF | **OCR + EXTRACT** | Add `--ocr auto` or run the `ocr` command |
| Unknown environment | **CHECK** | `python3 scripts/pdf_text_reader.py check` |

Do not use this skill to recreate a PDF's visual design. Use `minimax-pdf` when
layout, styling, form filling, or PDF generation is the main task.

## Route A: EXTRACT

Run automatic dual-engine extraction:

```bash
python3 scripts/pdf_text_reader.py extract input.pdf \
  --format markdown \
  --output output.md
```

The automatic engine runs `pypdf` and `PyMuPDF` when available, compares the
results page by page, and keeps the higher-quality text.

Use JSON for automation:

```bash
python3 scripts/pdf_text_reader.py extract input.pdf \
  --format json \
  --output output.json
```

Useful options:

| Option | Purpose |
|---|---|
| `--pages "1-3,7"` | Extract selected 1-based pages |
| `--password "secret"` | Open an encrypted PDF |
| `--engine auto` | Compare available extractors; this is the default |
| `--engine pypdf` | Force `pypdf` |
| `--engine pymupdf` | Force `PyMuPDF` |
| `--profile academic` | Rebuild reading order for two-column papers |
| `--profile plain` | Keep simple page text order |
| `--ocr auto` | OCR only when extraction quality is poor |
| `--ocr always` | OCR before extraction |
| `--ocr-language "chi_sim+eng"` | Use Chinese and English OCR languages |

## Route B: OCR + EXTRACT

Use OCR only when direct extraction is empty, very short, or badly garbled:

```bash
python3 scripts/pdf_text_reader.py extract scanned.pdf \
  --ocr auto \
  --ocr-language "chi_sim+eng" \
  --output scanned.md
```

To create a searchable intermediate PDF:

```bash
python3 scripts/pdf_text_reader.py ocr scanned.pdf searchable.pdf \
  --language "chi_sim+eng" \
  --deskew
```

Read `references/ocr-fallback.md` before diagnosing OCR installation or language
problems.

## Academic Papers

Use the academic profile for journal papers, conference papers, arXiv PDFs, and
other multi-column documents:

```bash
python3 scripts/pdf_text_reader.py extract paper.pdf \
  --profile academic \
  --format markdown \
  --output paper.md
```

This route reads text blocks by page coordinates, orders the left column before
the right column, joins wrapped paragraph lines, removes soft line-break
hyphenation, and formats detected section headings and figure captions.

Do not use layout-preserving text as the final Markdown for a multi-column
paper. Large runs of spaces reproduce page geometry but make the document hard
to read and can interleave both columns.

Equations, charts, dense tables, and text embedded in figures remain
best-effort. Preserve the page number and advise checking the source PDF when
these elements are important.

## Quality Rules

1. Preserve page boundaries for citations, quotations, and traceability.
2. Prefer Markdown for human review and JSON for downstream automation.
3. Inspect the emitted `quality` status before claiming success.
4. Treat `poor` quality as a signal to try OCR or review the source manually.
5. Do not invent text for blank, damaged, or unreadable pages.
6. Extract before summarizing, translating, searching, or classifying.

Quality is `good`, `partial`, or `poor`. The result also reports empty pages,
character count, maximum line length, layout warnings, selected engines, and
whether OCR was used.

## Output Shape

```markdown
# Extracted Text: filename.pdf

| Field | Value |
|---|---|
| Quality | good |
| OCR used | false |

## Page 1
Page text here.

## Page 2
Page text here.
```

## Environment

Check dependencies:

```bash
python3 scripts/pdf_text_reader.py check
```

Install core extraction dependencies:

```bash
python3 -m pip install -r scripts/requirements.txt
```

On Windows, use `python` instead of `python3` when that is the installed command.
