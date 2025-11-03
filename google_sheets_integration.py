#!/usr/bin/env python3
"""
Google Sheets Integration for Completed Students Tracking

This module handles reading from and writing to the completed_students Google Sheet.
"""

import re
from typing import List, Dict
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import json
import os


def extract_spreadsheet_id(sheet_url: str) -> str:
    """
    Extract the spreadsheet ID from a Google Sheets URL.
    
    Args:
        sheet_url: Google Sheets URL
        
    Returns:
        str: The spreadsheet ID
        
    Examples:
        https://docs.google.com/spreadsheets/d/1ABC123xyz/edit
        -> 1ABC123xyz
    """
    patterns = [
        r'/spreadsheets/d/([a-zA-Z0-9-_]+)',
        r'id=([a-zA-Z0-9-_]+)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, sheet_url)
        if match:
            return match.group(1)
    
    # If no pattern matches, assume the entire string is the ID
    return sheet_url


def is_service_account_json(creds_file: str) -> bool:
    """Check if credentials file is a Service Account."""
    try:
        with open(creds_file, 'r') as f:
            creds_data = json.load(f)
        return creds_data.get('type') == 'service_account'
    except:
        return False


def get_sheets_service(creds_file: str):
    """
    Create and return a Google Sheets service object.
    
    Args:
        creds_file: Path to service account JSON file
        
    Returns:
        Google Sheets service object
    """
    if not os.path.exists(creds_file):
        raise FileNotFoundError(f"Credentials file not found: {creds_file}")
    
    if not is_service_account_json(creds_file):
        raise ValueError("Google Sheets integration requires Service Account credentials")
    
    SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
    
    credentials = service_account.Credentials.from_service_account_file(
        creds_file,
        scopes=SCOPES
    )
    
    service = build('sheets', 'v4', credentials=credentials)
    return service


def get_completed_students_from_sheet(service, spreadsheet_id: str, sheet_name: str = 'Sheet1') -> List[str]:
    """
    Get list of student IDs that are already completed from Google Sheet.
    
    Args:
        service: Google Sheets service object
        spreadsheet_id: The ID of the spreadsheet
        sheet_name: Name of the sheet/tab (default: 'Sheet1')
        
    Returns:
        List of student IDs as strings
    """
    try:
        # Read the first column (Student ID) from row 2 onwards (skip header)
        range_name = f'{sheet_name}!A2:A'
        
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=range_name
        ).execute()
        
        values = result.get('values', [])
        
        # Extract student IDs and convert to strings
        student_ids = [str(row[0]).strip() for row in values if row]
        
        return student_ids
        
    except HttpError as error:
        if error.resp.status == 404:
            raise Exception(f"Spreadsheet or sheet '{sheet_name}' not found. Make sure the sheet exists and is shared with the service account.")
        raise Exception(f"Error reading from Google Sheet: {error}")


def append_completed_students_to_sheet(service, spreadsheet_id: str, students: List[Dict], sheet_name: str = 'Sheet1'):
    """
    Append newly completed students to the Google Sheet.
    
    Args:
        service: Google Sheets service object
        spreadsheet_id: The ID of the spreadsheet
        students: List of student dictionaries with keys: student_id, student_name, completed_date, output_file
        sheet_name: Name of the sheet/tab (default: 'Sheet1')
        
    Returns:
        int: Number of rows appended
    """
    try:
        if not students:
            return 0
        
        # Prepare rows to append
        rows = []
        for student in students:
            rows.append([
                str(student['student_id']),
                student['student_name'],
                student['completed_date'],
                student['output_file']
            ])
        
        # Append to sheet
        range_name = f'{sheet_name}!A:D'
        
        body = {
            'values': rows
        }
        
        result = service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            valueInputOption='RAW',
            insertDataOption='INSERT_ROWS',
            body=body
        ).execute()
        
        return result.get('updates', {}).get('updatedRows', 0)
        
    except HttpError as error:
        raise Exception(f"Error appending to Google Sheet: {error}")


