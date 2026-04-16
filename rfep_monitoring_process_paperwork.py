from datetime import datetime
import os
from pathlib import Path
import re
from typing import Optional, List, Dict, Tuple
import PyPDF2
from decouple import config
import requests
from slusdlib import core
import csv
import logging
import traceback

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('monitoring_log.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

window = config('RFEP_MONITORING_WINDOW', default=2 )

UPLOAD_LOG_PATH = Path("out/RFEP_MONITOR/MONITORING_UPLOAD_LOG.csv")


class MonitoringProcessor:
    """Processor for RFEP Monitoring Window paperwork"""

    HEADER_PATTERN = re.compile(
        r'RFEP\s+Monitoring\s+W\s*indow\s+(\d+).*Form Name:\s*RFEP Monitoring Form',
        re.DOTALL | re.IGNORECASE,
    )

    def __init__(
        self,
        input_dir: str = f"RFEP_Monitoring_Window/RFEP Monitoring Window {window}",
        output_dir: str = "out/RFEP_MONITOR",
    ):
        self.input_dir = Path(input_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"MonitoringProcessor initialized - Input: {self.input_dir}, Output: {self.output_dir}")

    def process_pdfs(self) -> List[Dict]:
        """Process all monitoring PDFs and return list of student info dicts."""
        pdf_files = sorted(self.input_dir.glob("*.pdf"))
        if not pdf_files:
            logger.warning(f"No PDF files found in {self.input_dir}")
            core.log(f"Monitoring Processing: No PDF files found in {self.input_dir}")
            return []

        core.log(f"Monitoring Processing: Found {len(pdf_files)} PDF file(s) to process")
        all_students: List[Dict] = []

        for pdf_file in pdf_files:
            logger.info(f"Processing {pdf_file.name}...")
            core.log(f"Monitoring Processing: Processing {pdf_file.name}")
            students = self._process_pdf_file(pdf_file)
            all_students.extend(students)

        logger.info(f"Found {len(all_students)} total student forms across {len(pdf_files)} PDFs")
        return all_students

    def _process_pdf_file(self, pdf_path: Path) -> List[Dict]:
        """Process a single PDF and return student dicts with page ranges."""
        students = []
        try:
            with open(pdf_path, 'rb') as file:
                reader = PyPDF2.PdfReader(file)
                total_pages = len(reader.pages)
                logger.info(f"{pdf_path.name}: {total_pages} pages")

                # Find all header pages and extract student info
                header_pages = []
                for page_num in range(total_pages):
                    text = reader.pages[page_num].extract_text() or ""
                    match = self.HEADER_PATTERN.search(text)
                    if match:
                        info = self._extract_student_info(text, match)
                        if info:
                            header_pages.append({
                                'page_num': page_num,
                                'student_id': info['student_id'],
                                'student_name': info['student_name'],
                                'window_num': info['window_num'],
                            })

                # Determine page ranges per student
                for i, header in enumerate(header_pages):
                    start = header['page_num']
                    end = header_pages[i + 1]['page_num'] if i + 1 < len(header_pages) else total_pages
                    pages = list(range(start, end))
                    students.append({
                        'pdf_path': str(pdf_path),
                        'student_id': header['student_id'],
                        'student_name': header['student_name'],
                        'window_num': header['window_num'],
                        'pages': pages,
                    })
                    logger.debug(f"Student {header['student_id']} ({header['student_name']}): pages {start+1}-{end}")

        except Exception as e:
            logger.error(f"Error processing {pdf_path}: {e}")
            traceback.print_exc()

        return students

    def _extract_student_info(self, text: str, header_match: re.Match) -> Optional[Dict[str, str]]:
        """Extract student ID, name, and window number from a header page."""
        window_num = header_match.group(1)

        # Student ID
        id_match = re.search(r'Student ID[#:\s]*(\d{5,6})', text, re.IGNORECASE)
        if not id_match:
            return None
        student_id = id_match.group(1)

        # Student name - appears as "Name:FirstName LastName" in these PDFs
        name_match = re.search(r'Name:([A-Za-z][A-Za-z\s\'-]{2,50}?)(?:\n|Student ID)', text)
        student_name = "Unknown"
        if name_match:
            name = name_match.group(1).strip()
            name = re.sub(r'\s+', ' ', name)
            if len(name) > 2 and not any(ch.isdigit() for ch in name):
                student_name = name

        return {'student_id': student_id, 'student_name': student_name, 'window_num': window_num}

    def create_per_student_pdfs(self, students: List[Dict]) -> List[str]:
        """Create individual PDFs per student. Returns list of output file paths."""
        created_files = []
        # Group by pdf_path to avoid re-reading the same PDF many times
        by_pdf: Dict[str, List[Dict]] = {}
        for s in students:
            by_pdf.setdefault(s['pdf_path'], []).append(s)

        for pdf_path, student_list in by_pdf.items():
            try:
                with open(pdf_path, 'rb') as file:
                    reader = PyPDF2.PdfReader(file)
                    for student in student_list:
                        output_filename = (
                            f"{student['student_id']}_{student['student_name'].replace(' ', '_')}"
                            f"_RFEP_Monitoring_Window_{student['window_num']}_Document.pdf"
                        )
                        output_path = self.output_dir / output_filename

                        writer = PyPDF2.PdfWriter()
                        for page_num in student['pages']:
                            if page_num < len(reader.pages):
                                writer.add_page(reader.pages[page_num])

                        with open(output_path, 'wb') as out_file:
                            writer.write(out_file)

                        created_files.append(str(output_path))
                        logger.debug(f"Created {output_filename} ({len(student['pages'])} pages)")
            except Exception as e:
                logger.error(f"Error creating PDFs from {pdf_path}: {e}")
                traceback.print_exc()

        logger.info(f"Created {len(created_files)} per-student PDFs")
        core.log(f"Monitoring Processing: Created {len(created_files)} per-student PDFs")
        return created_files


def get_previously_uploaded_keys() -> set:
    """Get set of (student_id, window) tuples from the local upload log CSV."""
    try:
        if not UPLOAD_LOG_PATH.exists():
            print("No upload log found - starting fresh")
            return set()
        with open(UPLOAD_LOG_PATH, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            keys = {(row['Student ID'], row.get('Window', '')) for row in reader}
        print(f"Found {len(keys)} previously uploaded student(s) in upload log")
        return keys
    except Exception as e:
        print(f"Error reading upload log: {e}")
        return set()


def upload_created_files(created_files: List[str], test_run: bool = False):
    """Upload created files to document management system."""
    print("\n" + "=" * 70)
    print("UPLOADING RFEP MONITORING WINDOW DOCUMENTS")
    print("=" * 70)

    core.log("=" * 50)
    core.log("Uploading RFEP Monitoring Window Documents")
    core.log("=" * 50)

    errors = []
    

    # Authenticate
    try:
        core.log(f"Authenticating with FastAPI at {config('FAST_API_URL')}")
        data = {"username": config('FAST_API_USERNAME'), "password": config('FAST_API_PASSWORD')}
        token_response = requests.post(
            f"{config('FAST_API_URL')}/token",
            data=data,
            timeout=30,
        )
        if token_response.status_code != 200:
            error_msg = f"Failed to authenticate: Status {token_response.status_code} - {token_response.text}"
            core.log(f"ERROR: {error_msg}")
            logger.error(error_msg)
            errors.append(error_msg)
            return [], [], errors

        token = token_response.json().get('token')
        if not token:
            error_msg = "Failed to get authentication token from response"
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
        error_msg = f"Unexpected error during authentication: {e}"
        core.log(f"ERROR: {error_msg}")
        logger.error(error_msg)
        errors.append(error_msg)
        return [], [], errors

    # Get previously completed students
    previous_student_keys = get_previously_uploaded_keys()
    core.log(f"Found {len(previous_student_keys)} previously completed students")

    success_files = []
    newly_uploaded = []
    skipped_count = 0

    core.log(f"Processing {len(created_files)} file(s) for upload")

    for file_path in created_files:
        # Extract student ID and name from filename
        basename = os.path.basename(file_path).replace('.pdf', '')
        parts = basename.split('_')
        student_id = parts[0]

        # Extract student name and window number from filename
        try:
            rfep_idx = parts.index('RFEP')
            student_name = ' '.join(parts[1:rfep_idx])
        except ValueError:
            student_name = ' '.join(parts[1:-1]) if len(parts) > 2 else 'Unknown'

        win_match = re.search(r'_RFEP_Monitoring_Window_(\d+)_Document', basename)
        student_window = win_match.group(1) if win_match else str(window)

        # Check if already completed
        if (student_id, student_window) in previous_student_keys:
            print(f"  Skipping student ID {student_id} ({student_name}) - already completed")
            core.log(f"Skipping student {student_id} ({student_name}) - already completed")
            skipped_count += 1
            continue

        print(f"  Uploading for student ID: {student_id} ({student_name})")
        core.log(f"Uploading monitoring PDF for student {student_id} ({student_name})")

        try:
            with open(file_path, 'rb') as pdf_file:
                response = requests.post(
                    f"{config('FAST_API_URL')}/docs/uploadGeneral",
                    headers={"Authorization": f"Bearer {token}"},
                    files={"file": (os.path.basename(file_path), pdf_file, 'application/pdf')},
                    data={
                        "student_id": student_id,
                        "document_name": os.path.basename(file_path).replace('_', ' '),
                        "document_type": "RFEP_MONITORING",
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
            else:
                print(f"    Successfully uploaded")
                core.log(f"Successfully uploaded monitoring PDF for student {student_id}")
                success_files.append(file_path)
                newly_uploaded.append({
                    'student_id': student_id,
                    'student_name': student_name,
                    'window_num': student_window,
                    'completed_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'output_file': os.path.basename(file_path),
                })

        except requests.exceptions.Timeout:
            error_msg = f"Timeout uploading PDF for student {student_id}"
            print(f"    Error uploading: Timeout")
            core.log(f"ERROR: {error_msg}")
            logger.error(error_msg)
            errors.append(error_msg)
            continue
        except Exception as e:
            error_msg = f"Error uploading PDF for student {student_id}: {e}"
            print(f"    Error uploading: {e}")
            core.log(f"ERROR: {error_msg}")
            logger.error(error_msg)
            errors.append(error_msg)
            continue

    # Summary
    print(f"\nUpload Summary:")
    print(f"  Successfully uploaded: {len(success_files)} file(s)")
    print(f"  Skipped (already completed): {skipped_count}")
    if errors:
        print(f"  Failed: {len(errors)} file(s)")
    print("=" * 70)

    core.log("Upload Summary:")
    core.log(f"  - Successfully uploaded: {len(success_files)} file(s)")
    core.log(f"  - Skipped (already completed): {skipped_count}")
    core.log(f"  - Failed: {len(errors)} file(s)")
    if errors:
        core.log("Upload Errors:")
        for error in errors:
            core.log(f"  - {error}")

    return success_files, newly_uploaded, errors


def main():
    """Main function for RFEP Monitoring Window processing."""
    start_time = datetime.now()
    all_errors = []

    print("\n" + "=" * 70)
    print("RFEP MONITORING WINDOW DOCUMENTS PROCESSING")
    print("=" * 70)
    print(f"Started: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    logger.info("=" * 70)
    logger.info("RFEP MONITORING PROCESSING STARTED")
    logger.info(f"Start time: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 70)

    core.log("=" * 60)
    core.log("RFEP MONITORING WINDOW DOCUMENTS PROCESSING STARTED")
    core.log(f"Start time: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    core.log("=" * 60)

    # Step 1: Process monitoring PDFs
    print("\nSTEP 1: Process RFEP Monitoring Window PDFs")
    print("=" * 70)
    logger.info("STEP 1: Processing monitoring PDFs")
    core.log("STEP 1: Processing monitoring PDFs")

    newly_uploaded = []
    success_files = []
    upload_errors = []
    created_files = []

    try:
        processor = MonitoringProcessor()
        students = processor.process_pdfs()

        if not students:
            print("\nNo student forms found to process")
            logger.warning("No student forms found")
            core.log("WARNING: No student forms found to process")
        else:
            print(f"\nFound {len(students)} student form(s)")
            created_files = processor.create_per_student_pdfs(students)
            print(f"Created {len(created_files)} per-student PDF(s)")
            logger.info(f"Created {len(created_files)} per-student PDFs")
            core.log(f"Created {len(created_files)} per-student PDFs")
    except Exception as e:
        error_msg = f"Error in Step 1 (PDF processing): {e}"
        print(f"\n{error_msg}")
        logger.error(error_msg)
        core.log(f"ERROR: {error_msg}")
        all_errors.append(error_msg)
        traceback.print_exc()

    # Step 2: Upload files to document management system
    if created_files:
        print("\nSTEP 2: Upload monitoring documents to document system")
        print("=" * 70)
        logger.info("STEP 2: Uploading to document management system")
        core.log("STEP 2: Uploading to document management system")

        success_files, newly_uploaded, upload_errors = upload_created_files(
            created_files,
            test_run=config('TEST_RUN', default='False', cast=bool),
        )

        if upload_errors:
            all_errors.extend(upload_errors)

        if newly_uploaded:
            logger.info(f"Successfully uploaded {len(newly_uploaded)} NEW student(s):")
            for student in newly_uploaded:
                logger.info(f"  - Student ID {student['student_id']}: {student['student_name']}")
        else:
            logger.info("No new students to upload - all were previously completed")

        # Step 3: Update upload log CSV
        if newly_uploaded:
            print("\nSTEP 3: Update upload log")
            print("=" * 70)
            logger.info("STEP 3: Updating upload log")

            existing_keys = set()
            if UPLOAD_LOG_PATH.exists():
                with open(UPLOAD_LOG_PATH, 'r', newline='', encoding='utf-8') as csvfile:
                    reader = csv.DictReader(csvfile)
                    for row in reader:
                        existing_keys.add((row['Student ID'], row.get('Window', '')))

            UPLOAD_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            write_header = not UPLOAD_LOG_PATH.exists() or os.path.getsize(UPLOAD_LOG_PATH) == 0
            newly_added_count = 0

            with open(UPLOAD_LOG_PATH, 'a', newline='', encoding='utf-8') as csvfile:
                fieldnames = ['Student ID', 'Student Name', 'Window', 'Completed Date', 'Output File']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                if write_header:
                    writer.writeheader()
                for student in newly_uploaded:
                    student_id_str = str(student['student_id'])
                    student_window = student.get('window_num', str(window))
                    key = (student_id_str, student_window)
                    if key not in existing_keys:
                        writer.writerow({
                            'Student ID': student_id_str,
                            'Student Name': student['student_name'],
                            'Window': student_window,
                            'Completed Date': student['completed_date'],
                            'Output File': student['output_file'],
                        })
                        newly_added_count += 1

            print(f"Updated upload log with {newly_added_count} new student(s)")
            logger.info(f"Updated upload log with {newly_added_count} new student(s)")
    else:
        print("\nSTEP 2-3: Skipped (no files to upload)")
        logger.info("STEP 2-3: Skipped - no files to upload")
        core.log("STEP 2-3: Skipped - no files to upload")

    # Final summary
    end_time = datetime.now()
    elapsed = end_time - start_time

    print("\n" + "=" * 70)
    print("PROCESSING COMPLETE")
    print("=" * 70)
    print(f"Finished: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Elapsed: {elapsed}")
    print(f"Student forms found: {len(created_files)}")
    print(f"Newly uploaded: {len(newly_uploaded)}")
    print(f"Skipped (already completed): {len(created_files) - len(newly_uploaded) - len(upload_errors)}")
    if all_errors:
        print(f"Errors encountered: {len(all_errors)}")
    print("=" * 70)

    logger.info("=" * 70)
    logger.info("RFEP MONITORING PROCESSING COMPLETE")
    logger.info(f"End time: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Total elapsed time: {elapsed}")
    logger.info(f"Student forms processed: {len(created_files)}")
    logger.info(f"Newly uploaded: {len(newly_uploaded)}")
    if all_errors:
        logger.info(f"Total errors: {len(all_errors)}")
        for error in all_errors:
            logger.error(f"  - {error}")
    logger.info("=" * 70)

    core.log("=" * 60)
    core.log("RFEP MONITORING WINDOW DOCUMENTS PROCESSING COMPLETE")
    core.log(f"End time: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    core.log(f"Total elapsed time: {elapsed}")
    core.log(f"Student forms processed: {len(created_files)}")
    core.log(f"Newly uploaded: {len(newly_uploaded)}")
    if all_errors:
        core.log(f"ERRORS ENCOUNTERED: {len(all_errors)}")
        for error in all_errors:
            core.log(f"  - {error}")
    core.log("=" * 60)


if __name__ == "__main__":
    main()
