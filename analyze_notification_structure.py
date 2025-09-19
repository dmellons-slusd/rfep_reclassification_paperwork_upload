#!/usr/bin/env python3
"""
Script to analyze the structure of notification documents
to understand how to properly split them by student
"""

import PyPDF2
import re
from pathlib import Path

def analyze_notification_structure():
    """Analyze the notification PDF to understand student boundaries"""
    
    pdf_file = Path("in") / "Notification of Ext 9-18-2025.pdf"
    
    if not pdf_file.exists():
        print(f"File not found: {pdf_file}")
        return
    
    print(f"Analyzing notification document structure: {pdf_file.name}")
    print("=" * 70)
    
    try:
        with open(pdf_file, 'rb') as file:
            reader = PyPDF2.PdfReader(file)
            total_pages = len(reader.pages)
            
            print(f"Total pages: {total_pages}")
            print()
            
            # Student ID patterns for detection
            student_id_patterns = [
                r'Student ID#:\s*(\d{6})',
                r'Student ID#:\s*(\d{5})',
                r'学号[#:\s]*(\d{6})',
                r'学号[#:\s]*(\d{5})',
                r'N°\s*de\s*identificación\s*del\s*estudiante[#:\s]*(\d{6})',
                r'N°\s*de\s*identificación\s*del\s*estudiante[#:\s]*(\d{5})',
            ]
            
            # Student name patterns
            name_patterns = [
                r'Student:\s*([A-Za-z\s]+?)(?:\s+Student ID|$|\n)',
                r'学生[:\s]*([A-Za-z\s\u4e00-\u9fff]+?)(?:\s+学号|\s+等级|\n)',
                r'(?:Nombre|Estudiante)[:\s]+([A-Za-z\s]+?)(?:\s+Grado|\s+N°|\n)',
            ]
            
            # Section boundary patterns
            section_patterns = [
                r'Student Information',
                r'学生信息',
                r'Información del estudiante',
                r'Notification of English Language Program Exit',
                r'退出英语教学计划的通知',
                r'Notificación de salida del programa de idioma inglés',
            ]
            
            students_found = []
            
            for page_num in range(total_pages):
                print(f"\nPAGE {page_num + 1}")
                print("-" * 50)
                
                try:
                    page = reader.pages[page_num]
                    text = page.extract_text()
                    
                    # Look for section boundaries
                    print("Section markers found:")
                    for pattern in section_patterns:
                        matches = list(re.finditer(pattern, text, re.IGNORECASE))
                        if matches:
                            for match in matches:
                                print(f"  - '{pattern}' at position {match.start()}")
                    
                    # Look for student info
                    student_id = None
                    student_name = None
                    
                    # Extract student ID
                    for pattern in student_id_patterns:
                        match = re.search(pattern, text, re.IGNORECASE)
                        if match:
                            student_id = match.group(1)
                            print(f"Student ID found: {student_id} (pattern: {pattern})")
                            break
                    
                    # Extract student name
                    for pattern in name_patterns:
                        match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
                        if match:
                            name = match.group(1).strip()
                            name = re.sub(r'\s+', ' ', name)
                            if name and len(name) > 2:
                                student_name = name
                                print(f"Student Name found: '{student_name}' (pattern: {pattern})")
                                break
                    
                    if student_id and student_name:
                        student_info = {
                            'page': page_num + 1,
                            'student_id': student_id,
                            'student_name': student_name
                        }
                        students_found.append(student_info)
                        print(f"STUDENT DETECTED: {student_name} (ID: {student_id})")
                    
                    # Show first 300 characters for context
                    print(f"\nFirst 300 characters:")
                    print(repr(text[:300]))
                    
                    # Look for potential page breaks between students
                    if "Student Information" in text or "学生信息" in text or "Información del estudiante" in text:
                        print("*** POTENTIAL STUDENT SECTION START ***")
                    
                except Exception as e:
                    print(f"Error processing page {page_num + 1}: {e}")
                    continue
            
            # Summary
            print("\n" + "=" * 70)
            print("SUMMARY OF STUDENTS FOUND:")
            print("-" * 30)
            
            for i, student in enumerate(students_found, 1):
                print(f"{i}. Page {student['page']}: {student['student_name']} (ID: {student['student_id']})")
            
            print(f"\nTotal students detected: {len(students_found)}")
            
            # Recommendations
            print("\nRECOMMENDATIONS:")
            print("-" * 20)
            if len(students_found) > 1:
                print("- Multiple students detected in notification document")
                print("- Need to split document by student sections")
                print("- Each student should get their own notification pages")
            else:
                print("- Only one student detected or detection failed")
                print("- Check if document actually contains multiple students")
            
            # Show page groupings
            if len(students_found) > 1:
                print("\nSUGGESTED PAGE GROUPINGS:")
                print("-" * 30)
                for i, student in enumerate(students_found):
                    start_page = student['page']
                    if i < len(students_found) - 1:
                        end_page = students_found[i + 1]['page'] - 1
                        print(f"Student {student['student_id']} ({student['student_name']}): Pages {start_page}-{end_page}")
                    else:
                        print(f"Student {student['student_id']} ({student['student_name']}): Pages {start_page}-{total_pages}")
    
    except Exception as e:
        print(f"Error analyzing file: {e}")
    finally:
        print("\nAnalysis complete.")

if __name__ == "__main__":
    analyze_notification_structure()