#!/usr/bin/env python3
"""
Test script for the Reclassification PDF Processor
"""

import os
import sys
from pathlib import Path

# Add the current directory to the Python path so we can import our processor
sys.path.insert(0, str(Path(__file__).parent))

from reclassification_processor import ReclassificationProcessor

def test_processor():
    """Test the processor with sample data"""
    
    # Create test directories
    input_dir = Path("in")
    output_dir = Path("out") 
    
    input_dir.mkdir(exist_ok=True)
    output_dir.mkdir(exist_ok=True)
    
    print("🧪 Testing Reclassification PDF Processor")
    print("=" * 50)
    
    # Check if there are any PDF files to process
    pdf_files = list(input_dir.glob("*.pdf"))
    
    if not pdf_files:
        print("⚠️  No PDF files found in 'in' folder")
        print("   Please add some PDF files to test with")
        return
    
    print(f"📄 Found {len(pdf_files)} PDF file(s) to process:")
    for pdf_file in pdf_files:
        print(f"   - {pdf_file.name}")
    
    # Initialize and run processor
    processor = ReclassificationProcessor(input_dir="in", output_dir="out")
    
    try:
        # Process the documents
        results = processor.run()
        
        print("\n" + "=" * 50)
        print("🎯 Test Results:")
        print(f"Status: {results['status']}")
        print(f"Students processed: {results['total_students']}")
        print(f"Files created: {len(results['created_files'])}")
        
        if results['created_files']:
            print("\n📁 Created files:")
            for file_path in results['created_files']:
                file_size = os.path.getsize(file_path)
                print(f"   - {Path(file_path).name} ({file_size:,} bytes)")
        
        if results.get('student_documents'):
            print("\n👥 Student documents:")
            for student_id, doc_types in results['student_documents'].items():
                print(f"   - Student {student_id}: {', '.join(doc_types)}")
        
        print("\n✅ Test completed successfully!")
        
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()

def analyze_pdf_structure():
    """Analyze the structure of PDFs in the input folder for debugging"""
    import PyPDF2
    
    input_dir = Path("in")
    pdf_files = list(input_dir.glob("*.pdf"))
    
    if not pdf_files:
        print("No PDF files found to analyze")
        return
    
    print("🔍 Analyzing PDF Structure")
    print("=" * 50)
    
    for pdf_file in pdf_files:
        print(f"\n📄 File: {pdf_file.name}")
        
        try:
            with open(pdf_file, 'rb') as file:
                reader = PyPDF2.PdfReader(file)
                total_pages = len(reader.pages)
                
                print(f"   Total pages: {total_pages}")
                
                # Analyze first few pages
                for page_num in range(min(3, total_pages)):
                    page = reader.pages[page_num]
                    text = page.extract_text()[:500]  # First 500 characters
                    
                    print(f"\n   Page {page_num + 1} preview:")
                    print(f"   {'-' * 30}")
                    print(f"   {text[:200]}...")
                    
                    # Look for student ID patterns
                    import re
                    student_id_match = re.search(r'Student ID[#:\s]*(\d{5,6})', text, re.IGNORECASE)
                    if student_id_match:
                        print(f"   📋 Found Student ID: {student_id_match.group(1)}")
                    
                    # Look for document type patterns
                    if "Teacher Evaluation for Reclassification" in text:
                        print("   📝 Document Type: Teacher Recommendation Form")
                    elif "Reclassification Meeting" in text:
                        print("   📝 Document Type: Reclassification Meeting")
                    elif "Notification of English Language Program Exit" in text:
                        print("   📝 Document Type: Notification of Exit")
        
        except Exception as e:
            print(f"   ❌ Error analyzing {pdf_file.name}: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "analyze":
        analyze_pdf_structure()
    else:
        test_processor()