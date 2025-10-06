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

def get_previously_uploaded_files():
    previous_ids = read_csv('out/completed_students.csv')['Student ID'].astype(str).tolist()
    return previous_ids

def upload_created_files(created_files, test_run=True):    
    data = {"username": config('FAST_API_USERNAME'), "password": config('FAST_API_PASSWORD')}
    token = requests.post(
        f"{config('FAST_API_URL')}/token",
        data=data,
       
    ).json().get('token')
    previous_student_ids = get_previously_uploaded_files()
    success_files = []
    for file_path in created_files:
        student_id = file_path.split('\\')[1].split('_')[0].strip()
        
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
        
        # Simulate upload process
        # In a real scenario, you would integrate with an API or service here
        print(f"Uploaded {file_path} successfully.")
    return created_files

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
    csv = 'Student #,RFEP Date'
    for file in created_files:
        rfep_date = get_reclass_date(file)
        if rfep_date:
            csv += f'\n{file.split("\\")[1].split("_")[0]},{rfep_date}'
        else:
            csv += f'\n{file.split("\\")[1].split("_")[0]},N/A'
        print(f"Creating RFEP CSV for {file}")
    with open(csv_file_path, 'w') as f:
        f.write(csv)
    return csv_file_path
    
def archive_processed_files(created_files, archive_folder='archive', csv_file='out/rfep_students.csv'):
    if not os.path.exists(archive_folder):
        os.makedirs(archive_folder)
    for file in created_files:
        shutil.move(file, os.path.join(archive_folder, os.path.basename(file)))
        print(f"Moved {file} to {archive_folder}")
    shutil.move(csv_file, os.path.join(archive_folder, os.path.basename(csv_file)))    
def main():
    """Main function for standalone execution"""
    processor = ReclassificationProcessor()
    results = processor.run()
    
    if results['status'] == 'SUCCESS':
        print(f"Successfully processed {results['complete_students']} student(s) with complete paperwork")
        print(f"Created {len(results['created_files'])} combined PDF(s)")
        created_files = results['created_files']
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
    csv_file_path = create_rfep_csv(created_files)
    
    cnxn = aeries.get_aeries_cnxn(access_level='w', database=config('DATABASE') if not config('TEST_RUN', default='False', cast=bool) else f"{config('DATABASE')}_DAILY" if config('TEST_RUN', default='False', cast=bool) else config('DATABASE'))
    
    updates = process_rfep_list_with_completion_check(
        csv=csv_file_path, 
        cnxn=cnxn,
    )
    print(f"Processed {len(updates)} RFEP updates in the database")
    print(updates)
    archive_processed_files(created_files, archive_folder=f'archive/{datetime.today().strftime("%Y-%m-%d")}')
    # close_lip_records(created_files)     

if __name__ == "__main__":
    
    main()