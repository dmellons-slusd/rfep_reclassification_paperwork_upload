# RFEP Processing System

An automated system for processing Reclassification for Educational Purposes (RFEP) paperwork. This system handles the complete workflow from Google Drive integration to PDF document processing, database updates, and comprehensive tracking via Google Sheets.

## Overview

The RFEP Processing System streamlines the reclassification process by:

1. **Automatically downloading PDFs** from Google Drive and archiving them by date
2. **Processing multi-student PDF documents** containing reclassification paperwork
3. **Extracting student information** and intelligently splitting documents by student
4. **Combining required documents** into complete student packets
5. **Preventing duplicate uploads** through Google Sheets integration
6. **Uploading documents** to the document management system
7. **Tracking completion status** in both local CSV and Google Sheets
8. **Updating student records** in the database (LAC and LIP records)
9. **Archiving processed files** for record keeping with date stamps
10. **Generating comprehensive reports** on completed and incomplete students

## Required Document Types

The system processes three types of reclassification documents (in order):

1. **Notification of English Language Program Exit**
2. **Reclassification Meeting**
3. **Teacher Recommendation Form**

Students must have all three document types to create a complete reclassification packet.

## Main Components

### `main.py` - Primary Workflow Orchestrator

The main entry point that coordinates the entire RFEP processing workflow with full automation:

1. **Google Drive Download**: Automatically downloads new PDFs from specified Google Drive folder
2. **Document Processing**: Uses `ReclassificationProcessor` to process PDFs in the `in/` folder
3. **Duplicate Prevention**: Checks Google Sheets for previously completed students before uploading
4. **File Upload**: Uploads completed student packets to the document management system
5. **Completion Tracking**: Updates both local CSV and Google Sheets with completion dates
6. **CSV Generation**: Creates CSV file with student IDs and extracted RFEP dates
7. **Database Updates**: Processes RFEP student list and updates database records
8. **Report Upload**: Uploads completion and missing paperwork reports to Google Drive
9. **Archival**: Moves processed files to date-stamped archive folders

**Key Functions:**

- `download_new_pdfs_from_drive()`: Automatically downloads PDFs from Google Drive and archives them by creation date
- `get_previously_uploaded_files()`: Retrieves completion status from Google Sheets (with CSV fallback)
- `upload_created_files()`: Uploads PDFs to FastAPI-based document system (skips already completed students)
- `get_reclass_date()`: Extracts reclassification dates from PDF headers using multiple date format patterns
- `create_rfep_csv()`: Generates CSV with student IDs and RFEP dates for database processing
- `upload_csv_reports_to_drive()`: Uploads completion and missing paperwork reports to Google Drive
- `archive_processed_files()`: Moves files to date-stamped archive folders

**Completion Tracking Fix (Latest Update):**
- **Preserves original completion dates**: No longer overwrites completion dates when re-processing students
- **Only adds new students**: Checks if student already exists before updating CSV
- **Accurate historical data**: Ensures completion dates reflect when student was first completed, not last processed

### `reclassification_processor.py` - Core PDF Processing Engine

Handles the complex task of processing multi-student PDF documents with advanced intelligence:

**Key Features:**

- **Multi-language support**: Handles English, Chinese, and Spanish documents
- **Ligature normalization**: Fixes PDF text extraction issues with special characters (ﬁ → fi, ﬂ → fl, etc.)
- **Smart document splitting**: Identifies student boundaries and assigns continuation pages intelligently
- **Document type detection**: Recognizes the three required document types using pattern matching
- **Student information extraction**: Pulls student IDs and names from various text patterns across languages
- **Completion tracking**: Maintains history of completed students without duplicates
- **Missing paperwork reports**: Generates CSV reports of students with incomplete document sets

**Processing Logic:**

1. Scans all pages to identify students and document types
2. Groups pages by student, including translation/continuation pages
3. Creates `DocumentInfo` objects for each student-document combination
4. Combines documents into complete student packets (only if all 3 types present)
5. Outputs combined PDFs in the specified order
6. Exports two CSV files:
   - `completed_students.csv`: Historical log of all completed students (append-only, no duplicates)
   - `missing_paperwork - [DATE].csv`: Current list of students with incomplete paperwork (overwrites daily)

### `process_rfep.py` - Database Integration

Manages the database side of RFEP processing with validation and error handling:

**Core Functions:**

- `process_rfep_list_with_completion_check()`: Main processing function that reads CSV and updates records
- `student_is_rfep()`: Validates student eligibility and enrollment status before processing
- `append_to_lac_comment()`: Updates LAC record comments with automation notes and timestamps
- `append_to_pgm_comment()`: Updates program record comments with automation notes and timestamps
- `has_open_lip()`: Checks for open Language Instruction Program records

**Database Operations:**

