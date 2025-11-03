from datetime import datetime
import os
from pathlib import Path
import re
import shutil
from typing import Optional
import PyPDF2
from decouple import config
from process_rfep import process_rfep_list_with_completion_check
from reclassification_processor import ReclassificationProcessor
import requests
from slusdlib import aeries
import q_update_rfep as q
from pandas import read_csv
import csv
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('log.log'),
        logging.StreamHandler()  # Also print to console
    ]
)
logger = logging.getLogger(__name__)

# Import Google Drive functionality
import sys
sys.path.insert(0, str(Path(__file__).parent / 'test'))
from folder_check import (
    get_google_drive_service,
    extract_folder_id,
    count_pdfs_in_folder,
    download_and_archive_pdfs
)

# Import Google Sheets functionality
from google_sheets_integration import (
    sync_completed_students,
    get_sheets_service,
    extract_spreadsheet_id,
    get_completed_students_from_sheet
)

def get_previously_uploaded_files():
    """
    Get list of previously completed students from Google Sheet.
    Falls back to local CSV if Google Sheet is unavailable.
    
    Returns:
        List of student IDs as strings
    """
    try:
        # Try to get from Google Sheet first
        sheet_url = config('GOOGLE_DRIVE_COMPLETED_STUDENTS_SHEET_URL', default=None)
        creds_file = config('GOOGLE_CREDS_FILE')
        
        if sheet_url:
            print("📊 Checking completed students from Google Sheet...")
            spreadsheet_id = extract_spreadsheet_id(sheet_url)
            service = get_sheets_service(creds_file)
            previous_ids = get_completed_students_from_sheet(service, spreadsheet_id)
            print(f"✅ Found {len(previous_ids)} previously completed student(s) in Google Sheet")
            return previous_ids
        else:
            # Fall back to local CSV
            print("📄 Google Sheet URL not configured, checking local CSV...")
            previous_ids = read_csv('out/completed_students.csv')['Student ID'].astype(str).tolist()
            print(f"✅ Found {len(previous_ids)} previously completed student(s) in local CSV")
            return previous_ids
            
    except FileNotFoundError:
        print("⚠️  No completed students file found - starting fresh")
        return []
    except Exception as e:
        print(f"⚠️  Error reading completed students: {e}")
        print("⚠️  Continuing with empty list to avoid re-uploads")
        return []

def upload_created_files(created_files, test_run=True):
    """
    Upload created files to document management system.
    Only uploads files for students NOT already in the completed list.
    
    Args:
        created_files: List of file paths to upload
        test_run: Boolean flag for test mode
        
    Returns:
        Tuple: (list of successfully uploaded files, list of newly completed student dicts)
    """
    print("\n" + "=" * 70)
    print("UPLOADING TO DOCUMENT MANAGEMENT SYSTEM")
    print("=" * 70)
    
    data = {"username": config('FAST_API_USERNAME'), "password": config('FAST_API_PASSWORD')}
    token = requests.post(
        f"{config('FAST_API_URL')}/token",
        data=data,
    ).json().get('token')
    
    # Get previously completed students (from Google Sheet or local CSV)
    previous_student_ids = get_previously_uploaded_files()
    
    success_files = []
    newly_uploaded = []
    
    for file_path in created_files:
        # Extract student ID and name from filename
        student_id = file_path.split(os.sep)[1].split('_')[0].strip()
        
        # Extract student name from filename
        # Format: {StudentID}_{FirstName}_{LastName}_Reclassification_Paperwork.pdf
        filename_parts = os.path.basename(file_path).replace('.pdf', '').split('_')
        if len(filename_parts) > 3:
            try:
                reclass_idx = filename_parts.index('Reclassification')
                student_name = ' '.join(filename_parts[1:reclass_idx])
            except ValueError:
                student_name = ' '.join(filename_parts[1:-2])
        else:
            student_name = 'Unknown'
        
        # Check if already completed
        if student_id in previous_student_ids:
            print(f"⏭️  Skipping student ID {student_id} ({student_name}) - already completed")
            continue
        
        # Upload to document system
        print(f"📤 Uploading for student ID: {student_id} ({student_name})")
        
        try:
            response = requests.post(
                f"{config('FAST_API_URL')}/docs/uploadGeneral",
                headers={"Authorization": f"Bearer {token}"},
                files={"file": open(file_path, 'rb')},
                data={
                    "student_id": student_id,
                    "document_name": os.path.basename(file_path).replace('_', ' '),
                    "document_type": "RECLASS",
                    "test_run": test_run
                }
            )
            
            if response.status_code != 200:
                print(f"  ❌ Failed to upload: {response.text}")
                continue
            else:
                print(f"  ✅ Successfully uploaded")
                success_files.append(file_path)
                newly_uploaded.append({
                    'student_id': student_id,
                    'student_name': student_name,
                    'completed_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'output_file': os.path.basename(file_path)
                })
                
        except Exception as e:
            print(f"  ❌ Error uploading: {e}")
            continue
    
    print(f"\n📊 Upload Summary:")
    print(f"  ✅ Successfully uploaded: {len(success_files)} file(s)")
    print(f"  ⏭️  Skipped (already completed): {len(created_files) - len(success_files) - (len(created_files) - len(success_files) - len(newly_uploaded))}")
    print("=" * 70)
    
    return success_files, newly_uploaded

