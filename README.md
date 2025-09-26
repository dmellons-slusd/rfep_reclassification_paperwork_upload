# RFEP Processing System

An automated system for processing Reclassification for Educational Purposes (RFEP) paperwork. This system handles the complete workflow from PDF document processing to database updates and file archival.

## Overview

The RFEP Processing System streamlines the reclassification process by:

1. **Processing multi-student PDF documents** containing reclassification paperwork
2. **Extracting student information** and splitting documents by student
3. **Combining required documents** into complete student packets
4. **Uploading documents** to the document management system
5. **Updating student records** in the database (LAC and LIP records)
6. **Archiving processed files** for record keeping

## Required Document Types

The system processes three types of reclassification documents (in order):

1. **Notification of English Language Program Exit**
2. **Reclassification Meeting**
3. **Teacher Recommendation Form**

Students must have all three document types to create a complete reclassification packet.

## Main Components

### `main.py` - Primary Workflow Orchestrator

The main entry point that coordinates the entire RFEP processing workflow:

1. **Document Processing**: Uses `ReclassificationProcessor` to process PDFs in the `in/` folder
2. **File Upload**: Uploads completed student packets to the document management system
3. **CSV Generation**: Creates a CSV file with student IDs and extracted RFEP dates
4. **Database Updates**: Processes RFEP student list and updates database records
5. **Archival**: Moves processed files to date-stamped archive folders

**Key Functions:**

- `upload_created_files()`: Uploads PDFs to FastAPI-based document system
- `get_reclass_date()`: Extracts reclassification dates from PDF headers
- `create_rfep_csv()`: Generates CSV with student IDs and RFEP dates
- `archive_processed_files()`: Moves files to archive with date stamps

### `reclassification_processor.py` - Core PDF Processing Engine

Handles the complex task of processing multi-student PDF documents:

**Key Features:**

- **Multi-language support**: Handles English, Chinese, and Spanish documents
- **Ligature normalization**: Fixes PDF text extraction issues with special characters
- **Smart document splitting**: Identifies student boundaries and assigns continuation pages
- **Document type detection**: Recognizes the three required document types
- **Student information extraction**: Pulls student IDs and names from various text patterns

**Processing Logic:**

1. Scans all pages to identify students and document types
2. Groups pages by student, including translation/continuation pages
3. Creates `DocumentInfo` objects for each student-document combination
4. Combines documents into complete student packets (only if all 3 types present)
5. Outputs combined PDFs in the specified order

### `process_rfep.py` - Database Integration

Manages the database side of RFEP processing:

**Core Functions:**

- `process_rfep_list_with_completion_check()`: Main processing function that reads CSV and updates records
- `student_is_rfep()`: Validates student eligibility and enrollment status
- `append_to_lac_comment()`: Updates LAC record comments with automation notes
- `append_to_pgm_comment()`: Updates program record comments
- `has_open_lip()`: Checks for open Language Instruction Program records

**Database Operations:**

- Updates student LAC (Language Assessment Committee) records
- Sets student language fluency level to '4' (RFEP status)
- Closes LAC records with RFEP date
- Closes open LIP (Language Instruction Program) records when applicable
- Adds automated comments with timestamps

### `q_update_rfep.py` - SQL Query Definitions

Contains parameterized SQL queries for database operations:

- **LAC Record Updates**: Update dates, status, and comments
- **Student Record Updates**: Set language fluency level
- **Program Record Management**: Close LIP records
- **Validation Queries**: Check student status and enrollment

## Directory Structure

```text
project/
├── in/                     # Input PDFs (processed automatically)
├── out/                    # Generated student packets and CSV
├── archive/               # Archived files by date
│   └── YYYY-MM-DD/       # Date-stamped archive folders
├── main.py               # Primary workflow orchestrator
├── reclassification_processor.py  # PDF processing engine
├── process_rfep.py       # Database integration
├── q_update_rfep.py      # SQL query definitions
├── upload_files.py       # File upload utilities
├── test_processor.py     # Testing and debugging tools
└── analyze_notification_structure.py  # Document analysis tools
```

## Configuration

The system uses environment variables for configuration:

- `FAST_API_URL`: Document management system endpoint
- `FAST_API_USERNAME`: API authentication username  
- `FAST_API_PASSWORD`: API authentication password
- `DATABASE`: Target database name
- `TEST_RUN`: Boolean flag for test mode vs production

## Usage

### Basic Processing

1. Place PDF files in the `in/` folder
2. Run the main script:

   ```bash
   python main.py
   ```

The system will:

- Process all PDFs in the input folder
- Create combined student packets (if complete)
- Upload documents to the management system
- Update database records
- Archive processed files

### Testing and Analysis

- **Test the processor**: `python test_processor.py`
- **Analyze PDF structure**: `python test_processor.py analyze`
- **Debug notifications**: `python analyze_notification_structure.py`

## Document Processing Details

### Student Identification

The system identifies students using multiple pattern matching approaches:

- **Student ID patterns**: Various formats in English, Chinese, and Spanish
- **Name extraction**: Context-aware name parsing with student ID correlation
- **Document type recognition**: Pattern matching for the three required document types

### Multi-language Support

- **English**: Primary document language
- **Chinese**: Translation pages (学生信息, 学号, etc.)
- **Spanish**: Translation pages (Información del estudiante, etc.)

### Page Assignment Logic

1. **Primary pages**: Pages with clear student IDs and document types
2. **Continuation pages**: Signature pages, additional content without new student IDs
3. **Translation pages**: Non-English versions linked to primary pages
4. **Boundary detection**: Smart algorithms to prevent cross-student page assignment

## Error Handling

The system includes comprehensive error handling:

- **Missing documents**: Reports incomplete student packets
- **Invalid dates**: Handles various date formats and parsing errors
- **Database errors**: Validates student enrollment and RFEP eligibility
- **File processing errors**: Continues processing other files if individual files fail

## Output

### Successful Processing

- **Combined PDFs**: `{StudentID}_{StudentName}_Reclassification_Paperwork.pdf`
- **CSV File**: `rfep_students.csv` with student IDs and RFEP dates
- **Database Updates**: LAC and LIP records updated with RFEP status
- **Archive**: All processed files moved to date-stamped archive folder

### Logging

The system provides detailed logging including:

- Processing progress for each student
- Document type identification results
- Database operation results
- Error details and troubleshooting information

## Dependencies

- **PyPDF2**: PDF processing and text extraction
- **pandas**: Data manipulation and CSV processing
- **requests**: HTTP API communication
- **sqlalchemy**: Database operations
- **dateparser**: Flexible date parsing
- **decouple**: Environment variable management
- **slusdlib**: Custom library for Aeries database integration

## Notes

- The system is designed for San Leandro Unified School District's specific document formats
- Document order in output packets follows district requirements
- All database operations include audit trails with automation timestamps
- The system respects existing completion statuses to prevent duplicate processing
