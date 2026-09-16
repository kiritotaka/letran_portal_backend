-- Add product permissions without changing existing permissions or assignments.
-- Safe to run again. Does not create product/import tables or APIs.
begin;
insert into public.permission_groups(group_name,description)
values ('PRODUCT','Qu?n l? s?n ph?m')
on conflict(group_name) do nothing;

insert into public.permissions(group_id,permission_code,permission_name)
select g.id,v.code,v.name
from public.permission_groups g
cross join (values
 ('PRODUCT_VIEW','Xem v? t?m ki?m s?n ph?m'),
 ('PRODUCT_CREATE','T?o s?n ph?m'),
 ('PRODUCT_UPDATE','C?p nh?t s?n ph?m'),
 ('PRODUCT_REMOVE','Ng?ng s? d?ng s?n ph?m'),
 ('PRODUCT_IMPORT','Upload v? ki?m tra d? li?u s?n ph?m'),
 ('PRODUCT_IMPORT_APPLY','X?c nh?n c?p nh?t s?n ph?m t? file import')
) as v(code,name)
where g.group_name='PRODUCT'
on conflict(permission_code) do nothing;
commit;
