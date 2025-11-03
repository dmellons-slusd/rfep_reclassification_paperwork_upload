#!/usr/bin/env python3
"""
Google Drive Folder PDF Counter

This script checks how many PDF files are located in a Google Drive folder
specified in the .env file under GOOGLE_DRIVE_FOLDER_URL.

Supports both Service Account (recommended for automation) and OAuth 2.0 authentication.
"""

import os
import re
import json
import pickle
from pathlib import Path
from decouple import config
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


def extract_folder_id(folder_url: str) -> str:
    """
    Extract the folder ID from a Google Drive folder URL.
    
    Args:
        folder_url: Google Drive folder URL
        
    Returns:
        str: The folder ID
        
    Examples:
        https://drive.google.com/drive/folders/1ABC123xyz
        -> 1ABC123xyz
    """
    # Try different URL patterns
    patterns = [
        r'folders/([a-zA-Z0-9_-]+)',  # Standard URL
        r'id=([a-zA-Z0-9_-]+)',        # Alternative format
    ]
    
    for pattern in patterns:
        match = re.search(pattern, folder_url)
        if match:
            return match.group(1)
    
    # If no pattern matches, assume the entire string is the ID
    return folder_url


def is_service_account_json(creds_file: str) -> bool:
    """
    Determine if the credentials file is a Service Account or OAuth 2.0 Client ID.
    
    Args:
        creds_file: Path to credentials JSON file
        
    Returns:
        bool: True if Service Account, False if OAuth 2.0
    """
    try:
        with open(creds_file, 'r') as f:
            creds_data = json.load(f)
        
        # Service Account has 'type': 'service_account'
        if creds_data.get('type') == 'service_account':
            return True
        
        # OAuth 2.0 has 'installed' or 'web' key
        if 'installed' in creds_data or 'web' in creds_data:
            return False
        
        # Check for service account specific fields
        if 'client_email' in creds_data and 'private_key' in creds_data:
            return True
        
        return False
        
    except Exception as e:
        raise Exception(f"Error reading credentials file: {e}")


def get_google_drive_service_with_service_account(creds_file: str):
    """
    Create Google Drive service using Service Account credentials.
    
    Best for: Automated processes, server-side applications
    
    Args:
        creds_file: Path to service account JSON file
        
    Returns:
        Google Drive service object
    """
    print("🔐 Using Service Account authentication (automated mode)")
    
    # Use full drive scope to allow file operations (download, move, create folders)
    SCOPES = ['https://www.googleapis.com/auth/drive']
    
    credentials = service_account.Credentials.from_service_account_file(
        creds_file, 
        scopes=SCOPES
    )
    
    service = build('drive', 'v3', credentials=credentials)
    return service


def get_google_drive_service_with_oauth(creds_file: str):
    """
    Create Google Drive service using OAuth 2.0 credentials.
    
    Best for: Interactive scripts, user-specific access
    
    Args:
        creds_file: Path to OAuth 2.0 client ID JSON file
        
    Returns:
        Google Drive service object
    """
    print("👤 Using OAuth 2.0 authentication (user mode)")
    
    # Use full drive scope to allow file operations (download, move, create folders)
    SCOPES = ['https://www.googleapis.com/auth/drive']
    
    creds = None
    token_file = 'token.pickle'
    
    # Check if we have saved credentials
    if os.path.exists(token_file):
        print("📌 Found existing token file")
        with open(token_file, 'rb') as token:
            creds = pickle.load(token)
    
    # If there are no valid credentials, let the user log in
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("🔄 Refreshing expired credentials...")
            creds.refresh(Request())
        else:
            print("🌐 No valid credentials found. Starting OAuth flow...")
            print("📝 A browser window will open for you to authorize access")
            flow = InstalledAppFlow.from_client_secrets_file(
                creds_file, SCOPES)
            creds = flow.run_local_server(port=0)
            print("✅ Authorization successful!")
        
        # Save the credentials for the next run
        with open(token_file, 'wb') as token:
            pickle.dump(creds, token)
            print(f"💾 Credentials saved to {token_file}")
    
    service = build('drive', 'v3', credentials=creds)
    return service


def get_google_drive_service():
    """
    Create and return a Google Drive service object.
    
    Automatically detects whether to use Service Account or OAuth 2.0
    based on the credentials file format.
    
    Returns:
        Google Drive service object
    """
    try:
        creds_file = config('GOOGLE_CREDS_FILE')
        
        if not os.path.exists(creds_file):
            raise FileNotFoundError(f"Credentials file not found: {creds_file}")
        
        # Detect credential type and use appropriate authentication method
        if is_service_account_json(creds_file):
            return get_google_drive_service_with_service_account(creds_file)
        else:
            return get_google_drive_service_with_oauth(creds_file)
        
    except Exception as e:
        raise Exception(f"Error creating Google Drive service: {e}")


