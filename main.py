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

def get_previously_uploaded_files():
    try:
        previous_ids = read_csv('out/completed_students.csv')['Student ID'].astype(str).tolist()
        return previous_ids
    except FileNotFoundError:
        return []

def upload_created_files(created_files, test_run=True):
    """
    Upload created files and update completed_students.csv with successful uploads
    
    Args:
        created_files: List of file paths to upload
        test_run: Boolean flag for test mode
        
    Returns:
        List of successfully uploaded files
    """
    data = {"username": config('FAST_API_USERNAME'), "password": config('FAST_API_PASSWORD')}
    token = requests.post(
        f"{config('FAST_API_URL')}/token",
        data=data,
       
    ).json().get('token')
    previous_student_ids = get_previously_uploaded_files()
    success_files = []
    newly_uploaded = []
    
    for file_path in created_files:
        student_id = file_path.split('\\')[1].split('_')[0].strip()
        
        # Extract student name from filename
        # Format: {StudentID}_{FirstName}_{LastName}_Reclassification_Paperwork.pdf
        filename_parts = os.path.basename(file_path).replace('.pdf', '').split('_')
        if len(filename_parts) > 3:
            # Find index of "Reclassification" to know where name ends
            try:
                reclass_idx = filename_parts.index('Reclassification')
                student_name = ' '.join(filename_parts[1:reclass_idx])
            except ValueError:
                # Fallback: assume last two parts are "Reclassification" and "Paperwork"
                student_name = ' '.join(filename_parts[1:-2])
        else:
            student_name = 'Unknown'
        
        if student_id in previous_student_ids:
            print(f"Skipping upload for student ID {student_id} as it was previously uploaded.")
            continue
            
        print(f"Uploading file for student ID: {student_id}")
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
            print(f"Failed to upload {file_path}: {response.text}")
            continue
        else:
            print(f"Successfully uploaded {file_path}: {response.text}")
            success_files.append(file_path)
            newly_uploaded.append({
                'student_id': student_id,
                'student_name': student_name,
                'completed_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'output_file': os.path.basename(file_path)
            })
    
    # Update the completed_students.csv file with newly uploaded students
    if newly_uploaded:
        csv_path = Path('out/completed_students.csv')
        
        # Read existing records if file exists
        existing_students = {}
        if csv_path.exists():
            with open(csv_path, 'r', newline='', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)
                for row in reader:
                    existing_students[row['Student ID']] = row
            print(f"\nFound {len(existing_students)} existing completed student records")
        
        # Add newly uploaded students (or update if already exists)
        for student in newly_uploaded:
            existing_students[student['student_id']] = {
                'Student ID': student['student_id'],
                'Student Name': student['student_name'],
                'Completed Date': student['completed_date'],
                'Output File': student['output_file']
            }
        
        # Write all records back (sorted by student ID)
        with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['Student ID', 'Student Name', 'Completed Date', 'Output File']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            for student_id in sorted(existing_students.keys()):
                writer.writerow(existing_students[student_id])
        
        print(f"\n✅ Updated completed_students.csv with {len(newly_uploaded)} newly uploaded student(s)")
        print(f"📊 Total completed students: {len(existing_students)}")
    
    return success_files

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

def create_rfep_csv(created_files, csv_file_path:str='out/rfep_students.csv'):
    """Create CSV file with student IDs and RFEP dates"""
    csv_content = 'Student #,RFEP Date'
    for file in created_files:
        rfep_date = get_reclass_date(file)
        if rfep_date:
            csv_content += f'\n{file.split("\\")[1].split("_")[0]},{rfep_date}'
        else:
            csv_content += f'\n{file.split("\\")[1].split("_")[0]},N/A'
        print(f"Creating RFEP CSV entry for {file}")
    with open(csv_file_path, 'w') as f:
        f.write(csv_content)
    return csv_file_path
    
def archive_processed_files(created_files, archive_folder='archive', csv_file='out/rfep_students.csv'):
    """Archive processed files and CSV to date-stamped folder"""
    if not os.path.exists(archive_folder):
        os.makedirs(archive_folder)
    for file in created_files:
        shutil.move(file, os.path.join(archive_folder, os.path.basename(file)))
        print(f"Moved {file} to {archive_folder}")
    if os.path.exists(csv_file):
        shutil.move(csv_file, os.path.join(archive_folder, os.path.basename(csv_file)))

def main():
    """Main function for standalone execution"""
    processor = ReclassificationProcessor()
    results = processor.run()
    
    if results['status'] == 'SUCCESS':
        print(f"Successfully processed {results['complete_students']} student(s) with complete paperwork")
        print(f"Created {len(results['created_files'])} combined PDF(s)")
        created_files = results['created_files']
        
        # Upload files and track in completed_students.csv
        upload_created_files(created_files, test_run=config('TEST_RUN', default='False', cast=bool))
        
        if results['incomplete_students'] > 0:
            print(f"{results['incomplete_students']} student(s) had incomplete paperwork")
                
    elif results['status'] == 'INCOMPLETE_DOCUMENTS':
        print(f"Found {results['total_students']} student(s) but none had complete paperwork")
        print(f"{results['incomplete_students']} student(s) missing required documents")
            
    elif results['status'] == 'NO_DOCUMENTS':
        print("No documents found to process")
        print("Make sure PDF files are in the 'in' folder")
    else:
        print(f"Processing failed: {results.get('message', 'Unknown error')}")
    
    # Create RFEP CSV for database updates
    csv_file_path = create_rfep_csv(created_files)
    
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
    print(f"\nProcessed {len(updates)} RFEP updates in the database")
    print(updates)
    
    # Archive processed files
    archive_processed_files(
        created_files, 
        archive_folder=f'archive/{datetime.today().strftime("%Y-%m-%d")}'
    )

if __name__ == "__main__":
    main()