#!/usr/bin/env python3
"""
Reclassification Paperwork PDF Processor

This script processes reclassification paperwork PDFs by:
1. Reading PDFs from the 'in' folder
2. Extracting student information and document types
3. Grouping documents by Student ID
4. Creating combined PDFs for each student
5. Saving results to the 'out' folder

Based on the SLUSD-API IEP processing architecture.
"""

import os
import re
import PyPDF2
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@dataclass
class DocumentInfo:
    """Information about a processed document"""
    file_path: str
    student_id: str
    student_name: str
    document_type: str
    pages: List[int]  # Page numbers in the original PDF
    page_count: int

class ReclassificationProcessor:
    """Main processor for reclassification paperwork"""
    
    # Document type patterns and identifiers
    DOCUMENT_PATTERNS = {
        'teacher_recommendation': {
            'pattern': r'Teacher Evaluation for Reclassification|Criteria 2: Teacher Evaluation',
            'title': 'Teacher Recommendation Form'
        },
        'reclassification_meeting': {
            'pattern': r'Reclassification Meeting w/ Parent/Guardian|Alternate Reclassification IEP Meeting',
            'title': 'Reclassification Meeting'
        },
        'notification_exit': {
            'pattern': r'Notification of English Language Program Exit|退出英语教学计划的通知|Notificación de salida del programa de idioma inglés',
            'title': 'Notification of English Language Program Exit'
        }
    }
    
    def __init__(self, input_dir: str = "in", output_dir: str = "out"):
        self.input_dir = Path(input_dir)
        self.output_dir = Path(output_dir)
        
        # Create directories if they don't exist
        self.input_dir.mkdir(exist_ok=True)
        self.output_dir.mkdir(exist_ok=True)
        
        logger.info(f"Initialized processor with input: {self.input_dir}, output: {self.output_dir}")
    
    def process_pdfs(self) -> Dict[str, List[DocumentInfo]]:
        """
        Process all PDFs in the input directory
        Returns: Dictionary mapping student_id to list of their documents
        """
        logger.info("Starting PDF processing...")
        
        # Find all PDF files in input directory
        pdf_files = list(self.input_dir.glob("*.pdf"))
        if not pdf_files:
            logger.warning(f"No PDF files found in {self.input_dir}")
            return {}
        
        logger.info(f"Found {len(pdf_files)} PDF file(s) to process")
        
        all_documents = []
        
        # Process each PDF file
        for pdf_file in pdf_files:
            logger.info(f"Processing: {pdf_file.name}")
            documents = self._extract_documents_from_pdf(pdf_file)
            all_documents.extend(documents)
            logger.info(f"Extracted {len(documents)} document(s) from {pdf_file.name}")
        
        # Group documents by student ID
        student_documents = self._group_by_student(all_documents)
        
        logger.info(f"Found documents for {len(student_documents)} student(s)")
        
        return student_documents
    
    def _extract_documents_from_pdf(self, pdf_path: Path) -> List[DocumentInfo]:
        """Extract individual documents from a PDF file"""
        documents = []
        
        try:
            with open(pdf_path, 'rb') as file:
                reader = PyPDF2.PdfReader(file)
                total_pages = len(reader.pages)
                
                logger.info(f"Scanning {total_pages} pages in {pdf_path.name}")
                
                current_doc = None
                current_pages = []
                
                for page_num in range(total_pages):
                    try:
                        page = reader.pages[page_num]
                        text = page.extract_text()
                        
                        # Check if this page starts a new document
                        doc_info = self._identify_document_type(text)
                        
                        if doc_info:
                            # Save previous document if it exists
                            if current_doc and current_pages:
                                documents.append(DocumentInfo(
                                    file_path=str(pdf_path),
                                    student_id=current_doc['student_id'],
                                    student_name=current_doc['student_name'],
                                    document_type=current_doc['document_type'],
                                    pages=current_pages.copy(),
                                    page_count=len(current_pages)
                                ))
                            
                            # Start new document
                            current_doc = doc_info
                            current_pages = [page_num]
                            
                            logger.info(f"Found {doc_info['document_type']} for student {doc_info['student_id']} ({doc_info['student_name']}) on page {page_num + 1}")
                        
                        elif current_doc:
                            # Continue current document
                            current_pages.append(page_num)
                    
                    except Exception as e:
                        logger.warning(f"Error processing page {page_num + 1} in {pdf_path.name}: {e}")
                        continue
                
                # Don't forget the last document
                if current_doc and current_pages:
                    documents.append(DocumentInfo(
                        file_path=str(pdf_path),
                        student_id=current_doc['student_id'],
                        student_name=current_doc['student_name'],
                        document_type=current_doc['document_type'],
                        pages=current_pages.copy(),
                        page_count=len(current_pages)
                    ))
        
        except Exception as e:
            logger.error(f"Error processing {pdf_path}: {e}")
        finally:
            # Ensure we always return something, even if empty
            logger.debug(f"Completed processing {pdf_path.name}, found {len(documents)} documents")
        
        return documents
    
    def _identify_document_type(self, text: str) -> Optional[Dict[str, str]]:
        """
        Identify document type and extract student information from page text
        Returns: Dict with document_type, student_id, student_name or None
        """
        # Check for document type patterns
        document_type = None
        for doc_key, doc_info in self.DOCUMENT_PATTERNS.items():
            if re.search(doc_info['pattern'], text, re.IGNORECASE):
                document_type = doc_info['title']
                break
        
        if not document_type:
            return None
        
        # Debug: Show first part of text for notification documents
        if document_type == 'Notification of English Language Program Exit':
            logger.debug(f"Processing notification document. First 500 chars: {repr(text[:500])}")
        
        # Extract student ID - look for various patterns in multiple languages
        student_id_patterns = [
            # English patterns
            r'Student ID#:\s*(\d{6})',    # Notification format: "Student ID#: 106874"
            r'Student ID#:\s*(\d{5})',    # Notification format 5-digit
            r'Student ID[#:\s]*(\d{6})',  # Standard format
            r'Student ID[#:\s]*(\d{5})',  # 5-digit format
            r'ID[#:\s]*(\d{6})',         # Shortened format
            r'ID[#:\s]*(\d{5})',         # Shortened 5-digit format
            
            # Chinese patterns
            r'学号[#:\s]*(\d{6})',        # Chinese: "学号: 106874"
            r'学号[#:\s]*(\d{5})',        # Chinese 5-digit
            r'学生编号[#:\s]*(\d{6})',     # Chinese alternative
            r'学生编号[#:\s]*(\d{5})',     # Chinese alternative 5-digit
            
            # Spanish patterns  
            r'N°\s*de\s*identificación\s*del\s*estudiante[#:\s]*(\d{6})',  # Spanish long form
            r'N°\s*de\s*identiﬁcación\s*del\s*estudiante\s*:\s*(\d{6})',  # Spanish long form
            r'N°\s*de\s*identificación\s*del\s*estudiante[#:\s]*(\d{5})',  # Spanish long form 5-digit
            r'ID\s*del\s*estudiante[#:\s]*(\d{6})',  # Spanish short form
            r'ID\s*del\s*estudiante[#:\s]*(\d{5})',  # Spanish short form 5-digit
            
            # Generic number patterns (last resort)
            r'(?:ID|编号|学号).*?(\d{6})',   # Any ID-like word followed by 6 digits
            r'(?:ID|编号|学号).*?(\d{5})',   # Any ID-like word followed by 5 digits
        ]
        
        student_id = None
        for i, pattern in enumerate(student_id_patterns):
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                student_id = match.group(1)
                if document_type == 'Notification of English Language Program Exit':
                    logger.debug(f"Found Student ID using pattern {i+1}: '{pattern}' -> '{student_id}'")
                break
        
        if not student_id:
            # Debug: Show more text if student ID not found in notification documents
            if document_type == 'Notification of English Language Program Exit':
                logger.debug(f"Student ID not found. Full text preview: {repr(text[:1000])}")
            logger.warning(f"Could not extract student ID from document of type: {document_type}")
            return None
        
        # Extract student name - look for various patterns in multiple languages
        name_patterns = [
            # English patterns
            r'Student:\s*([A-Za-z\s]+?)(?:\s+Student ID|$|\n)',  # Notification format: "Student: Borui Hu"
            r'(?:Name|Student)[:\s]+([A-Za-z\s]+?)(?:\s+Student|\s+Grade|\n)',
            r'Name[:\s]+(.+?)(?:\s+Student ID|$)',
            r'Student[:\s]+([A-Za-z\s]+?)(?:\s+Grade|\s+Student ID|\n)',
            
            # Chinese patterns
            r'学生[:\s]*([A-Za-z\s\u4e00-\u9fff]+?)(?:\s+学号|\s+等级|\n)',  # "学生: Name"
            r'姓名[:\s]*([A-Za-z\s\u4e00-\u9fff]+?)(?:\s+学号|\s+等级|\n)',  # "姓名: Name"
            
            # Spanish patterns
            r'(?:Nombre|Estudiante)[:\s]+([A-Za-z\s]+?)(?:\s+Grado|\s+N°|\n)',  # "Nombre: Name"
            r'Estudiante[:\s]+([A-Za-z\s]+?)(?:\s+Grado|\s+ID|\n)',  # "Estudiante: Name"
            
            # Generic patterns for names that appear before ID numbers
            r'([A-Za-z\s\u4e00-\u9fff]{3,30})(?:\s+(?:Student\s*)?ID[#:\s]*\d{5,6})',  # Name followed by ID
        ]
        
        student_name = "Unknown"
        for pattern in name_patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
            if match:
                name = match.group(1).strip()
                # Clean up the name (remove extra whitespace, etc.)
                name = re.sub(r'\s+', ' ', name)
                if name and len(name) > 2:  # Basic validation
                    student_name = name
                    break
        
        return {
            'document_type': document_type,
            'student_id': student_id,
            'student_name': student_name
        }
    
    def _group_by_student(self, documents: List[DocumentInfo]) -> Dict[str, List[DocumentInfo]]:
        """Group documents by student ID"""
        student_docs = {}
        
        for doc in documents:
            if doc.student_id not in student_docs:
                student_docs[doc.student_id] = []
            student_docs[doc.student_id].append(doc)
        
        return student_docs
    
    def create_combined_pdfs(self, student_documents: Dict[str, List[DocumentInfo]]) -> Tuple[List[str], List[Dict]]:
        """
        Create combined PDFs for students with complete document sets
        Returns: Tuple of (created_file_paths, incomplete_students)
        """
        created_files = []
        incomplete_students = []
        
        # Required document types
        required_docs = {
            'Teacher Recommendation Form',
            'Reclassification Meeting', 
            'Notification of English Language Program Exit'
        }
        
        for student_id, docs in student_documents.items():
            if not docs:
                continue
            
            # Get student name from the first document
            student_name = docs[0].student_name
            
            # Check if student has all required documents
            student_doc_types = {doc.document_type for doc in docs}
            missing_docs = required_docs - student_doc_types
            
            if missing_docs:
                # Student is missing required documents
                incomplete_students.append({
                    'student_id': student_id,
                    'student_name': student_name,
                    'found_documents': list(student_doc_types),
                    'missing_documents': list(missing_docs),
                    'total_pages': sum(doc.page_count for doc in docs)
                })
                logger.warning(f"Student {student_id} ({student_name}) missing: {', '.join(missing_docs)}")
                continue
            
            logger.info(f"Creating combined PDF for student {student_id} ({student_name}) with complete document set")
            
            # Sort documents in the specified order
            ordered_docs = self._order_documents(docs)
            
            # Create combined PDF
            output_filename = f"Reclassification Paperwork - ID# {student_id}.pdf"
            output_path = self.output_dir / output_filename
            
            try:
                self._combine_documents(ordered_docs, output_path)
                created_files.append(str(output_path))
                logger.info(f"Created: {output_filename}")
            except Exception as e:
                logger.error(f"Error creating PDF for student {student_id}: {e}")
                # Move to incomplete list if processing fails
                incomplete_students.append({
                    'student_id': student_id,
                    'student_name': student_name,
                    'found_documents': list(student_doc_types),
                    'missing_documents': [],
                    'error': str(e),
                    'total_pages': sum(doc.page_count for doc in docs)
                })
            finally:
                # Ensure any cleanup is done even if creation fails
                pass
        
        return created_files, incomplete_students
    
    def _order_documents(self, docs: List[DocumentInfo]) -> List[DocumentInfo]:
        """
        Order documents according to the specified sequence:
        1. Teacher Recommendation Form
        2. Reclassification Meeting
        3. Notification of English Language Program Exit
        """
        order_priority = {
            'Teacher Recommendation Form': 1,
            'Reclassification Meeting': 2,
            'Notification of English Language Program Exit': 3
        }
        
        # Sort by priority, then by document type name for consistency
        return sorted(docs, key=lambda x: (order_priority.get(x.document_type, 999), x.document_type))
    
    def _create_error_report(self, incomplete_students: List[Dict]) -> Optional[str]:
        """
        Create an error report for students with incomplete document sets
        Returns: Path to error report file or None if no errors
        """
        if not incomplete_students:
            return None
        
        error_report_path = self.output_dir / "INCOMPLETE_PAPERWORK_REPORT.txt"
        
        try:
            with open(error_report_path, 'w') as f:
                f.write("RECLASSIFICATION PAPERWORK - INCOMPLETE SETS REPORT\n")
                f.write("=" * 60 + "\n")
                f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                
                f.write(f"SUMMARY: {len(incomplete_students)} student(s) with incomplete paperwork\n")
                f.write("-" * 60 + "\n\n")
                
                required_docs = [
                    "Teacher Recommendation Form",
                    "Reclassification Meeting", 
                    "Notification of English Language Program Exit"
                ]
                
                for i, student in enumerate(incomplete_students, 1):
                    f.write(f"{i}. STUDENT ID: {student['student_id']}\n")
                    f.write(f"   Name: {student['student_name']}\n")
                    
                    if student.get('error'):
                        f.write(f"   ❌ Processing Error: {student['error']}\n")
                    else:
                        f.write(f"   📄 Found Documents ({len(student['found_documents'])}):\n")
                        for doc in student['found_documents']:
                            f.write(f"      ✅ {doc}\n")
                        
                        f.write(f"   ❌ Missing Documents ({len(student['missing_documents'])}):\n")
                        for doc in student['missing_documents']:
                            f.write(f"      ❌ {doc}\n")
                    
                    f.write(f"   📊 Total Pages Found: {student.get('total_pages', 0)}\n")
                    f.write("\n" + "-" * 40 + "\n\n")
                
                # Summary by document type
                f.write("MISSING DOCUMENTS SUMMARY:\n")
                f.write("-" * 30 + "\n")
                
                missing_count = {}
                for student in incomplete_students:
                    for missing_doc in student.get('missing_documents', []):
                        missing_count[missing_doc] = missing_count.get(missing_doc, 0) + 1
                
                for doc_type in required_docs:
                    count = missing_count.get(doc_type, 0)
                    f.write(f"• {doc_type}: {count} student(s) missing\n")
                
                f.write(f"\nNOTE: Only students with ALL THREE required documents will have combined PDFs created.\n")
                f.write(f"Please ensure all required paperwork is included and reprocess.\n")
            
            logger.info(f"Created error report: {error_report_path.name}")
            return str(error_report_path)
        except Exception as e:
            logger.error(f"Error creating error report: {e}")
            return None
            
    def _combine_documents(self, docs: List[DocumentInfo], output_path: Path):
        """Combine multiple documents into a single PDF"""
        writer = PyPDF2.PdfWriter()
        
        try:
            # Process each document
            for doc in docs:
                logger.info(f"  Adding {doc.document_type} ({doc.page_count} pages)")
                
                try:
                    # Open the source PDF
                    with open(doc.file_path, 'rb') as file:
                        reader = PyPDF2.PdfReader(file)
                        
                        # Add the specified pages
                        for page_num in doc.pages:
                            try:
                                if page_num < len(reader.pages):
                                    writer.add_page(reader.pages[page_num])
                                else:
                                    logger.warning(f"Page {page_num} not found in {doc.file_path}")
                            except Exception as e:
                                logger.error(f"Error adding page {page_num} from {doc.file_path}: {e}")
                                continue
                                
                except Exception as e:
                    logger.error(f"Error reading document {doc.file_path}: {e}")
                    continue
            
            # Write the combined PDF
            try:
                with open(output_path, 'wb') as output_file:
                    writer.write(output_file)
                logger.debug(f"Successfully wrote combined PDF to {output_path}")
            except Exception as e:
                logger.error(f"Error writing combined PDF to {output_path}: {e}")
                raise
                
        except Exception as e:
            logger.error(f"Error combining documents: {e}")
            raise
        finally:
            # Clean up writer resources if needed
            if hasattr(writer, 'close'):
                try:
                    writer.close()
                except:
                    pass
    
    def run(self) -> Dict[str, any]:
        """
        Main execution method
        Returns: Summary of processing results
        """
        logger.info("=" * 80)
        logger.info("Starting Reclassification Paperwork Processing")
        logger.info("=" * 80)
        
        # Process PDFs
        student_documents = self.process_pdfs()
        
        if not student_documents:
            logger.warning("No documents found to process")
            return {
                'status': 'NO_DOCUMENTS',
                'total_students': 0,
                'created_files': []
            }
        
        # Create combined PDFs (only for complete sets)
        created_files, incomplete_students = self.create_combined_pdfs(student_documents)
        
        # Create error report for incomplete sets
        error_report_path = self._create_error_report(incomplete_students)
        
        # Summary
        logger.info("=" * 80)
        logger.info("Processing Summary:")
        logger.info(f"Total students found: {len(student_documents)}")
        logger.info(f"Complete sets processed: {len(created_files)}")
        logger.info(f"Incomplete sets: {len(incomplete_students)}")
        
        # Show complete students
        if created_files:
            logger.info("\n✅ STUDENTS WITH COMPLETE PAPERWORK:")
            for student_id, docs in student_documents.items():
                if len({doc.document_type for doc in docs}) == 3:  # Has all 3 required docs
                    student_name = docs[0].student_name if docs else "Unknown"
                    doc_types = [doc.document_type for doc in docs]
                    logger.info(f"   Student {student_id} ({student_name}): {len(doc_types)} documents")
        
        # Show incomplete students
        if incomplete_students:
            logger.info(f"\n❌ STUDENTS WITH INCOMPLETE PAPERWORK ({len(incomplete_students)}):")
            for student in incomplete_students:
                if student.get('error'):
                    logger.info(f"   Student {student['student_id']} ({student['student_name']}): Processing Error")
                else:
                    missing = ', '.join(student['missing_documents'])
                    logger.info(f"   Student {student['student_id']} ({student['student_name']}): Missing {missing}")
        
        if error_report_path:
            logger.info(f"\n📄 Error report created: {Path(error_report_path).name}")
        
        logger.info("=" * 80)
        
        return {
            'status': 'SUCCESS' if created_files else 'INCOMPLETE_DOCUMENTS',
            'total_students': len(student_documents),
            'complete_students': len(created_files),
            'incomplete_students': len(incomplete_students),
            'created_files': created_files,
            'error_report': error_report_path,
            'incomplete_details': incomplete_students,
            'student_documents': {
                student_id: [doc.document_type for doc in docs] 
                for student_id, docs in student_documents.items()
            }
        }

def main():
    """Main function for standalone execution"""
    processor = ReclassificationProcessor()
    results = processor.run()
    
    if results['status'] == 'SUCCESS':
        print(f"\n✅ Successfully processed {results['complete_students']} student(s) with complete paperwork")
        print(f"📁 Created {len(results['created_files'])} combined PDF(s)")
        
        if results['incomplete_students'] > 0:
            print(f"⚠️  {results['incomplete_students']} student(s) had incomplete paperwork")
            if results['error_report']:
                print(f"📄 See error report: {Path(results['error_report']).name}")
                
    elif results['status'] == 'INCOMPLETE_DOCUMENTS':
        print(f"\n⚠️  Found {results['total_students']} student(s) but none had complete paperwork")
        print(f"❌ {results['incomplete_students']} student(s) missing required documents")
        if results['error_report']:
            print(f"📄 See error report: {Path(results['error_report']).name}")
            
    elif results['status'] == 'NO_DOCUMENTS':
        print("\n⚠️  No documents found to process")
        print("   Make sure PDF files are in the 'in' folder")
    else:
        print(f"\n❌ Processing failed: {results.get('message', 'Unknown error')}")

if __name__ == "__main__":
    main()