-- Run in Supabase SQL Editor. Only new portal_* objects and an isolated bucket.
-- Never run tests/* SQL on the real project.
begin;
create table public.portal_document_tasks (
 id uuid primary key default gen_random_uuid(), code text not null unique,
 name text not null, is_active boolean not null default true
);
create table public.portal_document_types (
 id uuid primary key default gen_random_uuid(), code text not null unique,
 name text not null, is_active boolean not null default true
);
create table public.portal_document_templates (
 id uuid primary key default gen_random_uuid(), task_id uuid not null references public.portal_document_tasks,
 name text not null, version integer not null check(version>0),
 output_format text not null check(output_format in ('docx','xlsx','pdf')),
 bucket text, object_path text, is_active boolean not null default false,
 unique(task_id,version), check(not is_active or (bucket is not null and object_path is not null))
);
create unique index portal_one_active_template on public.portal_document_templates(task_id) where is_active;
create table public.portal_document_requests (
 id uuid primary key default gen_random_uuid(), task_id uuid not null references public.portal_document_tasks,
 template_id uuid references public.portal_document_templates,
 title text not null check(length(title) between 1 and 200),
 status text not null default 'draft' check(status in ('draft','archived')),
 created_by uuid not null references public.profiles(id), updated_by uuid not null references public.profiles(id),
 created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create table public.portal_documents (
 id uuid primary key default gen_random_uuid(), request_id uuid not null references public.portal_document_requests,
 document_type_id uuid not null references public.portal_document_types,
 title text not null check(length(title) between 1 and 200),
 created_by uuid not null references public.profiles(id), created_at timestamptz not null default now(),
 unique(id,request_id)
);
create table public.portal_files (
 id uuid primary key, bucket text not null default 'portal_documents' check(bucket='portal_documents'),
 object_path text not null unique, original_name text not null,
 content_type text not null, size_bytes bigint not null check(size_bytes between 1 and 10485760),
 sha256 text not null check(sha256 ~ '^[0-9a-f]{64}$'),
 status text not null default 'uploading' check(status in ('uploading','ready','deleted')),
 created_by uuid not null references public.profiles(id),
 created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create table public.portal_document_request_files (
 file_id uuid primary key references public.portal_files,
 request_id uuid not null references public.portal_document_requests,
 document_id uuid not null,
 sort_order integer not null check(sort_order between 1 and 10000),
 foreign key(document_id,request_id) references public.portal_documents(id,request_id)
);
create index portal_requests_created on public.portal_document_requests(created_at desc,id);
create index portal_documents_request on public.portal_documents(request_id,created_at,id);
create index portal_request_files_order on public.portal_document_request_files(request_id,document_id,sort_order,file_id);

-- Existing shared profiles/permission tables are read, never altered.
do $$ declare t text; begin
 foreach t in array array['portal_document_tasks','portal_document_types','portal_document_templates',
   'portal_document_requests','portal_documents','portal_files','portal_document_request_files'] loop
  execute format('alter table public.%I enable row level security',t);
  execute format('revoke all on public.%I from public,anon,authenticated',t);
  execute format('grant all on public.%I to service_role',t);
 end loop;
end $$;

insert into public.portal_document_tasks(code,name) values ('ACCEPTANCE_REPORT','Lập biên bản nghiệm thu');
insert into public.portal_document_types(code,name) values
 ('ECONOMIC_CONTRACT','Hợp đồng kinh tế'),('INVOICE','Hóa đơn'),('PAYMENT_PROOF','Chứng từ thanh toán');
insert into public.portal_document_templates(task_id,name,version,output_format)
 select id,'Biên bản nghiệm thu và thanh lý hợp đồng dịch vụ',1,'docx'
 from public.portal_document_tasks where code='ACCEPTANCE_REPORT';

-- Fail on a conflicting pre-existing bucket instead of altering another team's bucket.
insert into storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
 values ('portal_documents','portal_documents',false,10485760,
 array['image/jpeg','image/png','application/pdf','application/vnd.openxmlformats-officedocument.wordprocessingml.document']);
-- Restrictive policy prevents broad existing Storage policies granting direct access.
-- For every other bucket this predicate is true and does not change existing access.
create policy portal_documents_backend_only on storage.objects as restrictive
 for all to anon,authenticated using(bucket_id <> 'portal_documents') with check(bucket_id <> 'portal_documents');

create function public.portal_documents_write(p_actor_id uuid,p_action text,p_data jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare
 required_code text; actor public.profiles%rowtype; req public.portal_document_requests%rowtype;
 doc public.portal_documents%rowtype; f public.portal_files%rowtype;
 link public.portal_document_request_files%rowtype; result jsonb; target_id uuid;
begin
 perform pg_catalog.pg_advisory_xact_lock(748201632);
 select * into actor from public.profiles where id=p_actor_id;
 required_code := case when p_action in ('create_request','create_document','reserve_file','complete_file') then 'DOC_CREATE'
  when p_action in ('update_request','reorder_file') then 'DOC_UPDATE'
  when p_action='delete_file' then 'DOC_REMOVE' else null end;
 if required_code is null then raise exception 'INVALID_INPUT'; end if;
 if actor.id is null or actor."isActive" is not true or actor.is_first_login is not false
 or (actor.is_super_admin is not true and not exists(
  select 1 from public.user_permissions up join public.permissions p on p.id=up.permission_id
  where up.user_id=p_actor_id and p.permission_code=required_code))
 then raise exception 'FORBIDDEN'; end if;

 if p_action='create_request' then
  if not exists(select 1 from public.portal_document_tasks where id=(p_data->>'task_id')::uuid and is_active)
  then raise exception 'CATALOG_NOT_FOUND'; end if;
  insert into public.portal_document_requests(task_id,template_id,title,created_by,updated_by)
   values((p_data->>'task_id')::uuid,
    (select id from public.portal_document_templates where task_id=(p_data->>'task_id')::uuid and is_active),
    p_data->>'title',p_actor_id,p_actor_id) returning to_jsonb(portal_document_requests.*) into result;
  return result;
 end if;
 select * into req from public.portal_document_requests where id=(p_data->>'request_id')::uuid for update;
 if not found then raise exception 'REQUEST_NOT_FOUND'; end if;
 if p_action='update_request' then
  update public.portal_document_requests set title=coalesce(p_data->>'title',title),
   status=coalesce(p_data->>'status',status),updated_by=p_actor_id,updated_at=now()
   where id=req.id returning to_jsonb(portal_document_requests.*) into result;
  return result;
 end if;
 if req.status<>'draft' then raise exception 'REQUEST_ARCHIVED'; end if;
 if p_action='create_document' then
  if not exists(select 1 from public.portal_document_types where id=(p_data->>'document_type_id')::uuid and is_active)
  then raise exception 'CATALOG_NOT_FOUND'; end if;
  if (select count(*) from public.portal_documents where request_id=req.id)>=30 then raise exception 'DOCUMENT_LIMIT'; end if;
  insert into public.portal_documents(request_id,document_type_id,title,created_by)
   values(req.id,(p_data->>'document_type_id')::uuid,p_data->>'title',p_actor_id)
   returning to_jsonb(portal_documents.*) into result;
  return result;
 end if;
 if p_action='reserve_file' then
  select * into doc from public.portal_documents where id=(p_data->>'document_id')::uuid and request_id=req.id;
  if not found then raise exception 'DOCUMENT_NOT_FOUND'; end if;
  select * into f from public.portal_files where id=(p_data->>'file_id')::uuid;
  if found then
   select * into link from public.portal_document_request_files where file_id=f.id;
   if link.request_id<>req.id or link.document_id<>doc.id or f.created_by<>p_actor_id
     or f.sha256<>p_data->>'sha256' or f.size_bytes<>(p_data->>'size_bytes')::bigint
     or f.original_name<>p_data->>'original_name' or f.content_type<>p_data->>'content_type'
   then raise exception 'IDEMPOTENCY_CONFLICT'; end if;
   if f.status='deleted' then raise exception 'FILE_DELETED'; end if;
   return to_jsonb(f);
  end if;
  if (select count(*) from public.portal_document_request_files l join public.portal_files x on x.id=l.file_id
      where l.request_id=req.id and x.status<>'deleted')>=30 then raise exception 'FILE_LIMIT'; end if;
  insert into public.portal_files(id,object_path,original_name,content_type,size_bytes,sha256,created_by)
  values((p_data->>'file_id')::uuid,req.id::text||'/'||doc.id::text||'/'||(p_data->>'file_id'),
   p_data->>'original_name',p_data->>'content_type',(p_data->>'size_bytes')::bigint,p_data->>'sha256',p_actor_id)
  returning * into f;
  insert into public.portal_document_request_files(file_id,request_id,document_id,sort_order)
   values(f.id,req.id,doc.id,(p_data->>'sort_order')::integer);
  return to_jsonb(f);
 end if;
 select x.* into f from public.portal_files x join public.portal_document_request_files l on l.file_id=x.id
  where x.id=(p_data->>'file_id')::uuid and l.request_id=req.id for update of x;
 if not found then raise exception 'FILE_NOT_FOUND'; end if;
 if p_action='delete_file' then
  update public.portal_files set status='deleted',updated_at=now() where id=f.id returning to_jsonb(portal_files.*) into result;
  return result;
 end if;
 if f.status='deleted' then raise exception 'FILE_DELETED'; end if;
 if p_action='complete_file' then
  if f.created_by<>p_actor_id then raise exception 'FORBIDDEN'; end if;
  update public.portal_files set status='ready',updated_at=now() where id=f.id returning to_jsonb(portal_files.*) into result;
  return result;
 end if;
 if p_action='reorder_file' then
  update public.portal_document_request_files set sort_order=(p_data->>'sort_order')::integer
   where file_id=f.id returning to_jsonb(portal_document_request_files.*) into result;
  return result;
 end if;
 raise exception 'INVALID_INPUT';
end $$;
revoke all on function public.portal_documents_write(uuid,text,jsonb) from public,anon,authenticated;
grant execute on function public.portal_documents_write(uuid,text,jsonb) to service_role;
notify pgrst,'reload schema';
commit;