def count_pdfs_in_folder(service, folder_id: str) -> dict:
    """
    Count the number of PDF files in a Google Drive folder.
    
    Args:
        service: Google Drive service object
        folder_id: The ID of the folder to check
        
    Returns:
        dict: Information about PDFs in the folder
    """
    try:
        # Query to find all PDF files in the specified folder
        query = f"'{folder_id}' in parents and mimeType='application/pdf' and trashed=false"
        
        pdf_files = []
        page_token = None
        
        while True:
            # List files in the folder
            results = service.files().list(
                q=query,
                spaces='drive',
                fields='nextPageToken, files(id, name, size, createdTime, modifiedTime)',
                pageToken=page_token,
                pageSize=100  # Retrieve up to 100 files per request
            ).execute()
            
            files = results.get('files', [])
            pdf_files.extend(files)
            
            page_token = results.get('nextPageToken')
            if not page_token:
                break
        
        # Calculate total size
        total_size = sum(int(f.get('size', 0)) for f in pdf_files)
        
        return {
            'count': len(pdf_files),
            'files': pdf_files,
            'total_size_bytes': total_size,
            'total_size_mb': round(total_size / (1024 * 1024), 2)
        }
        
    except HttpError as error:
        raise Exception(f"Error accessing Google Drive: {error}")


def download_pdf(service, file_id: str, file_name: str, destination_folder: str = './in') -> str:
    """
    Download a PDF file from Google Drive to local folder.
    
    Args:
        service: Google Drive service object
        file_id: The ID of the file to download
        file_name: The name of the file
        destination_folder: Local folder to save the file (default: './in')
        
    Returns:
        str: Path to the downloaded file
    """
    try:
        import io
        from googleapiclient.http import MediaIoBaseDownload
        
        # Create destination folder if it doesn't exist
        os.makedirs(destination_folder, exist_ok=True)
        
        # Get file content
        request = service.files().get_media(fileId=file_id)
        
        # Prepare file path
        file_path = os.path.join(destination_folder, file_name)
        
        # Download file
        fh = io.FileIO(file_path, 'wb')
        downloader = MediaIoBaseDownload(fh, request)
        
        done = False
        while done is False:
            status, done = downloader.next_chunk()
            if status:
                progress = int(status.progress() * 100)
                print(f"  📥 Downloading {file_name}: {progress}%", end='\r')
        
        print(f"  ✅ Downloaded: {file_name}" + " " * 20)  # Clear progress line
        
        return file_path
        
    except HttpError as error:
        raise Exception(f"Error downloading file {file_name}: {error}")


def create_or_get_dated_folder(service, parent_folder_id: str, date_str: str) -> str:
    """
    Create a date-named folder in Google Drive or get existing one.
    
    Args:
        service: Google Drive service object
        parent_folder_id: The ID of the parent folder
        date_str: The date string for folder name (e.g., '2025-11-03')
        
    Returns:
        str: The ID of the date-named folder
    """
    try:
        # Check if folder already exists
        query = f"name='{date_str}' and '{parent_folder_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
        
        results = service.files().list(
            q=query,
            spaces='drive',
            fields='files(id, name)'
        ).execute()
        
        folders = results.get('files', [])
        
        if folders:
            # Folder exists, return its ID
            folder_id = folders[0]['id']
            print(f"  📁 Found existing folder: {date_str} (ID: {folder_id})")
            return folder_id
        else:
            # Create new folder
            file_metadata = {
                'name': date_str,
                'mimeType': 'application/vnd.google-apps.folder',
                'parents': [parent_folder_id]
            }
            
            folder = service.files().create(
                body=file_metadata,
                fields='id, name'
            ).execute()
            
            folder_id = folder.get('id')
            print(f"  📁 Created new folder: {date_str} (ID: {folder_id})")
            return folder_id
        
    except HttpError as error:
        raise Exception(f"Error creating/getting folder: {error}")


def move_file_to_folder(service, file_id: str, file_name: str, source_folder_id: str, destination_folder_id: str):
    """
    Move a file from one folder to another in Google Drive.
    
    Args:
        service: Google Drive service object
        file_id: The ID of the file to move
        file_name: The name of the file (for logging)
        source_folder_id: The ID of the source folder
        destination_folder_id: The ID of the destination folder
    """
    try:
        # Retrieve the existing parents to remove
        file = service.files().get(
            fileId=file_id,
            fields='parents'
        ).execute()
        
        previous_parents = ",".join(file.get('parents', []))
        
        # Move the file to the new folder
        service.files().update(
            fileId=file_id,
            addParents=destination_folder_id,
            removeParents=previous_parents,
            fields='id, parents'
        ).execute()
        
        print(f"  ✅ Moved to archive: {file_name}")
        
    except HttpError as error:
        raise Exception(f"Error moving file {file_name}: {error}")


