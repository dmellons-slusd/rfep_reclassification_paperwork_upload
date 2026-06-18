"""
Legacy old_docs reclassification paperwork uploader.

Incorporates the backlog of legacy paperwork found in ./old_docs/ by combining each
student's three reclassification components into a single packet and uploading it to
Aeries student documents via the existing FastAPI /docs/uploadGeneral endpoint.

IMPORTANT — this script ONLY uploads documents. It performs NO Aeries database writes
(no LAC/STU/PGM updates), no archiving/moving of source files, and no Google Drive /
Google Sheets sync. It honors the TEST_RUN flag in .env.

The old_docs/ files are large Ellevation BATCH exports (cover page + many students per
PDF). Each student's section starts on a page containing "Student #:". The three folders
map to the three required packet components:

    old_docs/reclass_mtg_old/  -> "Meeting"     (Reclassification Meeting / Student Meeting Report)
    old_docs/ReclassRecForm/   -> "RecForm"     (EL Reclassification Recommendation Form)
    old_docs/RFEPmonitorOLD/   -> "Monitoring"  (RFEP Monitoring form)

A student is uploaded only if all three components are present AND each looks signed.
Students already present in out/completed_students.csv or in this script's own upload
log (out/OLD_DOCS/OLD_DOCS_UPLOAD_LOG.csv) are skipped so reruns are resumable.
"""

from datetime import datetime
import os
import sys
from pathlib import Path
import re
from typing import Optional, List, Dict, Tuple
import PyPDF2
from decouple import config
import requests
from slusdlib import core
from google_sheets_integration import sync_completed_students
import csv
import logging
import traceback

# Configure logging. Anchor the log file to the script directory so it doesn't get
# created in the caller's CWD when run from Task Scheduler / cron / another working dir.
# Use a dedicated log name so we don't clobber main.py's log.log.
LOG_FILE = Path(__file__).parent / 'old_docs_log.log'
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(str(LOG_FILE), encoding='utf-8'),
        logging.StreamHandler()  # Also print to console
    ],
    force=True,
)
logger = logging.getLogger(__name__)

# Force UTF-8 stdout so emoji prints in imported helpers (e.g. the Google Sheets
# integration) don't raise UnicodeEncodeError on a Windows cp1252 console / pipe.
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# ---------------------------------------------------------------------------
# Configuration / constants
# ---------------------------------------------------------------------------

OLD_DOCS_ROOT = Path("old_docs")

# Folder -> document type. Packet combine order is given by PRIORITY below.
FOLDER_DOCTYPES = {
    "reclass_mtg_old": "Meeting",
    "ReclassRecForm": "RecForm",
    "RFEPmonitorOLD": "Monitoring",
}

# Order the components appear in the combined packet PDF.
PRIORITY = {"Meeting": 1, "RecForm": 2, "Monitoring": 3}

# All three must be present (and signed) for a student to be "complete".
REQUIRED_DOCTYPES = {"Meeting", "RecForm", "Monitoring"}

# District (local) student ID lives in the colon form "Student #:   97484". The colon
# anchor avoids matching the 10-digit state ID "Student # 1628227697" (no colon).
STUDENT_ID_RE = re.compile(r'Student #:\s*(\d{4,6})')

# Student name renders as "Last, First" (e.g. "Student:  Chavez, Edgar;").
STUDENT_NAME_RE = re.compile(r'Student:\s*([^;\n]+)')

# A filled signature block: "Signed by:" followed by a signer name line and a Date value.
SIGNED_RE = re.compile(r'Signed by:\s*\n?\s*([^\n]+?)\s*\n?\s*Date:\s*([0-9/]{6,})', re.IGNORECASE)

OUTPUT_DIR = Path("out/OLD_DOCS")
UPLOAD_LOG_PATH = OUTPUT_DIR / "OLD_DOCS_UPLOAD_LOG.csv"
INCOMPLETE_REPORT_PATH = OUTPUT_DIR / "old_docs_incomplete_report.csv"
COMPLETED_CSV_PATH = Path("out/completed_students.csv")

LIGATURES = {
    'ﬁ': 'fi',
    'ﬂ': 'fl',
    'ﬀ': 'ff',
    'ﬃ': 'ffi',
    'ﬄ': 'ffl',
}


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def normalize_ligatures(text: str) -> str:
    """Normalize ligatures and special characters to standard ASCII."""
    for ligature, replacement in LIGATURES.items():
        text = text.replace(ligature, replacement)
    return text