def get_reclass_date(file_path: str) -> Optional[str]:
    """
    Extract the reclassification date from the upper left corner of a PDF.
    
    Args:
        file_path (str): Path to the PDF file
        
    Returns:
        str: Date in MM/DD/YYYY format if found, None otherwise
    """
    try:
        # Convert to Path object for better handling
        pdf_path = Path(file_path)
        
        if not pdf_path.exists():
            print(f"File not found: {file_path}")
            return None
        
        with open(pdf_path, 'rb') as file:
            reader = PyPDF2.PdfReader(file)
            
            if len(reader.pages) == 0:
                print(f"No pages found in PDF: {file_path}")
                return None
            
            # Extract text from the first page
            first_page = reader.pages[0]
            text = first_page.extract_text()
            
            # Normalize ligatures that might appear in PDFs
            ligature_replacements = {
                'ﬁ': 'fi',
                'ﬂ': 'fl',
                'ﬀ': 'ff',
                'ﬃ': 'ffi',
                'ﬄ': 'ffl',
            }
            for ligature, replacement in ligature_replacements.items():
                text = text.replace(ligature, replacement)
            
            # Look for date patterns in the first 500 characters (upper portion of page)
            # This helps ensure we're getting the date from the header area
            header_text = text[:500]
            
            # Multiple date patterns to catch various formats
            date_patterns = [
                r'(\d{1,2}/\d{1,2}/\d{4})',  # MM/DD/YYYY or M/D/YYYY
                r'(\d{1,2}-\d{1,2}-\d{4})',  # MM-DD-YYYY or M-D-YYYY
                r'(\d{1,2}\.\d{1,2}\.\d{4})', # MM.DD.YYYY or M.D.YYYY
            ]
            
            for pattern in date_patterns:
                matches = re.findall(pattern, header_text)
                if matches:
                    # Return the first date found
                    found_date = matches[0]
                    print(f"Found date: {found_date}")
                    return found_date
            
            # If no date found in header, search the entire first page
            print("No date found in header, searching entire first page...")
            for pattern in date_patterns:
                matches = re.findall(pattern, text)
                if matches:
                    # Return the first date found
                    found_date = matches[0]
                    print(f"Found date in full text: {found_date}")
                    return found_date
            
            print(f"No date found in PDF: {file_path}")
            return None
            
    except Exception as e:
        print(f"Error processing {file_path}: {e}")
        return None

def create_rfep_csv(created_files, csv_file_path:str='out/rfep_dates.csv'):
    """Create CSV file with student IDs and RFEP dates"""
    csv_content = 'Student #,RFEP Date'
    for file in created_files:
        rfep_date = get_reclass_date(file)
        if rfep_date:
            csv_content += f'\n{file.split(os.sep)[1].split("_")[0]},{rfep_date}'
        else:
            csv_content += f'\n{file.split(os.sep)[1].split("_")[0]},N/A'
        print(f"Creating RFEP CSV entry for {file}")
    with open(csv_file_path, 'w') as f:
        f.write(csv_content)
    return csv_file_path
    
