-- Run in Supabase SQL Editor after 001-006. Standalone request/file store for the
-- mechanical workshop, independent from portal_documents but same request->file shape.
-- Access: admin (is_super_admin) or any MECHANICAL_* permission holder, for every action.
begin;

create table public.portal_service_requests (
 id uuid primary key default gen_random_uuid(),
 title text not null check(length(title) between 1 and 200),
 status text not null default 'draft' check(status in ('draft','archived')),
 created_by uuid not null references public.profiles(id), updated_by uuid not null references public.profiles(id),
 created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create table public.portal_service_files (
 id uuid primary key, request_id uuid not null references public.portal_service_requests,
 bucket text not null default 'portal_service_files' check(bucket='portal_service_files'),
 object_path text not null unique, original_name text not null,
 content_type text not null, size_bytes bigint not null check(size_bytes between 1 and 10485760),
 sha256 text not null check(sha256 ~ '^[0-9a-f]{64}$'),
 status text not null default 'uploading' check(status in ('uploading','ready','deleted')),
 created_by uuid not null references public.profiles(id),
 created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create index portal_service_requests_created on public.portal_service_requests(created_at desc,id);
create index portal_service_files_request on public.portal_service_files(request_id,created_at,id);

do $$ declare t text; begin
 foreach t in array array['portal_service_requests','portal_service_files'] loop
  execute format('alter table public.%I enable row level security',t);
  execute format('revoke all on public.%I from public,anon,authenticated',t);
  execute format('grant all on public.%I to service_role',t);
 end loop;
end $$;

-- Fail on a conflicting pre-existing bucket instead of altering another team's bucket.
insert into storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
 values ('portal_service_files','portal_service_files',false,10485760,
 array['image/jpeg','image/png','application/pdf',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  'text/plain']);
-- Restrictive policy prevents broad existing Storage policies granting direct access.
-- For every other bucket this predicate is true and does not change existing access.
create policy portal_service_files_backend_only on storage.objects as restrictive
 for all to anon,authenticated using(bucket_id <> 'portal_service_files') with check(bucket_id <> 'portal_service_files');

create function public.portal_service_files_write(p_actor_id uuid,p_action text,p_data jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare
 actor public.profiles%rowtype; req public.portal_service_requests%rowtype;
 f public.portal_service_files%rowtype; result jsonb;
begin
 perform pg_catalog.pg_advisory_xact_lock(748201633);
 if p_action not in ('create_request','update_request','reserve_file','complete_file','delete_file')
 then raise exception 'INVALID_INPUT'; end if;
 select * into actor from public.profiles where id=p_actor_id;
 if actor.id is null or actor."isActive" is not true or actor.is_first_login is not false
 or (actor.is_super_admin is not true and not exists(
  select 1 from public.user_permissions up join public.permissions p on p.id=up.permission_id
  where up.user_id=p_actor_id and p.permission_code=any(
   array['MECHANICAL_CREATE','MECHANICAL_UPDATE','MECHANICAL_REMOVE','MECHANICAL_VIEW'])))
 then raise exception 'FORBIDDEN'; end if;

 if p_action='create_request' then
  insert into public.portal_service_requests(title,created_by,updated_by)
   values(p_data->>'title',p_actor_id,p_actor_id) returning to_jsonb(portal_service_requests.*) into result;
  return result;
 end if;

 select * into req from public.portal_service_requests where id=(p_data->>'request_id')::uuid for update;
 if not found then raise exception 'REQUEST_NOT_FOUND'; end if;
 if p_action='update_request' then
  update public.portal_service_requests set title=coalesce(p_data->>'title',title),
   status=coalesce(p_data->>'status',status),updated_by=p_actor_id,updated_at=now()
   where id=req.id returning to_jsonb(portal_service_requests.*) into result;
  return result;
 end if;

 if p_action='reserve_file' then
  if req.status<>'draft' then raise exception 'REQUEST_ARCHIVED'; end if;
  select * into f from public.portal_service_files where id=(p_data->>'file_id')::uuid;
  if found then
   if f.request_id<>req.id or f.created_by<>p_actor_id or f.sha256<>p_data->>'sha256'
     or f.size_bytes<>(p_data->>'size_bytes')::bigint or f.original_name<>p_data->>'original_name'
     or f.content_type<>p_data->>'content_type'
   then raise exception 'IDEMPOTENCY_CONFLICT'; end if;
   if f.status='deleted' then raise exception 'FILE_DELETED'; end if;
   return to_jsonb(f);
  end if;
  if (select count(*) from public.portal_service_files where request_id=req.id and status<>'deleted')>=30
  then raise exception 'FILE_LIMIT'; end if;
  insert into public.portal_service_files(id,request_id,object_path,original_name,content_type,size_bytes,sha256,created_by)
  values((p_data->>'file_id')::uuid,req.id,req.id::text||'/'||(p_data->>'file_id'),
   p_data->>'original_name',p_data->>'content_type',(p_data->>'size_bytes')::bigint,p_data->>'sha256',p_actor_id)
  returning * into f;
  return to_jsonb(f);
 end if;

 select x.* into f from public.portal_service_files x where x.id=(p_data->>'file_id')::uuid and x.request_id=req.id for update;
 if not found then raise exception 'FILE_NOT_FOUND'; end if;
 if p_action='delete_file' then
  update public.portal_service_files set status='deleted',updated_at=now() where id=f.id
   returning to_jsonb(portal_service_files.*) into result;
  return result;
 end if;
 if f.status='deleted' then raise exception 'FILE_DELETED'; end if;
 if p_action='complete_file' then
  if f.created_by<>p_actor_id then raise exception 'FORBIDDEN'; end if;
  update public.portal_service_files set status='ready',updated_at=now() where id=f.id
   returning to_jsonb(portal_service_files.*) into result;
  return result;
 end if;
 raise exception 'INVALID_INPUT';
end $$;
revoke all on function public.portal_service_files_write(uuid,text,jsonb) from public,anon,authenticated;
grant execute on function public.portal_service_files_write(uuid,text,jsonb) to service_role;
notify pgrst,'reload schema';
commit;
