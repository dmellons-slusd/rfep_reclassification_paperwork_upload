import os
from decouple import config
from reclassification_processor import ReclassificationProcessor

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