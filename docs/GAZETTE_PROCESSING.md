# MCA Gazette processing

`scripts/process_gazette_notifications.py` converts downloaded MCA Gazette PDFs to text,
deduplicates them, screens for the Companies Act, 2013, and uses Gemini to extract exact,
auditable legal data from relevant or uncertain documents.

## Why the pipeline is hybrid

- Text PDFs are read locally for fast, free relevance screening.
- Image-only PDFs are OCRed locally only to decide whether they need AI review.
- Gemini reads the original PDF for structured legal extraction; OCR text is never used as
  authoritative amendment wording.
- Documents with sufficient text and no Companies Act, 2013 citation are retained as text but
  excluded from Gemini calls.
- SHA-256 deduplication and per-document JSON checkpoints make interrupted runs safe to resume.

## Requirements

```bash
python -m pip install "google-genai>=1,<2" "pydantic>=2,<3" "pypdf>=5,<7"
sudo apt-get install poppler-utils tesseract-ocr
```

Set the API key in the shell that runs the extraction:

```bash
export GEMINI_API_KEY="your-key"
```

The GitHub Actions secret is not automatically available on a local computer.

## Run an inventory first

This creates text, detects duplicates, identifies obvious Companies Act candidates and reports
how many documents would require Gemini. It makes no API calls.

```bash
python scripts/process_gazette_notifications.py --inventory-only
```

The default input directory is `scripts/egazette_mca_pdfs/`. Use another directory when needed:

```bash
python scripts/process_gazette_notifications.py \
  --input-dir /path/to/989-pdfs \
  --inventory-only
```

## Run the Gemini extraction

```bash
python scripts/process_gazette_notifications.py
```

Rerun the same command after an interruption. Completed, unchanged PDFs are skipped. Use
`--force` only when every checkpoint must be regenerated. Use `--limit 10` for a small trial.

## Outputs

```text
docs/gazette_notifications/
├── index.json       # corpus counts and one row per source PDF
├── records/         # structured checkpoint/result JSON per unique PDF
└── text/            # page-marked embedded text or OCR screening text
```

Relevant notification JSON includes:

- Gazette number, Gazette part and publication date
- notification number, date, title and instrument type
- exact Companies Act, 2013 sections and enabling clause
- principal rules or instrument affected
- commencement/effective date when expressly stated
- each target, operation, exact enacted wording and PDF page reference
- complete English notification transcription

## Sample-screening validation

The nine supplied examples produced five Companies Act, 2013 candidates and four exclusions:

- Candidates: 43, 70, 88, 103 and 665
- Excluded: 341 (Insolvency and Bankruptcy Code), 558 (Chartered Accountants Act),
  584 (Companies Act, 1956) and scanned item 987 (Company Law Board recruitment rules)

This distinction is important: Ministry of Corporate Affairs publication and words such as
"company" or "Company Law Board" do not by themselves make a notification relevant to the
Companies Act, 2013.