- Updates student LAC (Language Assessment Committee) records
- Sets student language fluency level to '4' (RFEP status)
- Closes LAC records with RFEP date (one day before reclassification date)
- Closes open LIP (Language Instruction Program) records when applicable
- Adds automated comments with emoji indicators (🤖) and timestamps
- Validates student enrollment and RFEP eligibility before making changes

### `q_update_rfep.py` - SQL Query Definitions

Contains parameterized SQL queries for database operations:

- **LAC Record Updates**: Update reclassification date, clear program fields, set end date, append comments
- **Student Record Updates**: Set language fluency level to RFEP status
- **Program Record Management**: Close LIP records with end dates and comments
- **Validation Queries**: Check student RFEP status, attendance records, and LIP records

### `google_sheets_integration.py` - Completion Tracking

Manages Google Sheets integration for tracking completed students:

**Key Functions:**

- `sync_completed_students()`: Main sync function that updates Google Sheet with new completions
- `get_completed_students_from_sheet()`: Retrieves list of previously completed student IDs
- `append_completed_students_to_sheet()`: Appends only new students to the tracking sheet
- `initialize_sheet_if_needed()`: Sets up headers if sheet is empty

**Features:**

- **Duplicate prevention**: Only adds students not already in the sheet
- **Historical tracking**: Maintains permanent record of all completed students
- **Automatic initialization**: Creates headers if sheet is empty
- **Batch operations**: Efficiently appends multiple students in a single API call
- **Fallback support**: Uses local CSV if Google Sheets is unavailable

### `folder_check.py` - Google Drive Integration

Handles all Google Drive operations for automated file management:

**Key Functions:**

- `get_google_drive_service()`: Creates authenticated Drive service (Service Account or OAuth 2.0)
- `count_pdfs_in_folder()`: Counts and lists PDF files in specified folder
- `download_and_archive_pdfs()`: Downloads PDFs locally and archives in Drive by creation date
- `create_or_get_dated_folder()`: Creates or retrieves date-stamped folders (YYYY-MM-DD format)
- `move_file_to_folder()`: Moves files between Google Drive folders
- `upload_csv_reports_to_drive()`: Uploads completion and missing paperwork reports

**Features:**

- **Dual authentication support**: Automatically detects Service Account vs OAuth 2.0 credentials
- **Automatic archiving**: Organizes processed PDFs by creation date in Google Drive
- **Batch processing**: Handles multiple files efficiently
- **Error handling**: Continues processing if individual files fail
- **Progress tracking**: Real-time download progress indicators

## Directory Structure

```text
project/
├── in/                     # Input PDFs (downloaded from Google Drive)
├── out/                    # Generated student packets and reports
│   ├── {StudentID}_{Name}_Reclassification_Paperwork.pdf
│   ├── completed_students.csv              # Historical log (append-only)
│   ├── missing_paperwork - [DATE].csv      # Daily report (overwrites)
│   └── rfep_dates.csv                      # For database processing
├── archive/                # Archived files by date
│   └── YYYY-MM-DD/        # Date-stamped archive folders
├── test/                   # Test scripts and utilities
├── main.py                 # Primary workflow orchestrator
├── reclassification_processor.py  # PDF processing engine
├── process_rfep.py         # Database integration
├── q_update_rfep.py        # SQL query definitions
├── google_sheets_integration.py   # Completion tracking
├── folder_check.py         # Google Drive operations
├── upload_files.py         # Document system upload utilities
├── test_processor.py       # Testing and debugging tools
├── analyze_notification_structure.py  # Document analysis tools
└── .env                    # Configuration (not in git)
```

## Configuration

The system uses environment variables in `.env` file for configuration:

### Required Configuration

- `FAST_API_URL`: Document management system endpoint
- `FAST_API_USERNAME`: API authentication username  
- `FAST_API_PASSWORD`: API authentication password
- `DATABASE`: Target Aeries database name (e.g., 'DST_AER')
- `TEST_RUN`: Boolean flag (`True` for test mode, `False` for production)

### Google Integration (Required for full automation)

- `GOOGLE_CREDS_FILE`: Path to Google service account JSON file (e.g., 'creds.json')
- `GOOGLE_DRIVE_FOLDER_URL`: URL of Google Drive folder containing PDFs
- `GOOGLE_DRIVE_COMPLETED_STUDENTS_SHEET_URL`: URL of Google Sheet tracking completed students

### Example `.env` file:

```bash
# Document Management System
FAST_API_URL=https://your-api-url.com
FAST_API_USERNAME=your_username
FAST_API_PASSWORD=your_password

# Database
DATABASE=DST_AER
TEST_RUN=False

# Google Integration
GOOGLE_CREDS_FILE=creds.json
GOOGLE_DRIVE_FOLDER_URL=https://drive.google.com/drive/folders/your-folder-id
GOOGLE_DRIVE_COMPLETED_STUDENTS_SHEET_URL=https://docs.google.com/spreadsheets/d/your-sheet-id
```