def _format_name(raw: str) -> str:
    """Turn a 'Last, First' capture into 'First Last' (split on first comma only)."""
    raw = re.sub(r'\s+', ' ', raw).strip().strip(';').strip()
    if ',' in raw:
        last, first = raw.split(',', 1)
        name = f"{first.strip()} {last.strip()}".strip()
    else:
        name = raw
    return name if name else "Unknown"


def extract_section_header(text: str) -> Optional[Dict[str, str]]:
    """
    If `text` is a student section header page, return {'student_id', 'student_name'}.
    Returns None for continuation/score pages (no 'Student #:' marker).
    """
    id_match = STUDENT_ID_RE.search(text)
    if not id_match:
        return None
    student_id = id_match.group(1)

    name_match = STUDENT_NAME_RE.search(text)
    student_name = _format_name(name_match.group(1)) if name_match else "Unknown"

    return {'student_id': student_id, 'student_name': student_name}


def is_section_signed(text: str) -> Optional[Tuple[str, str]]:
    """
    Best-effort completion check. Returns (signer, date) if the section shows a filled
    signature block, else None.
    """
    m = SIGNED_RE.search(text)
    if m and len(m.group(1).strip()) > 1:
        return (m.group(1).strip(), m.group(2).strip())
    return None


# ---------------------------------------------------------------------------
# Batch PDF splitting
# ---------------------------------------------------------------------------

def split_batch_pdf(pdf_path: Path, doc_type: str) -> List[Dict]:
    """
    Split one Ellevation batch PDF into per-student sections.

    A new section starts on any page containing 'Student #:'. Each section's page range
    is [header_page, next_header_page). Memory is bounded: we extract page text in a
    single pass, keep only the per-section text needed for the signed check, and never
    hold all pages of a huge (1,200+ page) reader in memory at once.

    Returns list of dicts:
        {pdf_path, doc_type, student_id, student_name, pages:[int], signed:bool, signer}
    """
    sections: List[Dict] = []
    try:
        with open(pdf_path, 'rb') as fh:
            reader = PyPDF2.PdfReader(fh)
            total_pages = len(reader.pages)

            # Pass 1: locate header pages (cheap to keep just ints + small dicts).
            header_pages: List[Dict] = []
            for page_num in range(total_pages):
                text = normalize_ligatures(reader.pages[page_num].extract_text() or "")
                info = extract_section_header(text)
                if info:
                    header_pages.append({'page_num': page_num, **info})

            # Pass 2: build page ranges and compute the signed flag per section.
            for i, header in enumerate(header_pages):
                start = header['page_num']
                end = header_pages[i + 1]['page_num'] if i + 1 < len(header_pages) else total_pages
                pages = list(range(start, end))

                # Check the header page first; only scan the rest of the section if needed.
                signed_info = None
                for page_num in pages:
                    text = normalize_ligatures(reader.pages[page_num].extract_text() or "")
                    signed_info = is_section_signed(text)
                    if signed_info:
                        break

                sections.append({
                    'pdf_path': str(pdf_path),
                    'doc_type': doc_type,
                    'student_id': header['student_id'],
                    'student_name': header['student_name'],
                    'pages': pages,
                    'signed': signed_info is not None,
                    'signer': f"{signed_info[0]} ({signed_info[1]})" if signed_info else "",
                })
    except Exception as e:
        logger.error(f"Error processing {pdf_path}: {e}")
        traceback.print_exc()

    return sections


def process_all_folders() -> List[Dict]:
    """Split every batch PDF across all three old_docs folders."""
    all_sections: List[Dict] = []
    for folder_name, doc_type in FOLDER_DOCTYPES.items():
        folder = OLD_DOCS_ROOT / folder_name
        if not folder.is_dir():
            logger.warning(f"Folder not found, skipping: {folder}")
            core.log(f"WARNING: old_docs folder not found: {folder}")
            continue

        pdf_files = sorted(folder.glob("*.pdf"))
        folder_sections: List[Dict] = []
        for pdf_file in pdf_files:
            logger.info(f"Splitting {pdf_file.name} ({doc_type})...")
            folder_sections.extend(split_batch_pdf(pdf_file, doc_type))

        unique_ids = {s['student_id'] for s in folder_sections}
        signed_ct = sum(1 for s in folder_sections if s['signed'])
        logger.info(
            f"{folder_name}: {len(pdf_files)} PDF(s) -> {len(folder_sections)} section(s), "
            f"{len(unique_ids)} unique student(s), {signed_ct} signed"
        )
        core.log(
            f"old_docs {folder_name}: {len(folder_sections)} sections, "
            f"{len(unique_ids)} unique students, {signed_ct} signed"
        )
        all_sections.extend(folder_sections)

    return all_sections