def archive_processed_files(created_files, archive_folder='archive', csv_file='out/rfep_dates.csv'):
    """Archive processed files and CSV to date-stamped folder"""
    if not os.path.exists(archive_folder):
        os.makedirs(archive_folder)
    for file in created_files:
        shutil.move(file, os.path.join(archive_folder, os.path.basename(file)))
        print(f"Moved {file} to {archive_folder}")
    if os.path.exists(csv_file):
        shutil.move(csv_file, os.path.join(archive_folder, os.path.basename(csv_file)))

def download_new_pdfs_from_drive():
    """
    Download new PDFs from Google Drive and archive them.
    
    Returns:
        tuple: (number of PDFs downloaded, list of downloaded file names)
    """
    try:
        logger.info("=" * 70)
        logger.info("STEP 1: Checking Google Drive for new files")
        logger.info("=" * 70)
        
        print("\n" + "=" * 70)
        print("GOOGLE DRIVE - CHECKING FOR NEW FILES")
        print("=" * 70)
        
        # Get configuration from .env
        folder_url = config('GOOGLE_DRIVE_FOLDER_URL')
        
        print(f"\n📂 Google Drive Folder: {folder_url}")
        
        # Extract folder ID
        folder_id = extract_folder_id(folder_url)
        print(f"📋 Folder ID: {folder_id}")
        logger.info(f"Checking Google Drive folder: {folder_id}")
        
        # Create Google Drive service
        print("\n🔑 Authenticating with Google Drive...")
        service = get_google_drive_service()
        print("✅ Authentication successful")
        
        # Count PDFs
        print(f"\n🔍 Searching for PDF files in folder...")
        result = count_pdfs_in_folder(service, folder_id)
        
        print(f"📊 Found {result['count']} PDF file(s) ({result['total_size_mb']} MB)")
        logger.info(f"Found {result['count']} PDF file(s) in Google Drive ({result['total_size_mb']} MB)")
        
        downloaded_files = []
        
        if result['count'] > 0:
            # Show files
            print(f"\n📄 Files to download:")
            for file_info in result['files']:
                name = file_info.get('name', 'Unknown')
                size_mb = round(int(file_info.get('size', 0)) / (1024 * 1024), 2)
                print(f"  • {name} ({size_mb} MB)")
                downloaded_files.append(name)
                logger.info(f"Downloading: {name} ({size_mb} MB)")
            
            # Download and archive automatically (no user prompt in automated mode)
            print(f"\n🚀 Downloading PDFs and archiving in Google Drive...")
            archive_result = download_and_archive_pdfs(service, folder_id, result['files'])
            
            # Display summary
            print("\n" + "=" * 70)
            print("GOOGLE DRIVE DOWNLOAD SUMMARY")
            print("=" * 70)
            print(f"✅ Downloaded: {archive_result['downloaded']} file(s)")
            print(f"✅ Moved to archive: {archive_result['moved']} file(s)")
            
            logger.info(f"Successfully downloaded {archive_result['downloaded']} file(s) from Google Drive")
            logger.info(f"Moved {archive_result['moved']} file(s) to date-stamped archive folders")
            
            if archive_result['failed'] > 0:
                print(f"❌ Failed: {archive_result['failed']} file(s)")
                print("\nErrors:")
                for error in archive_result['errors']:
                    print(f"  • {error}")
                    logger.error(f"Download error: {error}")
            
            print(f"\n📁 PDFs downloaded to: ./in")
            print(f"📦 PDFs archived in Google Drive by date")
            print("=" * 70)
            
            return archive_result['downloaded'], downloaded_files
        else:
            print("\n⚠️  No new PDF files found in Google Drive")
            print("=" * 70)
            logger.info("No new PDF files found in Google Drive")
            return 0, []
            
    except Exception as e:
        print(f"\n❌ Error downloading from Google Drive: {e}")
        logger.error(f"Error downloading from Google Drive: {e}")
        import traceback
        traceback.print_exc()
        print("⚠️  Continuing with local processing...")
        return 0, []

