-- Run after 007 and 008. Preview only: never writes portal_products.
begin;
create table public.portal_product_imports (
 id uuid primary key,
 file_id uuid not null references public.portal_uploaded_files(id),
 sheet_name text check(length(sheet_name) between 1 and 31),
 status text not null default 'queued' check(status in ('queued','processing','preview_ready','failed')),
 attempts integer not null default 0,
 lease_token uuid,
 lease_until timestamptz,
 summary jsonb not null default '{}',
 error_code text,
 created_by uuid not null references public.profiles(id),
 created_at timestamptz not null default now(),
 updated_at timestamptz not null default now(),
 finished_at timestamptz
);
create index portal_product_imports_queue on public.portal_product_imports(status,created_at);
create index portal_product_imports_file on public.portal_product_imports(file_id);
create table public.portal_product_import_rows (
 job_id uuid not null references public.portal_product_imports(id),
 row_number integer not null,
 source_row integer not null,
 product_code text not null,
 product_name text not null,
 occurrences integer not null,
 action text not null check(action in ('create','update','unchanged','error')),
 error_code text,
 existing jsonb,
 primary key(job_id,row_number)
);
create index portal_product_import_rows_action on public.portal_product_import_rows(job_id,action,row_number);
alter table public.portal_product_imports enable row level security;
alter table public.portal_product_import_rows enable row level security;
revoke all on public.portal_product_imports,public.portal_product_import_rows from public,anon,authenticated;
grant select on public.portal_product_imports,public.portal_product_import_rows to service_role;

create function public.portal_product_import_allowed(p_actor_id uuid) returns boolean
language sql stable security definer set search_path='' as $$
 select exists(select 1 from public.profiles a where a.id=p_actor_id and a."isActive" is true
 and a.is_first_login is false and (a.is_super_admin is true or exists(
 select 1 from public.user_permissions up join public.permissions p on p.id=up.permission_id
 where up.user_id=a.id and p.permission_code='PRODUCT_IMPORT')));
$$;

-- The same file row lock used by upload/delete serializes attachment and deletion.
create function public.portal_product_import_protect_file() returns trigger
language plpgsql security definer set search_path='' as $$
begin
 if new.status='deleted' and old.status<>'deleted' and exists(
 select 1 from public.portal_product_imports where file_id=old.id and status in ('queued','processing','preview_ready'))
 then raise exception 'FILE_IN_USE'; end if;
 return new;
end $$;
create trigger portal_product_import_file_guard before update on public.portal_uploaded_files
 for each row execute function public.portal_product_import_protect_file();

create function public.portal_product_import_action(p_actor_id uuid,p_action text,p_job_id uuid,p_data jsonb default '{}')
returns jsonb language plpgsql security definer set search_path='' as $$
declare j public.portal_product_imports%rowtype; f public.portal_uploaded_files%rowtype;
 admin boolean; pg integer; sz integer; total bigint; items jsonb; filter_action text;
begin
 if not public.portal_product_import_allowed(p_actor_id) then raise exception 'FORBIDDEN'; end if;
 select is_super_admin is true into admin from public.profiles where id=p_actor_id;
 if p_action not in ('create','get','rows') or p_job_id is null then raise exception 'INVALID_INPUT'; end if;
 if p_action='create' then
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('product-import-actor:'||p_actor_id::text,0));
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('product-import:'||p_job_id::text,0));
 end if;
 select * into j from public.portal_product_imports where id=p_job_id;
 if p_action='create' then
  if j.id is not null then
   if j.created_by<>p_actor_id or j.file_id is distinct from (p_data->>'file_id')::uuid
   or j.sheet_name is distinct from p_data->>'sheet_name' then raise exception 'IDEMPOTENCY_CONFLICT'; end if;
  else
   select * into f from public.portal_uploaded_files where id=(p_data->>'file_id')::uuid for update;
   if f.id is null or (f.created_by<>p_actor_id and not admin) then raise exception 'FILE_NOT_FOUND'; end if;
   if f.status<>'ready' or f.purpose<>'product_import' then raise exception 'FILE_NOT_READY'; end if;
   if (select count(*) from public.portal_product_imports where created_by=p_actor_id and status in ('queued','processing'))>=3
   then raise exception 'IMPORT_QUEUE_FULL'; end if;
   insert into public.portal_product_imports(id,file_id,sheet_name,created_by)
   values(p_job_id,f.id,p_data->>'sheet_name',p_actor_id) returning * into j;
  end if;
 elsif j.id is null or (j.created_by<>p_actor_id and not admin) then raise exception 'IMPORT_NOT_FOUND';
 end if;
 if p_action<>'rows' then return to_jsonb(j)-'lease_token'-'lease_until'; end if;
 if j.status<>'preview_ready' then raise exception 'IMPORT_NOT_READY'; end if;
 pg=coalesce((p_data->>'page')::integer,1); sz=coalesce((p_data->>'page_size')::integer,20);
 filter_action=p_data->>'action';
 if pg<1 or pg>1000000 or sz<1 or sz>100 or (filter_action is not null and filter_action not in ('create','update','unchanged','error'))
 then raise exception 'INVALID_INPUT'; end if;
 select count(*) into total from public.portal_product_import_rows where job_id=j.id and (filter_action is null or action=filter_action);
 select coalesce(jsonb_agg(to_jsonb(r)-'job_id' order by r.row_number),'[]') into items from (
 select * from public.portal_product_import_rows where job_id=j.id and (filter_action is null or action=filter_action)
 order by row_number limit sz offset (pg-1)*sz) r;
 return jsonb_build_object('items',items,'pagination',jsonb_build_object('page',pg,'page_size',sz,'total',total,
 'total_pages',(total+sz-1)/sz,'has_next',pg::bigint*sz<total,'has_previous',pg>1));
