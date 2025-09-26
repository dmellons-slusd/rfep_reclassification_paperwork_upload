import os
from decouple import config
from reclassification_processor import ReclassificationProcessor
import requests
import json

def upload_created_files(created_files):    
    data = {"username": config('FAST_API_USERNAME'), "password": config('FAST_API_PASSWORD')}
    print('Data:', data)
    token = requests.post(
        f"{config('FAST_API_URL')}/token",
        data=data,
        headers={"Content-Type": "application/json"},
    ).json()
    print('Token:', token)
    for file_path in created_files:
        student_id = file_path.split('\\')[1].split('_')[0].strip()
        print(f"Uploading file for student ID: {student_id}")
        # Simulate upload process
        # In a real scenario, you would integrate with an API or service here
        print(f"Uploaded {file_path} successfully.")
    return created_files
def main():
    """Main function for standalone execution"""
    processor = ReclassificationProcessor()
    results = processor.run()
    
    if results['status'] == 'SUCCESS':
        print(f"Successfully processed {results['complete_students']} student(s) with complete paperwork")
        print(f"Created {len(results['created_files'])} combined PDF(s)")
        created_files = results['created_files']
        uploaded_files = upload_created_files(created_files)
        
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

if __name__ == "__main__":
    
    main()