def upload_csv_reports_to_drive(service, folder_id: str):
    """
    Upload completed_students.csv and missing_paperwork.csv to Google Drive.
    
    Args:
        service: Google Drive service object
        folder_id: The ID of the folder to upload to
    """
    try:
        from googleapiclient.http import MediaFileUpload
        
        print("\n" + "=" * 70)
        print("UPLOADING REPORTS TO GOOGLE DRIVE")
        print("=" * 70)
        
        csv_files = {
            'out/completed_students.csv': 'Completed Students Report',
            'out/missing_paperwork.csv': 'Missing Paperwork Report'
        }
        
        uploaded_count = 0
        
        for file_path, description in csv_files.items():
            if not os.path.exists(file_path):
                print(f"⏭️  Skipping {description} (file not found)")
                continue
            
            try:
                file_name = os.path.basename(file_path)
                
                # Check if file already exists in the folder
                query = f"name='{file_name}' and '{folder_id}' in parents and trashed=false"
                results = service.files().list(
                    q=query,
                    spaces='drive',
                    fields='files(id, name)'
                ).execute()
                
                existing_files = results.get('files', [])
                
                media = MediaFileUpload(file_path, mimetype='text/csv', resumable=True)
                
                if existing_files:
                    # Update existing file
                    file_id = existing_files[0]['id']
                    service.files().update(
                        fileId=file_id,
                        media_body=media
                    ).execute()
                    print(f"✅ Updated: {file_name}")
                else:
                    # Create new file
                    file_metadata = {
                        'name': file_name,
                        'parents': [folder_id]
                    }
                    service.files().create(
                        body=file_metadata,
                        media_body=media,
                        fields='id'
                    ).execute()
                    print(f"✅ Uploaded: {file_name}")
                
                uploaded_count += 1
                
            except Exception as e:
                print(f"❌ Failed to upload {description}: {e}")
        
        print(f"\n📊 Successfully uploaded {uploaded_count} report(s) to Google Drive")
        print("=" * 70)
        
    except Exception as e:
        print(f"\n❌ Error uploading reports to Google Drive: {e}")
        import traceback
        traceback.print_exc()