end $$;

create function public.portal_product_import_worker(p_action text,p_job_id uuid default null,p_token uuid default null,p_data jsonb default '{}')
returns jsonb language plpgsql security definer set search_path='' as $$
declare j public.portal_product_imports%rowtype; f public.portal_uploaded_files%rowtype; counts jsonb;
begin
 if p_action='claim' then
  update public.portal_product_imports set status='failed',error_code='IMPORT_RETRY_EXHAUSTED',finished_at=now(),updated_at=now(),lease_token=null,lease_until=null
  where status='processing' and lease_until<now() and attempts>=3;
  select * into j from public.portal_product_imports
  where status='queued' or (status='processing' and lease_until<now() and attempts<3)
  order by created_at,id for update skip locked limit 1;
  if j.id is null then return null; end if;
  update public.portal_product_imports set status='processing',attempts=attempts+1,
   lease_token=gen_random_uuid(),lease_until=now()+interval '3 minutes',updated_at=now()
   where id=j.id returning * into j;
 else
  select * into j from public.portal_product_imports where id=p_job_id for update;
  if j.id is null or j.status<>'processing' or j.lease_token is distinct from p_token or j.lease_until<now()
  then raise exception 'IMPORT_LEASE_LOST'; end if;
 end if;
 select * into f from public.portal_uploaded_files where id=j.file_id;
 if not public.portal_product_import_allowed(j.created_by) or f.status<>'ready' then
  update public.portal_product_imports set status='failed',error_code='IMPORT_ACCESS_REVOKED',finished_at=now(),updated_at=now(),lease_token=null,lease_until=null where id=j.id;
  return null;
 end if;
 if p_action='claim' then return to_jsonb(j)||jsonb_build_object('source',to_jsonb(f)); end if;
 if p_action='heartbeat' then
  update public.portal_product_imports set lease_until=now()+interval '3 minutes',updated_at=now() where id=j.id;
 elsif p_action='fail' then
  update public.portal_product_imports set status='failed',error_code=left(coalesce(p_data->>'error_code','IMPORT_FAILED'),100),finished_at=now(),updated_at=now(),lease_token=null,lease_until=null where id=j.id;
 elsif p_action='finish' then
  if jsonb_typeof(p_data->'rows') is distinct from 'array' or jsonb_array_length(p_data->'rows') not between 1 and 10000
  then raise exception 'INVALID_INPUT'; end if;
  -- Single INSERT statement observes one catalog snapshot, not separate HTTP pages.
  insert into public.portal_product_import_rows(job_id,row_number,source_row,product_code,product_name,occurrences,action,error_code,existing)
  select j.id,r.n::integer,(r.v->>'source_row')::integer,r.v->>'product_code',r.v->>'product_name',
   coalesce((r.v->>'occurrences')::integer,1),
   case when r.v->>'error_code' is not null then 'error' when p.id is null then 'create'
        when p.product_name is distinct from r.v->>'product_name' then 'update' else 'unchanged' end,
   r.v->>'error_code',case when p.id is null then null else jsonb_build_object('id',p.id,'product_name',p.product_name,'is_active',p.is_active,'updated_at',p.updated_at) end
  from jsonb_array_elements(p_data->'rows') with ordinality r(v,n)
  left join public.portal_products p on p.product_code=r.v->>'product_code';
  select jsonb_build_object('create',count(*) filter(where action='create'),'update',count(*) filter(where action='update'),
   'unchanged',count(*) filter(where action='unchanged'),'error',count(*) filter(where action='error'),
   'total',count(*),'has_errors',count(*) filter(where action='error')>0) into counts
   from public.portal_product_import_rows where job_id=j.id;
  update public.portal_product_imports set status='preview_ready',summary=coalesce(p_data->'summary','{}')||counts,
   finished_at=now(),updated_at=now(),lease_token=null,lease_until=null where id=j.id;
 else raise exception 'INVALID_INPUT'; end if;
 return jsonb_build_object('ok',true);
end $$;
revoke all on function public.portal_product_import_allowed(uuid),public.portal_product_import_protect_file(),
 public.portal_product_import_action(uuid,text,uuid,jsonb),public.portal_product_import_worker(text,uuid,uuid,jsonb) from public,anon,authenticated;
grant execute on function public.portal_product_import_action(uuid,text,uuid,jsonb),public.portal_product_import_worker(text,uuid,uuid,jsonb) to service_role;
notify pgrst,'reload schema';
commit;
