DECLARE @ID INT = 111304 -- 110692

select ID, SQ, DEL, DTS, GR, CT, NM
, *
from DOC 
where 1=1
and ct = 11
and id = @ID
-- and del = 0