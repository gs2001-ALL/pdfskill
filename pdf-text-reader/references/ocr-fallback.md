# OCR Fallback

Use this fallback when direct extraction returns empty, near-empty, or garbled
text.

## Recommended path

Use `ocrmypdf` to create a searchable PDF first, then rerun
`scripts/extract_pdf_text.py`.

```bash
ocrmypdf input.pdf output.ocr.pdf
python scripts/extract_pdf_text.py output.ocr.pdf --format markdown --output output.md
```

## When to use OCR

- Pages are scans or photos
- The PDF viewer lets you see pages but you cannot select text
- The extracted output has almost no characters
- The extracted output contains mostly broken glyphs

## Notes

- OCR quality depends on scan resolution and language packs.
- For multilingual documents, install the needed OCR language data before
  running OCR.
- Keep the OCR-generated PDF as an intermediate artifact so later steps can
  quote page numbers consistently.
