---
name: pdf-text-reader
description: >
  Read and extract text from PDF files, then convert the result into Markdown,
  TXT, or JSON with page-aware output. Use when the user asks to read a PDF,
  extract PDF text, export Markdown, search PDF content, quote PDF passages,
  summarize a PDF, translate a PDF, or inspect encrypted PDFs and selected
  page ranges. Preserve page boundaries, report extraction quality, and use
  the optional OCR path for scanned or image-only PDFs before claiming that no
  text is available.
---

# pdf-text-reader

Extract first, check quality, then complete the user's actual task.

Use this skill when the goal is to read text from a PDF, write it into a `.md`
file, and show the result to the user.

Do not use this skill to recreate a PDF's visual design, fill forms, add
stamps, or generate a new PDF. Use `minimax-pdf` when layout fidelity or PDF
editing is the main task.

## Quick Routes

| PDF condition | Route | Command |
|---|---|---|
| Normal text PDF | **EXTRACT** | `python scripts/pdf_text_reader.py extract input.pdf -o output.md` |
| Scanned or image-only PDF | **OCR + EXTRACT** | Add `--ocr auto` or run the `ocr` subcommand first |
| Unknown environment | **CHECK** | `python scripts/pdf_text_reader.py check` |

On Windows, use `python` unless the environment only provides `python3`.

## Standard Workflow

1. Check dependencies and extraction engines first:

```bash
python scripts/pdf_text_reader.py check
```

2. Extract PDF text into Markdown:

```bash
python scripts/pdf_text_reader.py extract input.pdf \
  --format markdown \
  --output output.md
```

3. If the user asks to "show the result", after writing `output.md`:

- Read and display the generated Markdown content
- Report the output file path clearly
- If the document is long, show the first pages or the most relevant sections
  while preserving the full `.md` file

Automatic mode tries both `pypdf` and `PyMuPDF` when available, compares the
results page by page, and keeps the more readable text.

Use JSON when another tool or script will consume the output:

```bash
python scripts/pdf_text_reader.py extract input.pdf \
  --format json \
  --output output.json
```

## Common Options

| Option | Purpose |
|---|---|
| `--pages "1-3,7"` | Extract only selected pages using 1-based page numbers |
| `--password "secret"` | Open an encrypted PDF |
| `--engine auto` | Compare extraction engines automatically; default |
| `--engine pypdf` | Force `pypdf` |
| `--engine pymupdf` | Force `PyMuPDF` |
| `--profile academic` | Better for papers and multi-column PDFs |
| `--profile plain` | Use simple reading order |
| `--ocr auto` | Try OCR when extraction quality is poor |
| `--ocr always` | Always OCR before extraction |
| `--ocr-language "chi_sim+eng"` | Use Chinese and English OCR languages |

## Scanned and Image-only PDFs

Enable OCR only when direct extraction is empty, very short, or clearly garbled:

```bash
python scripts/pdf_text_reader.py extract scanned.pdf \
  --ocr auto \
  --ocr-language "chi_sim+eng" \
  --output scanned.md
```

To create a searchable intermediate PDF first:

```bash
python scripts/pdf_text_reader.py ocr scanned.pdf searchable.pdf \
  --language "chi_sim+eng" \
  --deskew
```

Read `references/ocr-fallback.md` before diagnosing OCR installation, language
packs, or operating system dependencies.

## Academic and Multi-column PDFs

Use `academic` for journal papers, conference papers, arXiv PDFs, and other
multi-column documents:

```bash
python scripts/pdf_text_reader.py extract paper.pdf \
  --profile academic \
  --format markdown \
  --output paper.md
```

This mode rebuilds reading order from text block coordinates, prefers the left
column before the right column, joins wrapped paragraphs, and formats detected
headings and captions where possible.

Do not treat raw layout-preserving text as the final Markdown for a multi-column
paper. It often mixes both columns and is harder to read.

Equations, charts, dense tables, and text embedded in figures remain
best-effort. Preserve the page number and advise checking the source PDF when
those elements matter.

## Quality Rules

1. Preserve page boundaries for citation, traceability, and source checking.
2. Prefer Markdown for human review and JSON for downstream automation.
3. Inspect the emitted `quality` status before claiming success.
4. Treat `poor` as a signal to try OCR or request manual review.
5. Do not invent text for blank, damaged, or unreadable pages.
6. Extract before summarizing, translating, searching, or classifying.

Quality is `good`, `partial`, or `poor`. The output also reports empty pages,
character count, maximum line length, layout warnings, selected engines, and
whether OCR was used.

## Markdown Output Shape

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

Check the environment:

```bash
python scripts/pdf_text_reader.py check
```

Install the core extraction dependencies:

```bash
python -m pip install -r scripts/requirements.txt
```

If you want a local dependency directory instead of installing globally:

```bash
python -m pip install --target .test-deps -r scripts/requirements.txt
```

Then set `PYTHONPATH=.test-deps` before running, or insert that directory into
`sys.path` in the command that launches the script.
