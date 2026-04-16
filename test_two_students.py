from rfep_monitoring_process_paperwork import MonitoringProcessor, upload_created_files

processor = MonitoringProcessor()
students = processor.process_pdfs()

target = [s for s in students if s['student_id'] in ('107553', '107481')]
print(f'Found {len(target)} matching students: {[(s["student_id"], s["student_name"]) for s in target]}')

created = processor.create_per_student_pdfs(target)
upload_created_files(created)