def download_and_archive_pdfs(service, folder_id: str, pdf_files: list) -> dict:
    """
    Download PDFs to local ./in folder and move them to date-stamped folders in Google Drive.
    
    Args:
        service: Google Drive service object
        folder_id: The ID of the source folder
        pdf_files: List of PDF file information
        
    Returns:
        dict: Summary of operations
    """
    from datetime import datetime
    
    if not pdf_files:
        print("\n⚠️  No PDF files to process")
        return {
            'downloaded': 0,
            'moved': 0,
            'failed': 0,
            'errors': []
        }
    
    print(f"\n{'=' * 70}")
    print("DOWNLOADING AND ARCHIVING PDFs")
    print(f"{'=' * 70}\n")
    
    downloaded_count = 0
    moved_count = 0
    failed_count = 0
    errors = []
    
    # Group files by creation date
    files_by_date = {}
    for file_info in pdf_files:
        # Use createdTime for grouping
        created_time = file_info.get('createdTime', '')
        if created_time:
            # Extract date in YYYY-MM-DD format
            date_str = created_time.split('T')[0]
        else:
            # Fallback to today's date
            date_str = datetime.now().strftime('%Y-%m-%d')
        
        if date_str not in files_by_date:
            files_by_date[date_str] = []
        
        files_by_date[date_str].append(file_info)
    
    print(f"📊 Found PDFs from {len(files_by_date)} different date(s)\n")
    
    # Process each date group
    for date_str, files in files_by_date.items():
        print(f"📅 Processing files from {date_str} ({len(files)} file(s)):")
        
        # Create or get the dated folder
        try:
            dated_folder_id = create_or_get_dated_folder(service, folder_id, date_str)
        except Exception as e:
            error_msg = f"Failed to create/get folder for {date_str}: {e}"
            print(f"  ❌ {error_msg}")
            errors.append(error_msg)
            failed_count += len(files)
            continue
        
        # Download and move each file
        for file_info in files:
            file_id = file_info['id']
            file_name = file_info['name']
            
            try:
                # Download to local ./in folder
                download_pdf(service, file_id, file_name)
                downloaded_count += 1
                
                # Move to dated folder in Google Drive
                move_file_to_folder(service, file_id, file_name, folder_id, dated_folder_id)
                moved_count += 1
                
            except Exception as e:
                error_msg = f"Failed to process {file_name}: {e}"
                print(f"  ❌ {error_msg}")
                errors.append(error_msg)
                failed_count += 1
        
        print()  # Blank line between date groups
    
    return {
        'downloaded': downloaded_count,
        'moved': moved_count,
        'failed': failed_count,
        'errors': errors
    }


def format_file_info(file_info: dict) -> str:
    """
    Format file information for display.
    
    Args:
        file_info: File information dictionary
        
    Returns:
        str: Formatted file information
    """
    name = file_info.get('name', 'Unknown')
    size = int(file_info.get('size', 0))
    size_mb = round(size / (1024 * 1024), 2)
    created = file_info.get('createdTime', 'Unknown')
    modified = file_info.get('modifiedTime', 'Unknown')
    
    return f"  • {name} ({size_mb} MB) - Modified: {modified[:10]}"


def main():
    """Main function to check PDF count in Google Drive folder."""
    
    print("=" * 70)
    print("Google Drive Folder PDF Counter")
    print("=" * 70)
    
    try:
        # Get configuration from .env
        folder_url = config('GOOGLE_DRIVE_FOLDER_URL')
        
        print(f"\n📂 Folder URL: {folder_url}")
        
        # Extract folder ID
        folder_id = extract_folder_id(folder_url)
        print(f"📋 Folder ID: {folder_id}")
        
        # Create Google Drive service
        print("\n🔑 Authenticating with Google Drive...")
        service = get_google_drive_service()
        print("✅ Authentication successful")
        
        # Count PDFs
        print(f"\n🔍 Searching for PDF files in folder...")
        result = count_pdfs_in_folder(service, folder_id)
        
        # Display results
        print("\n" + "=" * 70)
        print("RESULTS")
        print("=" * 70)
        print(f"\n📊 Total PDF files found: {result['count']}")
        print(f"💾 Total size: {result['total_size_mb']} MB ({result['total_size_bytes']:,} bytes)")
        
        if result['count'] > 0:
            print(f"\n📄 PDF Files:")
            for file_info in result['files']:
                print(format_file_info(file_info))
            
            # Ask user if they want to download and archive
            print("\n" + "=" * 70)
            response = input("\n❓ Download PDFs to ./in folder and archive in Google Drive? (y/n): ").strip().lower()
            
            if response == 'y' or response == 'yes':
                # Download and archive
                archive_result = download_and_archive_pdfs(service, folder_id, result['files'])
                
                # Display summary
                print("\n" + "=" * 70)
                print("OPERATION SUMMARY")
                print("=" * 70)
                print(f"\n✅ Downloaded: {archive_result['downloaded']} file(s)")
                print(f"✅ Moved to archive: {archive_result['moved']} file(s)")
                
                if archive_result['failed'] > 0:
                    print(f"❌ Failed: {archive_result['failed']} file(s)")
                    print("\nErrors:")
                    for error in archive_result['errors']:
                        print(f"  • {error}")
                
                print(f"\n📁 PDFs have been downloaded to: ./in")
                print(f"📦 PDFs have been archived in Google Drive by creation date")
            else:
                print("\n⏭️  Skipping download and archive")
        else:
            print("\n⚠️  No PDF files found in the folder")
        
        print("\n" + "=" * 70)
        print("✅ Check complete!")
        print("=" * 70)
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()