def group_sections_by_student(sections: List[Dict]) -> Dict[str, Dict[str, Dict]]:
    """
    Group sections as {student_id: {doc_type: section}}.

    Collision rule (same student + same doc_type appearing more than once): prefer a
    signed section; among equal-signed, keep the first encountered. Log every collision.
    """
    grouped: Dict[str, Dict[str, Dict]] = {}
    for section in sections:
        sid = section['student_id']
        dtype = section['doc_type']
        by_type = grouped.setdefault(sid, {})

        existing = by_type.get(dtype)
        if existing is None:
            by_type[dtype] = section
            continue

        # Collision: prefer signed over unsigned; otherwise keep the existing (first) one.
        logger.info(
            f"Duplicate {dtype} section for student {sid} "
            f"(existing signed={existing['signed']}, new signed={section['signed']}) - "
            f"keeping {'new' if (section['signed'] and not existing['signed']) else 'first'}"
        )
        if section['signed'] and not existing['signed']:
            by_type[dtype] = section

    return grouped


def determine_complete_students(
    grouped: Dict[str, Dict[str, Dict]]
) -> Tuple[List[Dict], List[Dict]]:
    """
    Split grouped students into (complete, incomplete).

    Complete = all three required doc types present AND each present-and-signed.
    Incomplete entries carry present/missing/unsigned detail for the report.
    """
    complete: List[Dict] = []
    incomplete: List[Dict] = []

    for sid, by_type in grouped.items():
        present = set(by_type.keys())
        signed = {t for t in present if by_type[t]['signed']}
        # Pick a display name from any available section.
        student_name = next(iter(by_type.values()))['student_name']

        if REQUIRED_DOCTYPES.issubset(present) and REQUIRED_DOCTYPES.issubset(signed):
            complete.append({
                'student_id': sid,
                'student_name': student_name,
                'sections': by_type,
            })
        else:
            missing = REQUIRED_DOCTYPES - present
            unsigned = (present & REQUIRED_DOCTYPES) - signed
            incomplete.append({
                'student_id': sid,
                'student_name': student_name,
                'present': sorted(present & REQUIRED_DOCTYPES),
                'missing': sorted(missing),
                'unsigned': sorted(unsigned),
            })

    return complete, incomplete


# ---------------------------------------------------------------------------
# Packet building
# ---------------------------------------------------------------------------