def main():
    """Main function for standalone execution"""
    
    start_time = datetime.now()
    
    print("\n" + "=" * 70)
    print("RFEP RECLASSIFICATION PAPERWORK PROCESSING")
    print("=" * 70)
    print(f"Started: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    
    logger.info("=" * 70)
    logger.info("RFEP PROCESSING STARTED")
    logger.info(f"Start time: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 70)
    
    # Step 1: Download new PDFs from Google Drive
    print("\n📥 STEP 1: Download new files from Google Drive")
    downloaded_count, downloaded_files = download_new_pdfs_from_drive()
    
    # Step 2: Process PDFs locally
    print("\n🔄 STEP 2: Process reclassification paperwork")
    print("=" * 70)
    logger.info("STEP 2: Processing reclassification paperwork")
    
    processor = ReclassificationProcessor()
    results = processor.run()
    
    # Initialize variables to track uploads
    newly_uploaded = []
    success_files = []
    
    if results['status'] == 'SUCCESS':
        print(f"\n✅ Successfully processed {results['complete_students']} student(s) with complete paperwork")
        print(f"📄 Created {len(results['created_files'])} combined PDF(s)")
        logger.info(f"Successfully processed {results['complete_students']} student(s) with complete paperwork")
        
        created_files = results['created_files']
        
        # Step 3: Upload files to document management system
        print("\n📤 STEP 3: Upload completed paperwork to document system")
        logger.info("STEP 3: Uploading to document management system")
        success_files, newly_uploaded = upload_created_files(created_files, test_run=config('TEST_RUN', default='False', cast=bool))
        
        # Log each newly uploaded student
        if newly_uploaded:
            logger.info(f"Successfully uploaded {len(newly_uploaded)} NEW student(s):")
            for student in newly_uploaded:
                logger.info(f"  - Student ID {student['student_id']}: {student['student_name']} (File: {student['output_file']})")
        else:
            logger.info("No new students to upload - all were previously completed")
        
        # Log skipped students
        skipped_count = len(created_files) - len(newly_uploaded)
        if skipped_count > 0:
            logger.info(f"Skipped {skipped_count} student(s) - already completed previously")
        
        # Step 3a: Update local CSV with newly uploaded students
        if newly_uploaded:
            print("\n💾 Updating local completed_students.csv...")
            csv_path = Path('out/completed_students.csv')
            
            # Read existing records if file exists
            existing_students = {}
            if csv_path.exists():
                with open(csv_path, 'r', newline='', encoding='utf-8') as csvfile:
                    reader = csv.DictReader(csvfile)
                    for row in reader:
                        existing_students[row['Student ID']] = row
            
            # Add ONLY newly uploaded students (don't overwrite existing ones)
            newly_added_count = 0
            for student in newly_uploaded:
                student_id_str = str(student['student_id'])
                # Only add if not already in the CSV
                if student_id_str not in existing_students:
                    existing_students[student_id_str] = {
                        'Student ID': student_id_str,
                        'Student Name': student['student_name'],
                        'Completed Date': student['completed_date'],
                        'Output File': student['output_file']
                    }
                    newly_added_count += 1
                else:
                    # Student already exists in CSV, preserve their original completion date
                    logger.info(f"Student {student_id_str} already in local CSV - preserving original completion date: {existing_students[student_id_str]['Completed Date']}")
            
            # Write all records back (sorted by student ID)
            with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = ['Student ID', 'Student Name', 'Completed Date', 'Output File']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                for student_id in sorted(existing_students.keys()):
                    writer.writerow(existing_students[student_id])
            
            print(f"✅ Updated local CSV with {newly_added_count} new student(s)")
            logger.info(f"Updated local completed_students.csv with {newly_added_count} new student(s)")
        
        # Step 3b: Sync with Google Sheet
        if newly_uploaded:
            try:
                sheet_url = config('GOOGLE_DRIVE_COMPLETED_STUDENTS_SHEET_URL', default=None)
                creds_file = config('GOOGLE_CREDS_FILE')
                
                if sheet_url:
                    logger.info("Syncing with Google Sheet...")
                    sync_result = sync_completed_students(
                        creds_file=creds_file,
                        spreadsheet_url=sheet_url,
                        new_students=newly_uploaded,
                        sheet_name='Sheet1'
                    )
                    logger.info(f"Google Sheet sync complete: Added {sync_result['added_count']} student(s)")
                else:
                    print("\n⚠️  Google Sheet URL not configured - skipping Google Sheet sync")
                    print("💡 Add GOOGLE_DRIVE_COMPLETED_STUDENTS_SHEET_URL to .env to enable")
                    logger.warning("Google Sheet URL not configured - skipping sync")
            except Exception as e:
                print(f"\n⚠️  Could not sync with Google Sheet: {e}")
                print("💡 Local CSV has been updated successfully")
                logger.error(f"Google Sheet sync failed: {e}")
        
        if results['incomplete_students'] > 0:
            print(f"\n⚠️  {results['incomplete_students']} student(s) had incomplete paperwork")
            logger.warning(f"{results['incomplete_students']} student(s) had incomplete paperwork")
            if results['csv_files']['missing']:
                print(f"📋 Missing paperwork report: {results['csv_files']['missing']}")
                logger.info(f"Missing paperwork report saved: {results['csv_files']['missing']}")
                
    elif results['status'] == 'INCOMPLETE_DOCUMENTS':
        print(f"\n⚠️  Found {results['total_students']} student(s) but none had complete paperwork")
        print(f"❌ {results['incomplete_students']} student(s) missing required documents")
        logger.warning(f"Found {results['total_students']} student(s) but none had complete paperwork")
        if results['csv_files']['missing']:
            print(f"📋 Missing paperwork report: {results['csv_files']['missing']}")
            logger.info(f"Missing paperwork report saved: {results['csv_files']['missing']}")
        created_files = []
            
    elif results['status'] == 'NO_DOCUMENTS':
        print("\n⚠️  No documents found to process")
        print("💡 Make sure PDF files were downloaded to the 'in' folder")
        logger.warning("No documents found to process in 'in' folder")
        created_files = []
    else:
        print(f"\n❌ Processing failed: {results.get('message', 'Unknown error')}")
        logger.error(f"Processing failed: {results.get('message', 'Unknown error')}")
        created_files = []
    
    # Step 4: Upload CSV reports back to Google Drive
    if results['csv_files']['completed'] or results['csv_files']['missing']:
        print("\n📊 STEP 4: Upload reports to Google Drive")
        logger.info("STEP 4: Uploading CSV reports to Google Drive")
        try:
            folder_url = config('GOOGLE_DRIVE_FOLDER_URL')
            folder_id = extract_folder_id(folder_url)
            service = get_google_drive_service()
            upload_csv_reports_to_drive(service, folder_id)
            logger.info("Successfully uploaded CSV reports to Google Drive")
        except Exception as e:
            print(f"⚠️  Could not upload reports to Google Drive: {e}")
            logger.error(f"Failed to upload CSV reports to Google Drive: {e}")
    
    # Step 5: Create RFEP CSV and update database (ONLY for newly uploaded students)
    if newly_uploaded:
        print("\n💾 STEP 5: Update database records")
        print("=" * 70)
        print(f"Processing {len(newly_uploaded)} newly uploaded student(s) for database update...")
        logger.info("STEP 5: Updating database records")
        logger.info(f"Processing {len(newly_uploaded)} student(s) for database update")
        
        # Create CSV with ONLY newly uploaded students
        csv_file_path = create_rfep_csv(success_files)
        
        # Update database records
        cnxn = aeries.get_aeries_cnxn(
            access_level='w', 
            database=config('DATABASE') if not config('TEST_RUN', default='False', cast=bool) 
            else f"{config('DATABASE')}_DAILY"
        )
        
        updates = process_rfep_list_with_completion_check(
            csv=csv_file_path, 
            cnxn=cnxn,
        )
        print(f"\n✅ Processed {len(updates)} RFEP update(s) in the database")
        logger.info(f"Successfully updated database for {len(updates)} student(s)")
        
        # Log each database update
        for update in updates:
            if update.get('status') == 'complete':
                logger.info(f"  - Database updated for Student ID {update.get('student_id')}")
            elif update.get('status') == 'error':
                logger.error(f"  - Database update failed for Student ID {update.get('student_id')}: {update.get('error_message')}")
        
        # Step 6: Archive processed files (ONLY newly uploaded files)
        print("\n📦 STEP 6: Archive processed files")
        print("=" * 70)
        logger.info("STEP 6: Archiving processed files")
        archive_processed_files(
            success_files, 
            archive_folder=f'archive/{datetime.today().strftime("%Y-%m-%d")}'
        )
        print("✅ Files archived successfully")
        logger.info(f"Archived {len(success_files)} file(s) to archive/{datetime.today().strftime('%Y-%m-%d')}")
    else:
        print("\n⏭️  STEP 5-6: Skipped (no new students to process)")
        print("💡 All students were previously completed")
        logger.info("STEP 5-6: Skipped - no new students to process")
    
    # Final summary
    end_time = datetime.now()
    elapsed = end_time - start_time
    
    print("\n" + "=" * 70)
    print("PROCESSING COMPLETE")
    print("=" * 70)
    print(f"Finished: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📥 Downloaded from Drive: {downloaded_count} file(s)")
    print(f"✅ Completed students: {results.get('complete_students', 0)}")
    print(f"🆕 Newly uploaded: {len(newly_uploaded)}")
    print(f"⏭️  Skipped (already completed): {results.get('complete_students', 0) - len(newly_uploaded)}")
    print(f"⚠️  Incomplete students: {results.get('incomplete_students', 0)}")
    print("=" * 70)
    
    logger.info("=" * 70)
    logger.info("RFEP PROCESSING COMPLETE")
    logger.info(f"End time: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Total elapsed time: {elapsed}")
    logger.info(f"Downloaded from Drive: {downloaded_count} file(s)")
    if downloaded_files:
        logger.info(f"Downloaded files: {', '.join(downloaded_files)}")
    logger.info(f"Completed students: {results.get('complete_students', 0)}")
    logger.info(f"Newly uploaded students: {len(newly_uploaded)}")
    logger.info(f"Skipped (already completed): {results.get('complete_students', 0) - len(newly_uploaded)}")
    logger.info(f"Incomplete students: {results.get('incomplete_students', 0)}")
    logger.info("=" * 70)

if __name__ == "__main__":
    main()