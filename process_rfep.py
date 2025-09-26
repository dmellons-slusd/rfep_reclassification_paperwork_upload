# process_rfep_enhanced.py
from os import path
import warnings
import dateparser
from datetime import datetime, timedelta
from slusdlib import aeries, core
from sqlalchemy import text
from typing import Union, List
# import read_gsheet
import pandas as pd
import q_update_rfep as q
from decouple import config
# from enhanced_gsheet_writeback import EnhancedGSheetWriteback  # Updated import

def process_rfep_list_with_completion_check(csv: str, cnxn, gsheet_url: str = None, 
                                          id_header: str = 'Student #', 
                                          rfep_date_header: str = 'RFEP Date'):
    """
    Enhanced RFEP processing that respects existing completion statuses
    """
    today = dateparser.parse(datetime.today().date().strftime('%m.%d.%Y'))
    df_reclass_list = pd.read_csv(csv)
    
    # Initialize enhanced writeback handler
    # writeback = EnhancedGSheetWriteback()
    
    # Track updates for batch processing
    updates = []
    
    # Define sheets to search
    search_sheets = ['Main RFEP']
    
    skip_list: List[float] = []
    
    # Pre-check: Build completion status map to show summary
    core.log("Checking existing completion statuses...")
    # student_map = writeback.build_student_location_map_with_completion_check(gsheet_url, search_sheets)
    
    # total_students_in_sheet = len(student_map)
    # already_complete_count = sum(1 for _, _, _, status in student_map.values() if status and status.strip())
    
    # core.log(f"Found {total_students_in_sheet} students in Google Sheet")
    # if already_complete_count > 0:
    #     core.log(f"{already_complete_count} students already completed (will be skipped silently)")
    # core.log(f"{total_students_in_sheet - already_complete_count} students available for processing")
    
    for _, row in df_reclass_list.iterrows():
        stu_id = row[id_header]
        
        if stu_id in skip_list:
            continue
            
        if pd.isna(stu_id) or pd.isna(row[rfep_date_header]):
            if not pd.isna(stu_id):  # Only log if we have a student ID
                updates.append({
                    'student_id': int(stu_id),
                    'status': 'error',
                    'error_message': 'Missing student ID or RFEP date'
                })
            continue
        
        stu_id = int(stu_id)
        
        # Check if this student is already complete before processing
        
        try:
            # Check if student is already RFEP
            rfep_check = student_is_rfep(id=stu_id, cnxn=cnxn)
            if rfep_check == True:
                updates.append({
                    'student_id': stu_id,
                    'status': 'error',
                    'error_message': 'Student already RFEP or not enrolled'
                })
                continue
            
            # Parse RFEP date
            try:
                rfep_date = dateparser.parse(row[rfep_date_header])
            except Exception as e:
                updates.append({
                    'student_id': stu_id,
                    'status': 'error',
                    'error_message': f'Invalid date format: {e}'
                })
                continue
            
            # Build SQL queries (your existing logic)
            sql = {}
            append_comment = append_to_lac_comment(
                id=stu_id, cnxn=cnxn, today=today, 
                append_string='Student is RFEP, LAC closed by automation'
            )
            lac_end_date = rfep_date - timedelta(days=1)
            
            sql['lac_sql'] = q.update_rfep_lac_record.format(
                stu_id=stu_id, rfep_date=rfep_date, 
                appended_comment=append_comment, lac_end_date=lac_end_date
            )
            sql['stu_sql'] = q.update_rfep_stu_record.format(
                stu_id=stu_id, lf_level='4'
            )
            
            # Check for LIP record
            lip_check = has_open_lip(id=stu_id, cnxn=cnxn)
            if lip_check == True:
                new_pgm_comment = append_to_pgm_comment(
                    id=stu_id, cnxn=cnxn, today=today, 
                    append_string='Student is RFEP, LIP record closed by automation.'
                )
                sql['lip_sql'] = q.close_lip.format(
                    stu_id=stu_id, end_date=lac_end_date, new_comment=new_pgm_comment
                )
            
            print(f'Student #: {stu_id}')
            
            # Execute SQL updates
            with cnxn.connect() as conn:
                for key, query in sql.items():
                    conn.execute(text(query))
                conn.commit()
            
            # Mark as complete
            updates.append({
                'student_id': stu_id,
                'status': 'complete'
            })
            
            core.log(f'Student #{stu_id}: Updated LAC and LIP records')
            print(f'Successfully updated student #{stu_id}')
            
        except Exception as e:
            updates.append({
                'student_id': stu_id,
                'status': 'error',
                'error_message': str(e)
            })
            core.log(f'ERROR processing student {stu_id}: {e}')
            print(f'ERROR: {e}')
    
    # Enhanced batch update with completion checking
    # if updates:
    #     core.log(f"Starting enhanced writeback for {len(updates)} updates...")
    #     try:
    #         results = writeback.batch_update_with_completion_check(
    #             gsheet_url=gsheet_url,
    #             updates=updates,
    #             sheet_names=search_sheets,
    #             batch_size=25,  # Smaller batches to respect rate limits
    #             delay_between_batches=2.0,  # 2 second delay between batches
    #             skip_completed=True  # This is the key parameter!
    #         )
            
    #         core.log(f"Enhanced writeback results:")
    #         core.log(f"  - {results['successful']} successful updates")
    #         core.log(f"  - {results['failed']} failed updates")
    #         core.log(f"  - {results['not_found']} students not found in sheet")
    #         if results['skipped_already_complete'] > 0:
    #             core.log(f"  - {results['skipped_already_complete']} students already completed")
            
    #     except Exception as e:
    #         core.log(f"Writeback failed: {e}")
    
    return updates

