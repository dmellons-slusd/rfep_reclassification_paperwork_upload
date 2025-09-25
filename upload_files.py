from decouple import config
import re

def upload_created_files(created_files):
    """Uploads the created files to the desired location.
    
    Args:
        created_files (list): List of file paths to upload.
        
    Returns:
        list: List of uploaded file URLs or paths.
    """
    
    uploaded_files = []
    for file_path in created_files:
        student_id = file_path.split('\\')[1].split('_')[0].strip()
        print(f"Preparing to upload file for student ID: {student_id}")
       
    return uploaded_files

if __name__ == "__main__":
    created_files = ['out\\106874_Borui_Hu_Reclassification_Complete.pdf', 'out\\112048_Angel_Ramirez_Hermosillo_Reclassification_Complete.pdf']
    uploaded_files = upload_created_files(created_files)