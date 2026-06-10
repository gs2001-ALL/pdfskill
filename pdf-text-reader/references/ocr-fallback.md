# OCR Fallback

Use OCR only when direct extraction returns empty, near-empty, or garbled text.
OCR is optional because it requires more system dependencies than normal PDF
text extraction.

## Check OCR Availability

```bash
python3 scripts/pdf_text_reader.py check
```

The OCR route requires:

- OCRmyPDF
- Tesseract OCR
- Ghostscript
- the Tesseract language packs required by the document

## Install

Install the Python package:

```bash
python3 -m pip install ocrmypdf
```

OCRmyPDF still needs Tesseract and Ghostscript from the operating system. Follow
the OCRmyPDF installation documentation for the current platform.

## Chinese Documents

Install the Tesseract Simplified Chinese language pack, then use:

```bash
python3 scripts/pdf_text_reader.py extract input.pdf \
  --ocr auto \
  --ocr-language "chi_sim+eng" \
  --output output.md
```

Use `chi_tra+eng` for Traditional Chinese and English.

## Manual OCR Route

Create a searchable PDF first:

```bash
python3 scripts/pdf_text_reader.py ocr input.pdf output.ocr.pdf \
  --language "chi_sim+eng" \
  --deskew
```

Then extract from the searchable PDF:

```bash
python3 scripts/pdf_text_reader.py extract output.ocr.pdf \
  --format markdown \
  --output output.md
```

## Notes

- OCR quality depends on scan resolution and language packs.
- Keep the OCR-generated PDF when later work needs stable page citations.
- Do not use `--force-ocr` unless an existing broken text layer must be
  replaced.
- Review names, numbers, tables, and punctuation manually when accuracy is
  important.
