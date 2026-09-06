# Companies Act, 2013 Viewer

A searchable React viewer for the Companies Act, 2013 that combines the current Act with earlier wording from the bare Act and target-specific amendment citations.

> **Important:** This project is an informational research tool. It is not an official publication and does not provide legal advice.

## Features

- Chapter and section navigation without duplicate entries
- Full-text search across sections, subsections and clauses
- Current statutory wording generated from the supplied current-Act PDF
- Earlier omitted or substituted wording retained alongside current text
- Amendment citations matched to the exact affected section, subsection or clause
- AI-assisted extraction for image-based and text-based PDFs
- Resumable Gemini parsing with cached page-batch checkpoints
- Synchronized JSON for the source archive and React frontend
- Ordinance PDFs intentionally excluded from the current processing scope

## Included source documents

The current pipeline processes:

- Companies Act, 2013 — current/consolidated PDF
- Companies Act, 2013 — bare/original PDF
- Companies (Amendment) Act, 2015
- Companies (Amendment) Act, 2017
- Companies (Amendment) Act, 2019
- Companies (Amendment) Act, 2020

Files under `docs/ordinances/` are not processed at present.

## Project structure

```text
.
├── docs/
│   ├── ai_parsed_documents/       # Per-document Gemini output
│   └── sections_master.json       # Assembled legal-data source
├── frontend/
│   ├── public/docs/
│   │   └── sections_master.json   # Browser-facing synchronized copy
│   └── src/                       # React viewer
├── scripts/                       # Parsing, checkpointing and merge tools
└── .github/workflows/             # Resumable Gemini workflow
```

## Requirements

For the viewer:

- Node.js 20.19 or newer
- npm

For parser development:

- Python 3.12
- A Gemini API key stored as the GitHub Actions secret `GEMINI_API_KEY`

The API key is not required to run the frontend because the generated JSON is committed to the repository.

## Run locally

```bash
git clone https://github.com/arvindkumarmanisekaran-netizen/companies_act.git
cd companies_act/frontend
npm ci
npm run dev
```

Open <http://localhost:5173>.

## Production build

```bash
cd frontend
npm ci
npm run build
npm run preview
```

The preview server normally runs at <http://localhost:4173>.

## Regenerate the legal JSON

1. Add `GEMINI_API_KEY` under **Repository settings → Secrets and variables → Actions**.
2. Open **Actions → Gemini parse Companies Act PDFs**.
3. Select **Run workflow**.
4. Monitor all six parse jobs and the final assembly job.

The workflow:

1. Restores compatible page-batch checkpoints.
2. Parses missing batches with Gemini.
3. Validates and merges overlap batches.
4. Preserves historical wording only when an exact amendment target supports it.
5. Removes duplicate chapters, sections, section-number prefixes and title-only overlap artifacts.
6. Synchronizes both master JSON files.
7. Builds the frontend against the generated JSON.
8. Commits changed generated files to the working branch.

## Tests

Parser and merge tests:

```bash
python -m unittest scripts.test_ai_parse_legal_documents
python -m unittest scripts.test_pdftojson
python -m unittest scripts.test_ai_parse_with_checkpoint
```

Frontend validation:

```bash
npm --prefix frontend ci
npm --prefix frontend run build
```

## Data quality and legal disclaimer

The source PDFs include image-based documents, and the structured files are produced with AI assistance. Automated validation reduces structural errors but cannot guarantee a legally authoritative transcription.

Before relying on any provision:

- compare it with the relevant official gazette or authoritative publication;
- verify commencement notifications and effective dates;
- confirm whether later amendments, rules, circulars, judgments or ordinances apply; and
- obtain advice from a qualified legal professional where appropriate.

The project owner and contributors provide the software and project-created material without warranties, to the maximum extent permitted by law.

## Licensing

This repository uses scoped non-commercial licenses:

- **Original software code:** [PolyForm Noncommercial License 1.0.0](LICENSE)
- **Original documentation, project-created annotations and protectable data arrangement:** [CC BY-NC-SA 4.0](CONTENT-LICENSE.md)
- **Statutory text, source PDFs and third-party material:** excluded from those grants; see [Third-Party Notices](THIRD-PARTY-NOTICES.md)

These restrictions make the project **source-available**, not OSI-approved open source.

Commercial use requires separate written permission from the repository owner. To request permission, contact the owner through the repository's GitHub page.

## Attribution

When redistributing permitted material, retain:

- the applicable license or canonical license URL;
- the copyright and attribution notices;
- a link to this repository; and
- a clear description of any modifications.

Copyright © 2026 Arvind Kumar Manisekaran.
