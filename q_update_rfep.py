update_rfep_lac_record = """
UPDATE lac
set RD1 = '{rfep_date}'
, pr = ''
, ld = ''
, ece = ''
, li = ''
, sr = ''
, lt = ''
, ed = '{lac_end_date}'
, co = N'{appended_comment}'
where id = '{stu_id}'
"""

get_lac_commnet = """
select co
from lac
where id = '{stu_id}'
"""

update_rfep_stu_record = """
update stu
set lf = '{lf_level}'
where id = '{stu_id}'
"""

rfep_check = """
select id,lf
from stu
where id = '{stu_id}'
and lf = '4'
"""
get_lip_pgm_commnet = """
select co
from pgm
where pid = '{stu_id}'
and CD in ('301','305','306')
and eed is null
"""

lip_check = """
select *
from pgm
where 1=1
and EED is null
and CD in ('301','305','306')
and pid = '{stu_id}'
"""

close_lip = """
update pgm 
set eed = '{end_date}',
co = N'{new_comment}'
where CD in ('301','305','306')
and pid = '{stu_id}'
"""

attendance_check = """
select *
from stu
where 1=1
and stu.id = {stu_id}
and stu.del = 0
and stu.tg = ''
"""