# Keep your existing helper functions unchanged
def student_is_rfep(id: str, cnxn) -> Union[bool, str]:
    """Checks if the student is RFEP or not"""
    sql = q.rfep_check.format(stu_id=id)
    data = pd.read_sql(sql, cnxn)

    check = False if data.empty else True
    if check == True: return check
    attendance_sql = q.attendance_check.format(stu_id=id)
    data2 = pd.read_sql(attendance_sql, cnxn)

    check2 = False if data2.empty else True
    if check2 == False: 
        core.log(f'ERROR: Student ID# {id} is not enrolled in target school year')
        return True
    return check

def append_to_lac_comment(id: str, cnxn, today: datetime, append_string='Updated by automation on ') -> str:
    """Gets original comment from LAC table and appends {append_string} to it"""
    sql = q.get_lac_commnet.format(stu_id=id)
    original_comment = pd.read_sql(sql, cnxn).values[0][0]
    new_comment = original_comment + ' // ' + append_string + ' 🤖 ' + today.strftime('%m.%d.%Y')
    new_comment = new_comment.replace("'", "")
    return new_comment 

def append_to_pgm_comment(id: str, cnxn, today: datetime, append_string: str='Closed by automation on ') -> str:
    """Gets original comment from open PGM record and appends {append_string} to it"""
    sql = q.get_lip_pgm_commnet.format(stu_id=id)
    original_comment = pd.read_sql(sql, cnxn).values[0][0]
    new_comment = original_comment + ' // ' + append_string + ' 🤖 ' + today.strftime('%m.%d.%Y')
    return new_comment 

def has_open_lip(id: str, cnxn) -> bool:
    """Checks if the student has an open LIP program record"""
    sql = q.lip_check.format(stu_id=id)
    data = pd.read_sql(sql, cnxn)
    check = False if data.empty else True
    return check

if __name__ == '__main__':
    # Ignore dateparser warnings regarding pytz
    warnings.filterwarnings(
        "ignore",
        message="The localize method is no longer necessary, as this time zone supports the fold attribute",
    )
    
    # Configuration
    db_str = config('DATABASE') if not config('TEST_RUN', default='False', cast=bool) else f"{config('DATABASE')}_DAILY" if config('TEST_RUN', default='False', cast=bool) else config('DATABASE')
    test_run = config('TEST_RUN', default='False', cast=bool)
    
    # Read RFEP data from Google Sheet
    in_file = 'out/rfep_dates.csv'
    
    # Database connection
    cnxn = aeries.get_aeries_cnxn(access_level='w', database=config('DATABASE') if not config('TEST_RUN', default='False', cast=bool) else f"{config('DATABASE')}_DAILY" if config('TEST_RUN', default='False', cast=bool) else config('DATABASE'))
    
    date = datetime.today().strftime('%Y-%m-%d')
    core.log(f'~~~~~~~~~~~~~ Starting  RFEP Process for {date} ~~~~~~~~~~~~~')
    core.log(f'Using database: {db_str}')
    core.log(f'Processing will skip students with existing completion status')
    
    # Process with enhanced completion checking
    updates = process_rfep_list_with_completion_check(
        csv=in_file, 
        cnxn=cnxn,
    )
    
    core.log(f'~~~~~~~~~~~~~~~ End of RFEP Process for {date} ~~~~~~~~~~~~~~~~')