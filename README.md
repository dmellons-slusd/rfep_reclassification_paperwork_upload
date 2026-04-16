# RFEP Reclassification Paperwork Upload

## Purpose
Automates the RFEP reclassification paperwork pipeline: downloads multi-student PDF packets from Google Drive, splits them by student, combines required documents (Notification, Reclassification Meeting, Teacher Recommendation), uploads completed packets to the document management system, updates Aeries database records, and tracks completion via Google Sheets. Also handles RFEP Monitoring Window paperwork separately.

## Key Scripts
- `main.py` — Primary workflow orchestrator (download, process, upload, track, archive)
- `rfep_monitoring_process_paperwork.py` — Standalone monitoring window PDF processor
- `reclassification_processor.py` — Core PDF processing engine (multi-language: English, Chinese, Spanish)
- `process_rfep.py` — Database integration (LAC, STU, PGM record updates)
- `google_sheets_integration.py` — Completion tracking via Google Sheets
- `folder_check.py` — Google Drive download and archival operations
- `q_update_rfep.py` — SQL query definitions
- 13 Python files total

## Database Connections
- **Aeries SQL Server**: LAC, STU, PGM tables (via slusdlib.aeries + slusdlib.core)
- **FastAPI document management system**: File uploads via REST API

## Schedule / How to Run
Windows Scheduled Task: **"RFEP Paperwork Process"**
```bash
python main.py                                 # Full automated pipeline
python rfep_monitoring_process_paperwork.py     # Monitoring window only
```

## Log Files
- `log.log` (main pipeline)
- `monitoring_log.log` (monitoring window processor)

## Dependencies
- slusdlib.aeries, slusdlib.core, PyPDF2, pandas, requests, sqlalchemy, dateparser, python-decouple
- Google API: google-auth, google-api-python-client

## Notes
- Three-layer duplicate prevention: Google Sheets check, local CSV fallback, filename convention
- Completion dates are preserved and never overwritten on re-processing
- All database operations include audit trails with timestamps
- Requires `.env` file with FastAPI, database, and Google credentials
- Multi-language PDF support: English, Chinese, Spanish
- Handles ligature normalization issues in PDF text extraction