def initialize_sheet_if_needed(service, spreadsheet_id: str, sheet_name: str = 'Sheet1'):
    """
    Initialize the Google Sheet with headers if it's empty.
    
    Args:
        service: Google Sheets service object
        spreadsheet_id: The ID of the spreadsheet
        sheet_name: Name of the sheet/tab (default: 'Sheet1')
    """
    try:
        # Check if sheet has headers
        range_name = f'{sheet_name}!A1:D1'
        
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=range_name
        ).execute()
        
        values = result.get('values', [])
        
        if not values or not values[0]:
            # Sheet is empty, add headers
            headers = [['Student ID', 'Student Name', 'Completed Date', 'Output File']]
            
            body = {
                'values': headers
            }
            
            service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=f'{sheet_name}!A1:D1',
                valueInputOption='RAW',
                body=body
            ).execute()
            
            print(f"✅ Initialized Google Sheet with headers")
        
    except HttpError as error:
        raise Exception(f"Error initializing Google Sheet: {error}")


def sync_completed_students(creds_file: str, spreadsheet_url: str, new_students: List[Dict], sheet_name: str = 'Sheet1') -> Dict:
    """
    Main function to sync completed students with Google Sheet.
    
    Args:
        creds_file: Path to service account credentials
        spreadsheet_url: URL of the Google Sheet
        new_students: List of newly completed student dictionaries
        sheet_name: Name of the sheet/tab (default: 'Sheet1')
        
    Returns:
        Dict with sync results
    """
    try:
        print("\n" + "=" * 70)
        print("SYNCING COMPLETED STUDENTS WITH GOOGLE SHEET")
        print("=" * 70)
        
        # Extract spreadsheet ID
        spreadsheet_id = extract_spreadsheet_id(spreadsheet_url)
        print(f"📊 Spreadsheet ID: {spreadsheet_id}")
        
        # Get Sheets service
        print("🔑 Authenticating with Google Sheets...")
        service = get_sheets_service(creds_file)
        print("✅ Authentication successful")
        
        # Initialize sheet if needed
        initialize_sheet_if_needed(service, spreadsheet_id, sheet_name)
        
        # Get existing completed students
        print(f"\n📖 Reading existing completed students from sheet...")
        existing_ids = get_completed_students_from_sheet(service, spreadsheet_id, sheet_name)
        print(f"📋 Found {len(existing_ids)} existing completed student(s)")
        
        # Filter out students that are already in the sheet
        students_to_add = [
            student for student in new_students
            if str(student['student_id']) not in existing_ids
        ]
        
        if not students_to_add:
            print("\n⏭️  All students already exist in the sheet - no updates needed")
            return {
                'existing_count': len(existing_ids),
                'added_count': 0,
                'skipped_count': len(new_students),
                'total_count': len(existing_ids)
            }
        
        # Append new students
        print(f"\n➕ Appending {len(students_to_add)} new student(s) to sheet...")
        rows_added = append_completed_students_to_sheet(service, spreadsheet_id, students_to_add, sheet_name)
        
        print(f"\n✅ Successfully added {rows_added} student(s) to Google Sheet")
        
        if len(new_students) > len(students_to_add):
            skipped = len(new_students) - len(students_to_add)
            print(f"⏭️  Skipped {skipped} student(s) (already in sheet)")
        
        print(f"📊 Total completed students in sheet: {len(existing_ids) + rows_added}")
        print("=" * 70)
        
        return {
            'existing_count': len(existing_ids),
            'added_count': rows_added,
            'skipped_count': len(new_students) - len(students_to_add),
            'total_count': len(existing_ids) + rows_added
        }
        
    except Exception as e:
        print(f"\n❌ Error syncing with Google Sheet: {e}")
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    # Test the Google Sheets integration
    from decouple import config
    
    print("Testing Google Sheets Integration")
    print("=" * 70)
    
    try:
        sheet_url = config('GOOGLE_DRIVE_COMPLETED_STUDENTS_SHEET_URL')
        creds_file = config('GOOGLE_CREDS_FILE')
        
        # Test reading
        spreadsheet_id = extract_spreadsheet_id(sheet_url)
        service = get_sheets_service(creds_file)
        
        existing_ids = get_completed_students_from_sheet(service, spreadsheet_id)
        print(f"\n✅ Successfully connected to Google Sheet")
        print(f"📊 Found {len(existing_ids)} completed student(s)")
        
        if existing_ids:
            print("\nFirst 5 student IDs:")
            for student_id in existing_ids[:5]:
                print(f"  • {student_id}")
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")