def build_packet_pdf(student: Dict) -> Optional[str]:
    """
    Combine a complete student's three components into one packet PDF, ordered by
    PRIORITY (Meeting -> RecForm -> Monitoring). One packet built/written at a time so
    memory stays bounded even with huge source PDFs.

    Returns the output file path, or None on failure.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    student_id = student['student_id']
    name_for_file = student['student_name'].replace(' ', '_')
    output_path = OUTPUT_DIR / f"{student_id}_{name_for_file}_Reclassification_Paperwork.pdf"

    ordered = sorted(
        student['sections'].values(),
        key=lambda s: PRIORITY.get(s['doc_type'], 999),
    )

    writer = PyPDF2.PdfWriter()
    open_readers = []
    try:
        for section in ordered:
            fh = open(section['pdf_path'], 'rb')
            open_readers.append(fh)
            reader = PyPDF2.PdfReader(fh)
            for page_num in section['pages']:
                if page_num < len(reader.pages):
                    writer.add_page(reader.pages[page_num])

        with open(output_path, 'wb') as out_file:
            writer.write(out_file)
    except Exception as e:
        logger.error(f"Error building packet for student {student_id}: {e}")
        traceback.print_exc()
        return None
    finally:
        for fh in open_readers:
            try:
                fh.close()
            except Exception:
                pass

    logger.info(f"Built packet for {student_id} ({student['student_name']}): {output_path.name}")
    return str(output_path)


def export_incomplete_components_to_inbox(
    grouped: Dict[str, Dict[str, Dict]],
    complete_ids: set,
    in_dir: Path = Path("in"),
) -> Tuple[int, int]:
    """
    Write each INCOMPLETE student's SIGNED components as individual per-student PDFs into
    the normal pipeline's `in/` bucket, so the daily reclassification script considers them
    alongside newly-arriving documents when assembling completable packets.

    - Only incomplete students (not in complete_ids) are exported; the 490 complete ones are
      already uploaded and must not be re-processed (which would trigger DB writes).
    - Only SIGNED components are written, preserving the signed-quality bar (the normal
      processor does not check signatures, so we withhold unsigned components).
    - One file per (student, component) so the normal processor groups them by student and
      combines them with any later normal documents. Files are named OLDDOC_<id>_<type>.pdf
      so they're identifiable/removable.

    Returns (files_written, students_touched).
    """
    in_dir.mkdir(exist_ok=True)
    files_written = 0
    students_touched = 0

    for sid, by_type in grouped.items():
        if sid in complete_ids:
            continue
        wrote_for_student = False
        for doc_type, section in by_type.items():
            if not section['signed']:
                continue
            out_path = in_dir / f"OLDDOC_{sid}_{doc_type}.pdf"
            try:
                with open(section['pdf_path'], 'rb') as fh:
                    reader = PyPDF2.PdfReader(fh)
                    writer = PyPDF2.PdfWriter()
                    for page_num in section['pages']:
                        if page_num < len(reader.pages):
                            writer.add_page(reader.pages[page_num])
                    with open(out_path, 'wb') as out_file:
                        writer.write(out_file)
                files_written += 1
                wrote_for_student = True
            except Exception as e:
                logger.error(f"Error exporting {doc_type} for student {sid} to {in_dir}: {e}")
        if wrote_for_student:
            students_touched += 1

    logger.info(
        f"Exported {files_written} signed component file(s) for {students_touched} "
        f"incomplete student(s) into {in_dir}/"
    )
    core.log(
        f"old_docs: exported {files_written} incomplete signed component(s) for "
        f"{students_touched} student(s) into {in_dir}/ bucket"
    )
    return files_written, students_touched


# ---------------------------------------------------------------------------
# Dedup sources
# ---------------------------------------------------------------------------

def _read_ids_from_csv(path: Path, column: str) -> set:
    """Read a set of string IDs from `column` of a CSV; empty set if missing/unreadable."""
    ids = set()
    try:
        if not path.exists():
            return ids
        with open(path, 'r', newline='', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                value = (row.get(column) or '').strip()
                if value:
                    ids.add(value)
    except Exception as e:
        logger.warning(f"Could not read IDs from {path}: {e}")
    return ids


def get_already_uploaded_ids() -> set:
    """
    Union of students to skip:
      - out/completed_students.csv  (the main pipeline's already-uploaded RECLASS packets)
      - out/OLD_DOCS/OLD_DOCS_UPLOAD_LOG.csv  (this script's own log, for resumability)
    """
    completed = _read_ids_from_csv(COMPLETED_CSV_PATH, 'Student ID')
    own_log = _read_ids_from_csv(UPLOAD_LOG_PATH, 'Student ID')
    logger.info(
        f"Dedup: {len(completed)} in completed_students.csv, {len(own_log)} in OLD_DOCS log"
    )
    return completed | own_log


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

def upload_packets(
    packet_files: List[str],
    already_uploaded: set,
    test_run: bool = True,
) -> Tuple[List[str], List[Dict], List[str]]:
    """
    Upload combined packet PDFs to the document management system as document_type
    "RECLASS". Skips any student already in `already_uploaded`.

    Returns (success_files, newly_uploaded, errors).
    """
    print("\n" + "=" * 70)
    print("UPLOADING LEGACY PACKETS TO DOCUMENT MANAGEMENT SYSTEM")
    print("=" * 70)
    core.log("=" * 50)
    core.log("Uploading legacy old_docs packets (document_type=RECLASS)")
    core.log("=" * 50)

    errors: List[str] = []

    # Authenticate with FastAPI.
    try:
        core.log(f"Authenticating with FastAPI at {config('FAST_API_URL')}")
        data = {"username": config('FAST_API_USERNAME'), "password": config('FAST_API_PASSWORD')}
        token_response = requests.post(
            f"{config('FAST_API_URL')}/token",
            data=data,
            timeout=30,
        )
        if token_response.status_code != 200:
            error_msg = f"Failed to authenticate with FastAPI: Status {token_response.status_code} - {token_response.text}"
            core.log(f"ERROR: {error_msg}")
            logger.error(error_msg)
            errors.append(error_msg)
            return [], [], errors

        token = token_response.json().get('token')
        if not token:
            error_msg = "Failed to get authentication token from FastAPI response"
            core.log(f"ERROR: {error_msg}")
            logger.error(error_msg)
            errors.append(error_msg)
            return [], [], errors

        core.log("Successfully authenticated with FastAPI")

    except requests.exceptions.Timeout:
        error_msg = f"Timeout connecting to FastAPI at {config('FAST_API_URL')}"
        core.log(f"ERROR: {error_msg}")
        logger.error(error_msg)
        errors.append(error_msg)
        return [], [], errors
    except requests.exceptions.ConnectionError as e:
        error_msg = f"Connection error to FastAPI: {e}"
        core.log(f"ERROR: {error_msg}")
        logger.error(error_msg)
        errors.append(error_msg)
        return [], [], errors
    except Exception as e:
        error_msg = f"Unexpected error during FastAPI authentication: {e}"
        core.log(f"ERROR: {error_msg}")
        logger.error(error_msg)
        errors.append(error_msg)
        return [], [], errors

    success_files: List[str] = []
    newly_uploaded: List[Dict] = []
    skipped_count = 0

    core.log(f"Processing {len(packet_files)} packet(s) for upload")

    for file_path in packet_files:
        basename = os.path.basename(file_path)
        student_id = basename.split('_')[0].strip()

        # Recover student name from filename: {id}_{First}_{Last}_Reclassification_Paperwork.pdf
        parts = basename.replace('.pdf', '').split('_')
        try:
            reclass_idx = parts.index('Reclassification')
            student_name = ' '.join(parts[1:reclass_idx])
        except ValueError:
            student_name = ' '.join(parts[1:-2]) if len(parts) > 3 else 'Unknown'

        if student_id in already_uploaded:
            print(f"  Skipping student ID {student_id} ({student_name}) - already uploaded")
            core.log(f"Skipping student {student_id} ({student_name}) - already uploaded")
            skipped_count += 1
            continue

        print(f"  Uploading for student ID: {student_id} ({student_name})")
        core.log(f"Uploading legacy packet for student {student_id} ({student_name})")

        try:
            with open(file_path, 'rb') as pdf_file:
                response = requests.post(
                    f"{config('FAST_API_URL')}/docs/uploadGeneral",
                    headers={"Authorization": f"Bearer {token}"},
                    files={"file": (basename, pdf_file, 'application/pdf')},
                    data={
                        "student_id": student_id,
                        "document_name": basename.replace('_', ' '),
                        "document_type": "RECLASS",
                        "test_run": test_run,
                    },
                    timeout=60,
                )

            if response.status_code != 200:
                error_msg = f"Failed to upload for student {student_id}: Status {response.status_code} - {response.text}"
                print(f"    Failed to upload: {response.text}")
                core.log(f"ERROR: {error_msg}")
                logger.error(error_msg)
                errors.append(error_msg)
                continue

            print(f"    Successfully uploaded")
            core.log(f"Successfully uploaded legacy packet for student {student_id}")
            success_files.append(file_path)
            newly_uploaded.append({
                'student_id': student_id,
                'student_name': student_name,
                'completed_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'output_file': basename,
            })

        except requests.exceptions.Timeout:
            error_msg = f"Timeout uploading packet for student {student_id}"
            print(f"    Error uploading: Timeout")
            core.log(f"ERROR: {error_msg}")
            logger.error(error_msg)
            errors.append(error_msg)
            continue
        except Exception as e:
            error_msg = f"Error uploading packet for student {student_id}: {e}"
            print(f"    Error uploading: {e}")
            core.log(f"ERROR: {error_msg}")
            logger.error(error_msg)
            errors.append(error_msg)
            continue

    print(f"\nUpload Summary:")
    print(f"  Successfully uploaded: {len(success_files)} file(s)")
    print(f"  Skipped (already uploaded): {skipped_count}")
    if errors:
        print(f"  Failed: {len(errors)} file(s)")
    print("=" * 70)

    core.log("Upload Summary:")
    core.log(f"  - Successfully uploaded: {len(success_files)} file(s)")
    core.log(f"  - Skipped (already uploaded): {skipped_count}")
    core.log(f"  - Failed: {len(errors)} file(s)")
    if errors:
        core.log("Upload Errors:")
        for error in errors:
            core.log(f"  - {error}")

    return success_files, newly_uploaded, errors


# ---------------------------------------------------------------------------
# Reports / logs
# ---------------------------------------------------------------------------

def append_upload_log(newly_uploaded: List[Dict]) -> int:
    """Append newly uploaded students to the OLD_DOCS upload log (own state, resumable)."""
    if not newly_uploaded:
        return 0

    UPLOAD_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing_ids = _read_ids_from_csv(UPLOAD_LOG_PATH, 'Student ID')

    write_header = not UPLOAD_LOG_PATH.exists() or os.path.getsize(UPLOAD_LOG_PATH) == 0
    added = 0
    with open(UPLOAD_LOG_PATH, 'a', newline='', encoding='utf-8') as f:
        fieldnames = ['Student ID', 'Student Name', 'Completed Date', 'Output File']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        for student in newly_uploaded:
            sid = str(student['student_id'])
            if sid in existing_ids:
                continue
            writer.writerow({
                'Student ID': sid,
                'Student Name': student['student_name'],
                'Completed Date': student['completed_date'],
                'Output File': student['output_file'],
            })
            existing_ids.add(sid)
            added += 1

    logger.info(f"Updated OLD_DOCS upload log with {added} new student(s)")
    return added


def load_upload_log_students() -> List[Dict]:
    """Read every student we've recorded in the OLD_DOCS upload log (authoritative
    record of successful legacy uploads). Used to keep the normal completion records
    in sync idempotently, including any uploaded via a one-off smoke test."""
    students: List[Dict] = []
    if UPLOAD_LOG_PATH.exists():
        with open(UPLOAD_LOG_PATH, 'r', newline='', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                students.append({
                    'student_id': (row.get('Student ID') or '').strip(),
                    'student_name': row.get('Student Name', ''),
                    'completed_date': row.get('Completed Date', ''),
                    'output_file': row.get('Output File', ''),
                })
    return students


def update_completed_students_csv(students: List[Dict]) -> int:
    """Merge uploaded students into out/completed_students.csv (the normal pipeline's
    completion record). Preserves existing rows / original completion dates; only adds
    students not already present. Mirrors main.py's Step 3a."""
    if not students:
        return 0

    existing: Dict[str, Dict] = {}
    if COMPLETED_CSV_PATH.exists():
        with open(COMPLETED_CSV_PATH, 'r', newline='', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                existing[row['Student ID']] = row

    added = 0
    for student in students:
        sid = str(student['student_id'])
        if sid and sid not in existing:
            existing[sid] = {
                'Student ID': sid,
                'Student Name': student['student_name'],
                'Completed Date': student['completed_date'],
                'Output File': student['output_file'],
            }
            added += 1

    COMPLETED_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(COMPLETED_CSV_PATH, 'w', newline='', encoding='utf-8') as f:
        fieldnames = ['Student ID', 'Student Name', 'Completed Date', 'Output File']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for sid in sorted(existing.keys()):
            writer.writerow(existing[sid])

    logger.info(f"Updated completed_students.csv with {added} new student(s)")
    return added


def sync_to_google_sheet(students: List[Dict], all_errors: List[str]) -> None:
    """Sync uploaded students to the completed-students Google Sheet (the normal
    pipeline's shared record). No-op if the sheet URL isn't configured. Mirrors
    main.py's Step 3b; the sheet helper dedups internally, so this is idempotent."""
    if not students:
        return
    try:
        sheet_url = config('GOOGLE_DRIVE_COMPLETED_STUDENTS_SHEET_URL', default=None)
        creds_file = config('GOOGLE_CREDS_FILE')
        if sheet_url:
            core.log("Syncing legacy completed students with Google Sheet...")
            result = sync_completed_students(
                creds_file=creds_file,
                spreadsheet_url=sheet_url,
                new_students=students,
                sheet_name='Sheet1',
            )
            core.log(f"Google Sheet sync complete: Added {result.get('added_count', 0)} student(s)")
            logger.info(f"Google Sheet sync complete: Added {result.get('added_count', 0)} student(s)")
        else:
            core.log("WARNING: Google Sheet URL not configured - skipping sync")
            logger.warning("Google Sheet URL not configured - skipping sync")
    except Exception as e:
        msg = f"Google Sheet sync failed: {e}"
        logger.error(msg)
        core.log(f"ERROR: {msg}")
        all_errors.append(msg)


def write_incomplete_report(incomplete: List[Dict]) -> None:
    """Write a CSV of students skipped for incompleteness (missing or unsigned components)."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(INCOMPLETE_REPORT_PATH, 'w', newline='', encoding='utf-8') as f:
        fieldnames = ['Student ID', 'Student Name', 'Present', 'Missing', 'Unsigned']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for s in sorted(incomplete, key=lambda x: x['student_id']):
            writer.writerow({
                'Student ID': s['student_id'],
                'Student Name': s['student_name'],
                'Present': ', '.join(s['present']),
                'Missing': ', '.join(s['missing']),
                'Unsigned': ', '.join(s['unsigned']),
            })
    logger.info(f"Wrote incomplete report ({len(incomplete)} student(s)): {INCOMPLETE_REPORT_PATH}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    """Standalone execution: split -> group -> gate -> dedup -> combine -> upload. No DB."""
    start_time = datetime.now()
    all_errors: List[str] = []

    print("\n" + "=" * 70)
    print("LEGACY old_docs RECLASSIFICATION PAPERWORK UPLOAD")
    print("=" * 70)
    print(f"Started: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    logger.info("=" * 70)
    logger.info("LEGACY OLD_DOCS UPLOAD STARTED")
    logger.info(f"Start time: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 70)
    core.log("=" * 60)
    core.log("LEGACY OLD_DOCS RECLASSIFICATION UPLOAD STARTED")
    core.log(f"Start time: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    core.log("=" * 60)

    newly_uploaded: List[Dict] = []
    upload_errors: List[str] = []
    incomplete: List[Dict] = []
    complete: List[Dict] = []

    # Step 1: split all batch PDFs into per-student sections.
    print("\nSTEP 1: Split old_docs batch PDFs into per-student sections")
    try:
        sections = process_all_folders()
        print(f"Found {len(sections)} student section(s) across all folders")
    except Exception as e:
        error_msg = f"Error in Step 1 (splitting): {e}"
        logger.error(error_msg)
        core.log(f"ERROR: {error_msg}")
        all_errors.append(error_msg)
        sections = []

    # Step 2: group by student and gate on completeness.
    print("\nSTEP 2: Group by student and determine complete packets")
    grouped = group_sections_by_student(sections)
    complete, incomplete = determine_complete_students(grouped)
    print(f"  Total students: {len(grouped)}")
    print(f"  Complete (all 3 present & signed): {len(complete)}")
    print(f"  Incomplete: {len(incomplete)}")
    core.log(f"old_docs students: {len(grouped)} total, {len(complete)} complete, {len(incomplete)} incomplete")

    # Step 2a: export incomplete students' signed components into the normal `in/` bucket so
    # the daily reclassification script can complete them as more documents arrive. Complete
    # students are excluded (already uploaded; re-processing would trigger DB writes).
    complete_ids = {s['student_id'] for s in complete}
    try:
        exported_files, exported_students = export_incomplete_components_to_inbox(grouped, complete_ids)
        print(f"  Exported {exported_files} signed component(s) for {exported_students} incomplete student(s) into in/")
    except Exception as e:
        error_msg = f"Error exporting incomplete components to in/: {e}"
        logger.error(error_msg)
        core.log(f"ERROR: {error_msg}")
        all_errors.append(error_msg)

    # Step 3: skip students already uploaded (completed_students.csv or own log).
    already_uploaded = get_already_uploaded_ids()
    to_build = [s for s in complete if s['student_id'] not in already_uploaded]
    already_skipped = len(complete) - len(to_build)
    print(f"  Already uploaded (skipped before building): {already_skipped}")
    print(f"  Packets to build & upload: {len(to_build)}")
    core.log(f"old_docs: {already_skipped} already uploaded, {len(to_build)} to upload")

    # Step 4: build packets.
    print("\nSTEP 3: Build combined packets")
    packet_files: List[str] = []
    for student in to_build:
        path = build_packet_pdf(student)
        if path:
            packet_files.append(path)
        else:
            all_errors.append(f"Failed to build packet for student {student['student_id']}")
    print(f"  Built {len(packet_files)} packet(s)")

    # Step 5: upload packets as RECLASS (no DB writes).
    if packet_files:
        print("\nSTEP 4: Upload packets to document system")
        _success_files, newly_uploaded, upload_errors = upload_packets(
            packet_files,
            already_uploaded,
            test_run=config('TEST_RUN', default='False', cast=bool),
        )
        if upload_errors:
            all_errors.extend(upload_errors)
    else:
        print("\nSTEP 4: Skipped (no packets to upload)")
        core.log("old_docs: no packets to upload")

    # Step 6: update own upload log + write incomplete report.
    if newly_uploaded:
        added = append_upload_log(newly_uploaded)
        print(f"\nUpdated OLD_DOCS upload log with {added} new student(s)")
        core.log("===== NEWLY UPLOADED LEGACY STUDENTS =====")
        core.log(f"Count: {len(newly_uploaded)} | Run: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        for student in newly_uploaded:
            core.log(
                f"NEW_OLDDOC | id={student['student_id']} | name={student['student_name']} "
                f"| completed={student['completed_date']} | file={student['output_file']}"
            )
        core.log("===== END NEWLY UPLOADED LEGACY STUDENTS =====")

        # Keep the normal completion records in sync (local CSV + Google Sheet).
        # Drive off the full upload log so it's idempotent and backfills any student
        # uploaded outside a full run (e.g. a one-off smoke test). No DB writes.
        logged_students = load_upload_log_students()
        added_csv = update_completed_students_csv(logged_students)
        print(f"Updated completed_students.csv (+{added_csv} new of {len(logged_students)} logged)")
        sync_to_google_sheet(logged_students, all_errors)

    try:
        write_incomplete_report(incomplete)
    except Exception as e:
        error_msg = f"Error writing incomplete report: {e}"
        logger.error(error_msg)
        core.log(f"ERROR: {error_msg}")
        all_errors.append(error_msg)

    # Final summary.
    end_time = datetime.now()
    elapsed = end_time - start_time

    print("\n" + "=" * 70)
    print("PROCESSING COMPLETE")
    print("=" * 70)
    print(f"Finished: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Elapsed: {elapsed}")
    print(f"Sections found: {len(sections)}")
    print(f"Complete students: {len(complete)}")
    print(f"Incomplete students: {len(incomplete)}")
    print(f"Already uploaded (skipped): {already_skipped}")
    print(f"Newly uploaded: {len(newly_uploaded)}")
    if all_errors:
        print(f"Errors encountered: {len(all_errors)}")
    print("=" * 70)

    logger.info("=" * 70)
    logger.info("LEGACY OLD_DOCS UPLOAD COMPLETE")
    logger.info(f"End time: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Total elapsed time: {elapsed}")
    logger.info(f"Sections found: {len(sections)}")
    logger.info(f"Complete students: {len(complete)}")
    logger.info(f"Incomplete students: {len(incomplete)}")
    logger.info(f"Already uploaded (skipped): {already_skipped}")
    logger.info(f"Newly uploaded: {len(newly_uploaded)}")
    if all_errors:
        logger.info(f"Total errors: {len(all_errors)}")
        for error in all_errors:
            logger.error(f"  - {error}")
    logger.info("=" * 70)

    core.log("=" * 60)
    core.log("LEGACY OLD_DOCS RECLASSIFICATION UPLOAD COMPLETE")
    core.log(f"End time: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    core.log(f"Total elapsed time: {elapsed}")
    core.log(f"Sections found: {len(sections)}")
    core.log(f"Complete students: {len(complete)}")
    core.log(f"Incomplete students: {len(incomplete)}")
    core.log(f"Already uploaded (skipped): {already_skipped}")
    core.log(f"Newly uploaded: {len(newly_uploaded)}")
    if all_errors:
        core.log(f"ERRORS ENCOUNTERED: {len(all_errors)}")
        for error in all_errors:
            core.log(f"  - {error}")
    core.log("=" * 60)


if __name__ == "__main__":
    main()