## Usage

### Fully Automated Processing (Recommended)

The system runs completely automatically when properly configured:

```bash
python main.py
```

**What happens:**

1. ✅ Downloads new PDFs from Google Drive
2. ✅ Archives downloaded PDFs by creation date in Drive
3. ✅ Processes all PDFs to extract and combine documents
4. ✅ Checks Google Sheets to prevent duplicate uploads
5. ✅ Uploads only new completed student packets
6. ✅ Updates both local CSV and Google Sheets with completion dates
7. ✅ Uploads completion and missing paperwork reports to Drive
8. ✅ Updates database records for newly completed students only
9. ✅ Archives all processed files locally with date stamps

### Manual Processing (Without Google Drive)

If Google Drive is not configured, place PDFs manually in `in/` folder:

```bash
python main.py
```

The system will process local files and skip Google Drive operations.

### Testing and Analysis

- **Test the processor**: `python test_processor.py`
- **Analyze PDF structure**: `python test_processor.py analyze`
- **Debug notifications**: `python analyze_notification_structure.py`
- **Check Google Drive folder**: `python folder_check.py`

## Document Processing Details

### Student Identification

The system identifies students using multiple pattern matching approaches:

- **Student ID patterns**: Various formats in English, Chinese, and Spanish
  - English: `Student ID#: 106874`, `Student ID: 106874`
  - Chinese: `学号: 106874`
  - Spanish: `N° de identificación del estudiante: 106874`
- **Name extraction**: Context-aware name parsing with student ID correlation
- **Document type recognition**: Pattern matching for the three required document types

### Multi-language Support

- **English**: Primary document language
- **Chinese**: Translation pages (学生信息, 学号, 退出英语教学计划的通知, etc.)
- **Spanish**: Translation pages (Información del estudiante, Notificación de salida, etc.)

### Page Assignment Logic

1. **Primary pages**: Pages with clear student IDs and document types
2. **Continuation pages**: Signature pages, additional content without new student IDs
3. **Translation pages**: Non-English versions linked to primary pages (typically 2-4 pages per student)
4. **Boundary detection**: Smart algorithms to prevent cross-student page assignment
   - Uses safe boundaries between students
   - Maximum distance of 3 pages for notification translations
   - Maximum distance of 1 page for other document continuations

### Duplicate Prevention System

**Three-layer protection against re-uploading:**

1. **Google Sheets check**: Primary source of truth for completion status
2. **Local CSV fallback**: Used if Google Sheets is unavailable
3. **File naming convention**: Student ID in filename prevents overwrites

**Completion date preservation:**
- Original completion dates are never overwritten
- Re-processing a student preserves their first completion date
- Historical accuracy is maintained across local and cloud systems

## Error Handling

The system includes comprehensive error handling:

- **Missing documents**: Reports incomplete student packets in daily CSV report
- **Invalid dates**: Handles various date formats (MM/DD/YYYY, MM-DD-YYYY, MM.DD.YYYY)
- **Database errors**: Validates student enrollment and RFEP eligibility before updates
- **File processing errors**: Continues processing other files if individual files fail
- **Google API errors**: Falls back to local processing if Google services unavailable
- **Duplicate prevention**: Skips students already completed to prevent database conflicts
- **Ligature issues**: Normalizes PDF text extraction problems automatically

## Output Files

### Student Packets (when complete)

**Filename format**: `{StudentID}_{FirstName}_{LastName}_Reclassification_Paperwork.pdf`

**Example**: `106874_Borui_Hu_Reclassification_Paperwork.pdf`

**Document order** (as required by district):
1. Notification of English Language Program Exit (with translations)
2. Reclassification Meeting
3. Teacher Recommendation Form

### CSV Reports

**`completed_students.csv`** - Historical log (append-only, no duplicates):
- Student ID
- Student Name  
- Completed Date (first completion, never changes)
- Output File (PDF filename)

**`missing_paperwork - [DATE].csv`** - Daily report (overwrites each run):
- Student ID
- Student Name
- Missing Documents (list of missing doc types)
- Found Documents (list of available doc types)
- Error (if any processing errors occurred)

**`rfep_dates.csv`** - For database processing:
- Student # (Student ID)
- RFEP Date (extracted from Notification header)

### Database Updates

- **LAC records**: Reclassification date, program closure, end date, automation comments
- **STU records**: Language fluency level set to '4' (RFEP status)
- **PGM records**: LIP record closure with end dates and automation comments (if applicable)

### Archive Structure

