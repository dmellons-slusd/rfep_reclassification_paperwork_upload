#!/usr/bin/env python3
"""
Script to analyze the structure of notification documents
to understand how to properly split them by student
"""

import PyPDF2
import re
from pathlib import Path

def normalize_ligatures(text: str) -> str:
    """Normalize ligatures and special characters to standard ASCII"""
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

def extract_student_name(text, student_id):
    """Extract student name with better patterns"""
    name_patterns = [
        # English patterns with student ID
        rf'Student:\s*([A-Za-z][A-Za-z\s]{{2,40}}?)\s+Student ID[#:\s]*{student_id}',
        rf'Name:\s*([A-Za-z][A-Za-z\s]{{2,40}}?)\s+Student ID[#:\s]*{student_id}',
        # English patterns without ID
        r'Student:\s*([A-Za-z][A-Za-z\s]{2,40}?)\s+Grade',
        r'Student:\s*([A-Za-z][A-Za-z\s]{2,40}?)\s+Student ID',
        # Chinese patterns  
        r'学生[:\s]*([A-Za-z][A-Za-z\s]{2,40}?)\s+等级',
        r'学生[:\s]*([A-Za-z][A-Za-z\s]{2,40}?)\s+学号',
        # Spanish patterns
        r'Nombre[:\s]+([A-Za-z][A-Za-z\s]{2,40}?)\s+Grado',
        r'Estudiante[:\s]+([A-Za-z][A-Za-z\s]{2,40}?)\s+Grado',
    ]
    
    for pattern in name_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            name = match.group(1).strip()
            name = re.sub(r'\s+', ' ', name)
            # Filter out noise
            if len(name) > 2 and not any(char.isdigit() for char in name):
                return name
    return None

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
                r'Student ID#?\s*:?\s*(\d{6})',
                r'Student ID#?\s*:?\s*(\d{5})',
                r'Student ID[#:\s]*(\d{6})',
                r'Student ID[#:\s]*(\d{5})',
                r'学号[#:\s]*(\d{6})',
                r'学号[#:\s]*(\d{5})',
                r'N°\s*de\s*identificación\s*del\s*estudiante[#:\s]*(\d{6})',
                r'N°\s*de\s*identificación\s*del\s*estudiante[#:\s]*(\d{5})',
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
            
            # Translation markers (pages without student ID)
            translation_markers = [
                r'退出英语教学计划的通知',  # Chinese notification title
                r'Notificación de salida del programa de idioma inglés',  # Spanish notification title
                r'用于确定您的孩子退出课程的其他因素',  # Chinese "Additional factors"
                r'Factores adicionales usados para determinar',  # Spanish "Additional factors"
            ]
            
            students_found = []
            page_info = []  # Track all page information
            
            for page_num in range(total_pages):
                print(f"\nPAGE {page_num + 1}")
                print("-" * 50)
                
                try:
                    page = reader.pages[page_num]
                    text = page.extract_text()
                    
                    # Normalize ligatures
                    text = normalize_ligatures(text)
                    
                    # Look for section boundaries
                    print("Section markers found:")
                    for pattern in section_patterns:
                        matches = list(re.finditer(pattern, text, re.IGNORECASE))
                        if matches:
                            for match in matches:
                                print(f"  - '{pattern}' at position {match.start()}")
                    
                    # Check for translation markers
                    is_translation = False
                    for marker in translation_markers:
                        if re.search(marker, text, re.IGNORECASE):
                            print(f"  - TRANSLATION PAGE detected: '{marker}'")
                            is_translation = True
                            break
                    
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
                    
                    # Extract student name if we have an ID
                    if student_id:
                        student_name = extract_student_name(text, student_id)
                        if student_name:
                            print(f"Student Name found: '{student_name}'")
                    
                    # Store page information
                    page_info.append({
                        'page_num': page_num + 1,
                        'has_student_id': student_id is not None,
                        'student_id': student_id,
                        'student_name': student_name,
                        'is_translation': is_translation
                    })
                    
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
            
            # Analyze page groupings with translation detection
            print("\n" + "=" * 70)
            print("DETAILED PAGE ANALYSIS:")
            print("-" * 30)
            
            current_student = None
            for info in page_info:
                if info['has_student_id']:
                    current_student = info['student_id']
                    print(f"\nPage {info['page_num']}: Student {info['student_id']} ({info['student_name']}) - PRIMARY PAGE")
                elif info['is_translation'] and current_student:
                    print(f"Page {info['page_num']}: -> Translation/continuation for Student {current_student}")
                else:
                    print(f"Page {info['page_num']}: Unassigned or continuation page")
            
            # Recommendations
            print("\n" + "=" * 70)
            print("RECOMMENDATIONS:")
            print("-" * 30)
            if len(students_found) > 1:
                print("- Multiple students detected in notification document")
                print("- Need to split document by student sections")
                print("- Each student should get their own notification pages")
                print("- Translation pages (Chinese/Spanish) should be grouped with their student")
            else:
                print("- Only one student detected or detection failed")
                print("- Check if document actually contains multiple students")
            
            # Show page groupings with translation awareness
            if len(students_found) >= 1:
                print("\n" + "=" * 70)
                print("SUGGESTED PAGE GROUPINGS:")
                print("-" * 30)
                
                for i, student in enumerate(students_found):
                    start_page = student['page']
                    
                    # Calculate end page
                    if i < len(students_found) - 1:
                        # End before next student's first page
                        end_page = students_found[i + 1]['page'] - 1
                    else:
                        # Last student gets remaining pages
                        end_page = total_pages
                    
                    # Count how many pages this student should have
                    page_count = end_page - start_page + 1
                    
                    # Estimate: 1 English page + up to 2 translation pages = typically 2-4 pages per student
                    if page_count > 4:
                        print(f"WARNING: Student {student['student_id']} ({student['student_name']}): Pages {start_page}-{end_page} ({page_count} pages - UNUSUALLY HIGH)")
                    else:
                        print(f"Student {student['student_id']} ({student['student_name']}): Pages {start_page}-{end_page} ({page_count} pages)")
                    
                    # Show which pages are translations
                    for p in range(start_page, end_page + 1):
                        page_data = page_info[p - 1]
                        if page_data['is_translation']:
                            print(f"  -> Page {p}: Translation/continuation page")
    
    except Exception as e:
        print(f"Error analyzing file: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("\n" + "=" * 70)
        print("Analysis complete.")
        print("\nKey Findings:")
        print("- Notification documents typically have 2-4 pages per student")
        print("- Page 1: English version with student ID")
        print("- Page 2: English continuation (if needed)")
        print("- Page 3+: Chinese/Spanish translations (may not have student ID)")
        print("\nThe processor should:")
        print("1. Detect student ID on first page")
        print("2. Capture subsequent pages until next student ID appears")
        print("3. Include translation pages even without student ID")

if __name__ == "__main__":
    analyze_notification_structure()