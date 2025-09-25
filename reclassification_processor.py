#!/usr/bin/env python3
"""
Simple Reclassification Paperwork PDF Processor

Processes reclassification paperwork PDFs by:
1. Reading PDFs from the 'in' folder
2. Extracting student information and document types
3. Splitting multi-student documents properly
4. Creating combined PDFs for each student
5. Saving results to the 'out' folder
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
    level=logging.DEBUG,
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
    pages: List[int]
    page_count: int

class ReclassificationProcessor:
    """Main processor for reclassification paperwork"""
    
    # Document type patterns
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
            'pattern': r'Notification of English Language Program Exit',
            'title': 'Notification of English Language Program Exit'
        }
    }
    # DOCUMENT_PATTERNS = {
    #     'teacher_recommendation': {
    #         'pattern': r'Teacher Evaluation for Reclassification|Criteria 2: Teacher Evaluation',
    #         'title': 'Teacher Recommendation Form'
    #     },
    #     'reclassification_meeting': {
    #         'pattern': r'Reclassification Meeting w/ Parent/Guardian|Alternate Reclassification IEP Meeting',
    #         'title': 'Reclassification Meeting'
    #     },
    #     'notification_exit': {
    #         'pattern': r'Notification of English Language Program Exit|退出英语教学计划的通知|Notificación de salida del programa de idioma inglés',
    #         'title': 'Notification of English Language Program Exit'
    #     }
    # }
    
    def __init__(self, input_dir: str = "in", output_dir: str = "out"):
        self.input_dir = Path(input_dir)
        self.output_dir = Path(output_dir)
        
        # Create directories if they don't exist
        self.input_dir.mkdir(exist_ok=True)
        self.output_dir.mkdir(exist_ok=True)
        
        logger.info(f"Initialized processor - Input: {self.input_dir}, Output: {self.output_dir}")
    
    def process_pdfs(self) -> Dict[str, List[DocumentInfo]]:
        """Process all PDF files in the input directory"""
        pdf_files = list(self.input_dir.glob("*.pdf"))
        if not pdf_files:
            logger.warning(f"No PDF files found in {self.input_dir}")
            return {}
        
        all_documents = []
        for pdf_file in pdf_files:
            logger.info(f"Processing {pdf_file.name}...")
            documents = self._process_pdf_file(pdf_file)
            all_documents.extend(documents)
        
        # Group documents by student
        return self._group_by_student(all_documents)
    
    def _process_pdf_file(self, pdf_path: Path) -> List[DocumentInfo]:
        """Process a single PDF file and extract document information"""
        documents = []
        
        try:
            with open(pdf_path, 'rb') as file:
                reader = PyPDF2.PdfReader(file)
                total_pages = len(reader.pages)
                
                logger.info(f"Processing {pdf_path.name} - {total_pages} pages")
                
                # Find all pages with student IDs
                student_page_map = {}
                
                for page_num in range(total_pages):
                    try:
                        page = reader.pages[page_num]
                        text = page.extract_text()
                        page_info = self._identify_document_and_student(text)
                        
                        if page_info:
                            student_id = page_info['student_id']
                            if student_id not in student_page_map:
                                student_page_map[student_id] = []
                            
                            student_page_map[student_id].append({
                                'page_num': page_num,
                                'doc_type': page_info['document_type'],
                                'student_name': page_info['student_name']
                            })
                            
                            logger.debug(f"Page {page_num + 1}: {page_info['document_type']} for {student_id}")
                    
                    except Exception as e:
                        logger.error(f"Error processing page {page_num + 1}: {e}")
                        continue
                
                # Assign unassigned pages to students
                documents = self._create_documents_from_student_pages(pdf_path, student_page_map, total_pages)
        
        except Exception as e:
            logger.error(f"Error processing {pdf_path}: {e}")
        
        return documents
    
    def _normalize_ligatures(self, text: str) -> str:
        """Normalize ligatures and special characters to standard ASCII"""
        # Common ligatures that appear in PDFs
        replacements = {
            'ﬁ': 'fi',  # fi ligature
            'ﬂ': 'fl',  # fl ligature
            'ﬀ': 'ff',  # ff ligature
            'ﬃ': 'ffi', # ffi ligature
            'ﬄ': 'ffl', # ffl ligature
        }
        for ligature, replacement in replacements.items():
            text = text.replace(ligature, replacement)
        return text
    
    def _identify_document_and_student(self, text: str) -> Optional[Dict[str, str]]:
        """Identify document type and extract student information"""
        
        # Normalize ligatures first
        text = self._normalize_ligatures(text)
        
        # Find document type
        document_type = None
        for doc_key, doc_info in self.DOCUMENT_PATTERNS.items():
            if re.search(doc_info['pattern'], text, re.IGNORECASE):
                document_type = doc_info['title']
                break
        
        if not document_type:
            return None
        
        # Find student ID
        student_id_patterns = [
            r'Student ID#?\s*:?\s*(\d{6})',
            r'Student ID#?\s*:?\s*(\d{5})',
            r'Student ID[#:\s]*(\d{6})',
            r'Student ID[#:\s]*(\d{5})',
            r'学号[#:\s]*(\d{6})',
            r'学号[#:\s]*(\d{5})',
            r'N°\s*de\s*identificación\s*del\s*estudiante[#:\s]*(\d{6})',
            r'N°\s*de\s*identificación\s*del\s*estudiante[#:\s]*(\d{5})',
        ]
        
        student_id = None
        for pattern in student_id_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                student_id = match.group(1)
                break
        
        if not student_id:
            return None
        
        # Find student name
        name_patterns = [
            r'Name:\s*([A-Za-z\s]+?)(?:\s+Student ID|\n)',
            r'Student:\s*([A-Za-z\s]+?)(?:\s+Student ID|\n)',
            r'学生[:\s]*([A-Za-z\s\u4e00-\u9fff]+?)(?:\s+学号|\n)',
            r'Nombre[:\s]+([A-Za-z\s]+?)(?:\s+Grado|\s+N°|\n)',
            r'([A-Za-z][A-Za-z\s]{2,30})\s+Student ID\s+' + student_id,
        ]
        
        student_name = "Unknown"
        for pattern in name_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                name = match.group(1).strip()
                name = re.sub(r'\s+', ' ', name)
                if len(name) > 2:
                    student_name = name
                    break
        
        return {
            'document_type': document_type,
            'student_id': student_id,
            'student_name': student_name
        }
    
    def _create_documents_from_student_pages(self, pdf_path: Path, student_page_map: Dict, total_pages: int) -> List[DocumentInfo]:
        """Create DocumentInfo objects from student page mappings"""
        documents = []
        
        # Sort students by first page appearance
        sorted_students = sorted(student_page_map.items(), 
                               key=lambda x: min(p['page_num'] for p in x[1]))
        
        # First, determine safe boundaries for each student
        student_boundaries = {}
        for i, (student_id, pages) in enumerate(sorted_students):
            identified_pages = [p['page_num'] for p in pages]
            min_page = min(identified_pages)
            max_page = max(identified_pages)
            
            # Determine safe upper boundary
            if i + 1 < len(sorted_students):
                # There's a next student - boundary is just before their first page
                next_student_pages = [p['page_num'] for p in sorted_students[i + 1][1]]
                next_min = min(next_student_pages)
                safe_upper_bound = next_min - 1
            else:
                # Last student - extend to end of document
                safe_upper_bound = total_pages - 1
            
            student_boundaries[student_id] = {
                'min_page': min_page,
                'max_page': max_page,
                'safe_upper_bound': safe_upper_bound
            }
            
            logger.debug(f"Student {student_id}: pages {identified_pages}, safe boundary: {min_page}-{safe_upper_bound}")
        
        # Now assign continuation/translation pages more carefully
        all_identified_pages = set()
        for pages in student_page_map.values():
            all_identified_pages.update(p['page_num'] for p in pages)
        
        for student_id, pages in student_page_map.items():
            boundaries = student_boundaries[student_id]
            
            # Group pages by document type
            doc_groups = {}
            for page_info in pages:
                doc_type = page_info['doc_type']
                if doc_type not in doc_groups:
                    doc_groups[doc_type] = []
                doc_groups[doc_type].append(page_info['page_num'])
            
            # Look for unassigned continuation/translation pages within safe boundaries
            for page_num in range(boundaries['min_page'], boundaries['safe_upper_bound'] + 1):
                if page_num not in all_identified_pages:
                    # Check if this is a continuation/translation page for the current student
                    page_student_info = self._check_page_belongs_to_student(pdf_path, page_num, student_id)
                    
                    if page_student_info:
                        # This page belongs to this student (could be translation or continuation)
                        # Find the most appropriate document type to assign it to
                        if doc_groups:
                            # Get the document type with the highest page number before this unassigned page
                            best_doc_type = None
                            best_distance = float('inf')
                            
                            for doc_type, doc_pages in doc_groups.items():
                                relevant_pages = [p for p in doc_pages if p < page_num]
                                if relevant_pages:
                                    distance = page_num - max(relevant_pages)
                                    if distance < best_distance:
                                        best_distance = distance
                                        best_doc_type = doc_type
                            
                            # For notification documents, be more liberal with continuation pages (translations)
                            max_distance = 3 if best_doc_type == 'Notification of English Language Program Exit' else 1
                            
                            if best_doc_type and best_distance <= max_distance:
                                doc_groups[best_doc_type].append(page_num)
                                all_identified_pages.add(page_num)
                                logger.debug(f"Assigned continuation/translation page {page_num + 1} to {student_id} - {best_doc_type}")
            
            # Create DocumentInfo for each document type
            for doc_type, page_list in doc_groups.items():
                if page_list:
                    student_name = pages[0]['student_name']
                    documents.append(DocumentInfo(
                        file_path=str(pdf_path),
                        student_id=student_id,
                        student_name=student_name,
                        document_type=doc_type,
                        pages=sorted(page_list),
                        page_count=len(page_list)
                    ))
                    logger.info(f"Created {doc_type} for {student_id} ({student_name}) - pages {sorted(page_list)}")
        
        return documents
    
    def _check_page_belongs_to_student(self, pdf_path: Path, page_num: int, student_id: str) -> bool:
        """Check if a page belongs to a specific student (includes translations)"""
        try:
            with open(pdf_path, 'rb') as file:
                reader = PyPDF2.PdfReader(file)
                if page_num < len(reader.pages):
                    page = reader.pages[page_num]
                    text = page.extract_text()
                    
                    # Normalize ligatures
                    text = self._normalize_ligatures(text)
                    
                    # Check if this page has the student's ID
                    student_id_patterns = [
                        rf'Student ID[#:\s]*{student_id}',
                        rf'学号[#:\s]*{student_id}',
                        rf'N°\s*de\s*identificación\s*del\s*estudiante[#:\s]*{student_id}',
                    ]
                    
                    for pattern in student_id_patterns:
                        if re.search(pattern, text, re.IGNORECASE):
                            return True
                    
                    # Check for translation markers that indicate continuation
                    # (Chinese, Spanish versions without student ID but same document)
                    translation_markers = [
                        r'退出英语教学计划的通知',  # Chinese notification
                        r'Notificación de salida del programa de idioma inglés',  # Spanish notification
                        r'学生信息',  # Chinese "Student Information"
                        r'Información del estudiante',  # Spanish "Student Information"
                    ]
                    
                    for marker in translation_markers:
                        if re.search(marker, text, re.IGNORECASE):
                            # This is likely a translation page, check if it's continuation
                            return True
                    
                    # If page has signature-related content but no new student ID, likely continuation
                    if re.search(r'signature|parent.*guardian|consulta', text, re.IGNORECASE):
                        if not re.search(r'Student ID[#:\s]*\d{5,6}', text, re.IGNORECASE):
                            return True
        except:
            pass
        
        return False
    
    def _is_likely_continuation_page(self, pdf_path: Path, page_num: int) -> bool:
        """Check if a page is likely a continuation page (no new student ID or document type)"""
        try:
            with open(pdf_path, 'rb') as file:
                reader = PyPDF2.PdfReader(file)
                if page_num < len(reader.pages):
                    page = reader.pages[page_num]
                    text = page.extract_text()
                    
                    # Normalize ligatures
                    text = self._normalize_ligatures(text)
                    
                    # If page has a student ID, it's not a continuation page
                    if re.search(r'Student ID[#:\s]*\d{5,6}', text, re.IGNORECASE):
                        return False
                    
                    # If page has a document type header, it's not a continuation page
                    for doc_info in self.DOCUMENT_PATTERNS.values():
                        if re.search(doc_info['pattern'], text, re.IGNORECASE):
                            return False
                    
                    # If it has signature-related content, it might be a continuation
                    if re.search(r'signature|sign|date|agree|disagree', text, re.IGNORECASE):
                        return True
                    
                    # If it's mostly empty or very short, might be continuation
                    return len(text.strip()) < 200
        except:
            pass
        
        return False
    
    def _group_by_student(self, documents: List[DocumentInfo]) -> Dict[str, List[DocumentInfo]]:
        """Group documents by student ID"""
        student_docs = {}
        for doc in documents:
            if doc.student_id not in student_docs:
                student_docs[doc.student_id] = []
            student_docs[doc.student_id].append(doc)
        return student_docs
    
    def create_combined_pdfs(self, student_documents: Dict[str, List[DocumentInfo]]) -> Tuple[List[str], List[Dict]]:
        """Create combined PDFs for students with complete document sets"""
        created_files = []
        incomplete_students = []
        
        required_docs = {
            'Teacher Recommendation Form',
            'Reclassification Meeting', 
            'Notification of English Language Program Exit'
        }
        student_name = None
        student_id = None
        # for student_id, docs in student_documents.items():
        for student_id, docs in student_documents.items():
            for doc in docs:
                if doc.student_id == student_id and doc.student_name and doc.student_name != "Unknown":
                    student_name = doc.student_name
                    break
            # student_name = docs[0].student_name if docs else "Unknown"
            found_doc_types = {doc.document_type for doc in docs}
            
            if required_docs.issubset(found_doc_types):
                # Complete set - create combined PDF
                try:
                    output_filename = f"{student_id}_{student_name.replace(' ', '_')}_Reclassification_Complete.pdf"
                    output_path = self.output_dir / output_filename
                    
                    # Sort documents in proper order
                    sorted_docs = self._sort_documents_by_priority(docs)
                    
                    # Combine PDFs
                    self._combine_documents(sorted_docs, output_path)
                    created_files.append(str(output_path))
                    
                    logger.info(f"Created complete PDF for {student_name} (ID: {student_id}): {output_filename}")
                
                except Exception as e:
                    logger.error(f"Error creating combined PDF for student {student_id}: {e}")
                    incomplete_students.append({
                        'student_id': student_id,
                        'student_name': student_name,
                        'error': str(e),
                        'found_documents': list(found_doc_types),
                        'missing_documents': [],
                        'total_pages': sum(doc.page_count for doc in docs)
                    })
            else:
                # Incomplete set
                missing_docs = required_docs - found_doc_types
                incomplete_students.append({
                    'student_id': student_id,
                    'student_name': student_name,
                    'found_documents': list(found_doc_types),
                    'missing_documents': list(missing_docs),
                    'total_pages': sum(doc.page_count for doc in docs)
                })
                
                logger.warning(f"Incomplete paperwork for {student_name} (ID: {student_id}). Missing: {', '.join(missing_docs)}")
        
        return created_files, incomplete_students
    
    def _sort_documents_by_priority(self, docs: List[DocumentInfo]) -> List[DocumentInfo]:
        """Sort documents in the required order"""
        order_priority = {
            'Notification of English Language Program Exit': 1,
            'Reclassification Meeting': 2,
            'Teacher Recommendation Form': 3,
        }
        
        return sorted(docs, key=lambda x: (order_priority.get(x.document_type, 999), x.document_type))
    
    def _combine_documents(self, docs: List[DocumentInfo], output_path: Path):
        """Combine multiple documents into a single PDF"""
        writer = PyPDF2.PdfWriter()
        
        for doc in docs:
            logger.debug(f"Adding {doc.document_type} for student {doc.student_id} - pages {doc.pages}")
            
            try:
                with open(doc.file_path, 'rb') as file:
                    reader = PyPDF2.PdfReader(file)
                    
                    for page_num in doc.pages:
                        if page_num < len(reader.pages):
                            writer.add_page(reader.pages[page_num])
                        else:
                            logger.warning(f"Page {page_num} not found in {doc.file_path}")
            
            except Exception as e:
                logger.error(f"Error reading document {doc.file_path}: {e}")
                continue
        
        # Write combined PDF
        with open(output_path, 'wb') as output_file:
            writer.write(output_file)
    
    def run(self) -> Dict:
        """Main processing method"""
        logger.info("Starting Reclassification Paperwork Processing")
        
        # Process PDFs
        student_documents = self.process_pdfs()
        
        if not student_documents:
            logger.warning("No documents found to process")
            return {'status': 'NO_DOCUMENTS', 'total_students': 0, 'created_files': []}
        
        # Create combined PDFs
        created_files, incomplete_students = self.create_combined_pdfs(student_documents)
        
        # Summary
        logger.info(f"Processing Summary:")
        logger.info(f"Total students found: {len(student_documents)}")
        logger.info(f"Complete sets processed: {len(created_files)}")
        logger.info(f"Incomplete sets: {len(incomplete_students)}")
        
        return {
            'status': 'SUCCESS' if created_files else 'INCOMPLETE_DOCUMENTS',
            'total_students': len(student_documents),
            'complete_students': len(created_files),
            'incomplete_students': len(incomplete_students),
            'created_files': created_files,
            'incomplete_details': incomplete_students,
        }

def main():
    """Main function for standalone execution"""
    processor = ReclassificationProcessor()
    results = processor.run()
    
    if results['status'] == 'SUCCESS':
        print(f"Successfully processed {results['complete_students']} student(s) with complete paperwork")
        print(f"Created {len(results['created_files'])} combined PDF(s)")
        
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