**Local archives** (by processing date):
```
archive/
├── 2025-11-03/
│   ├── 106874_Borui_Hu_Reclassification_Paperwork.pdf
│   ├── 112048_Angel_Ramirez_Hermosillo_Reclassification_Paperwork.pdf
│   └── rfep_dates.csv
```

**Google Drive archives** (by file creation date):
```
Google Drive Folder/
├── 2025-11-01/
│   └── Notification of Ext 11-01-2025.pdf
├── 2025-11-02/
│   └── Teacher Recommendations 11-02-2025.pdf
```

## Logging

The system provides detailed logging in `log.log` including:

- **Processing progress**: Each step of the workflow with timestamps
- **Student processing**: Individual student IDs and names being processed
- **Document identification**: What document types were found for each student
- **Upload results**: Success/failure for each file upload
- **Database operations**: SQL execution results and any errors
- **Google Drive operations**: Download/upload/archive activities
- **Google Sheets sync**: Completion tracking updates
- **Error details**: Full stack traces for troubleshooting

## Dependencies

### Core Dependencies

- **PyPDF2**: PDF processing and text extraction
- **pandas**: Data manipulation and CSV processing
- **requests**: HTTP API communication for document uploads
- **sqlalchemy**: Database operations and query execution
- **dateparser**: Flexible date parsing from PDF text
- **decouple**: Environment variable management from .env file
- **slusdlib**: Custom library for Aeries database integration

### Google Integration Dependencies

- **google-auth**: Google API authentication
- **google-auth-oauthlib**: OAuth 2.0 authentication flow
- **google-auth-httplib2**: HTTP library for Google APIs
- **google-api-python-client**: Google Drive and Sheets API client

## Installation

1. Clone the repository
2. Install dependencies:
   ```bash
   pip install PyPDF2 pandas requests sqlalchemy dateparser python-decouple google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client
   ```
3. Set up Google Service Account:
   - Create service account in Google Cloud Console
   - Download credentials JSON file
   - Share Google Drive folder with service account email
   - Share Google Sheets with service account email (Editor access)
4. Configure `.env` file with all required variables
5. Run the system: `python main.py`

## Workflow Summary

### Step 1: Download from Google Drive
- Authenticates with Google Drive (Service Account or OAuth)
- Searches for PDF files in configured folder
- Downloads all PDFs to local `in/` folder
- Archives PDFs in Google Drive by creation date (YYYY-MM-DD folders)

### Step 2: Process PDFs
- Scans all PDFs for students and document types
- Identifies student boundaries and assigns pages
- Handles multi-language documents (English, Chinese, Spanish)
- Combines complete document sets into student packets
- Generates missing paperwork report for incomplete students

### Step 3: Upload to Document System
- Checks Google Sheets for previously completed students
- Skips students already completed (prevents duplicates)
- Uploads only new completed student packets
- Records upload results with timestamps

### Step 4: Track Completion
- Updates local CSV with new completions (preserves original dates)
- Syncs new completions to Google Sheets
- Maintains historical record without duplicates
- Uploads reports to Google Drive

### Step 5: Update Database
- Creates CSV with RFEP dates from PDF headers
- Processes only newly uploaded students
- Updates LAC, STU, and PGM records
- Adds automation comments with timestamps

### Step 6: Archive Files
- Moves processed PDFs to date-stamped local archive
- Preserves all generated reports
- Maintains organized file structure

## Notes

- The system is designed for San Leandro Unified School District's specific document formats
- Document order in output packets follows district requirements
- All database operations include audit trails with automation timestamps (🤖 emoji)
- The system respects existing completion statuses to prevent duplicate processing
- Google Sheets provides cloud-based completion tracking accessible across systems
- Completion dates are preserved and never overwritten on re-processing
- The system handles PDF text extraction issues (ligatures) automatically
- Multi-language support covers English, Chinese (Mandarin), and Spanish documents
- Error handling allows processing to continue even if individual files fail
- Comprehensive logging enables troubleshooting and audit trails

## Troubleshooting

### Common Issues

**No PDFs downloaded from Google Drive:**
- Verify `GOOGLE_DRIVE_FOLDER_URL` is correct
- Check service account has access to the folder
- Ensure credentials file path is correct in `.env`

**Students showing as already completed when they shouldn't be:**
- Check Google Sheets for existing entries
- Verify local `completed_students.csv` doesn't have old data
- Review log file for completion tracking messages

**Date extraction fails:**
- Check PDF header format matches expected patterns (MM/DD/YYYY)
- Review log file for "No date found" messages
- Use `analyze_notification_structure.py` to debug PDF structure

**Database update errors:**
- Verify student is enrolled and not already RFEP
- Check database connection settings in `.env`
- Review SQL queries in `q_update_rfep.py` for compatibility

**Google Sheets sync fails:**
- Verify sheet URL is correct
- Check service account has Editor access to sheet
- Review error messages in console or log file
