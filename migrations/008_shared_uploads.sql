-- New isolated upload module. Run once; does not alter existing document uploads.
begin;
create table public.portal_uploaded_files (
 id uuid primary key,
 purpose text not null check(purpose in ('product_import')),
 bucket text not null default 'portal_uploads' check(bucket='portal_uploads'),
 object_path text not null unique,
 original_name text not null check(length(original_name) between 1 and 255),
 content_type text not null check(content_type in ('text/csv','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')),
 size_bytes bigint not null check(size_bytes between 1 and 10485760),
 sha256 text not null check(sha256 ~ '^[0-9a-f]{64}$'),
 status text not null default 'uploading' check(status in ('uploading','ready','deleted')),
 created_by uuid not null references public.profiles(id),
 created_at timestamptz not null default now(),
 updated_at timestamptz not null default now()
);
create index portal_uploaded_files_owner on public.portal_uploaded_files(created_by,created_at desc,id);
alter table public.portal_uploaded_files enable row level security;
revoke all on public.portal_uploaded_files from public,anon,authenticated;
grant select,insert,update on public.portal_uploaded_files to service_role;
insert into storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
values('portal_uploads','portal_uploads',false,10485760,array[
 'text/csv','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet']);
create policy portal_uploads_backend_only on storage.objects as restrictive
for all to anon,authenticated using(bucket_id<>'portal_uploads') with check(bucket_id<>'portal_uploads');

create function public.portal_uploaded_file_action(p_actor_id uuid,p_action text,p_file_id uuid,p_data jsonb default '{}'::jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare actor public.profiles%rowtype; f public.portal_uploaded_files%rowtype;
begin
 if p_action not in ('reserve','complete','get','delete') or p_file_id is null then raise exception 'INVALID_INPUT'; end if;
 select * into actor from public.profiles where id=p_actor_id;
 if actor.id is null or actor."isActive" is not true or actor.is_first_login is not false
 or (actor.is_super_admin is not true and not exists(
 select 1 from public.user_permissions up join public.permissions p on p.id=up.permission_id
 where up.user_id=p_actor_id and p.permission_code='PRODUCT_IMPORT'))
 then raise exception 'FORBIDDEN'; end if;
 perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(p_file_id::text, 0));
 select * into f from public.portal_uploaded_files where id=p_file_id for update;
 if p_action='reserve' then
  if p_data->>'purpose' is distinct from 'product_import' then raise exception 'INVALID_INPUT'; end if;
  if f.id is not null then
   if f.created_by<>p_actor_id or f.purpose is distinct from p_data->>'purpose'
   or f.original_name is distinct from p_data->>'original_name' or f.content_type is distinct from p_data->>'content_type'
   or f.sha256 is distinct from p_data->>'sha256' or f.size_bytes is distinct from (p_data->>'size_bytes')::bigint
   then raise exception 'IDEMPOTENCY_CONFLICT'; end if;
   if f.status='deleted' then raise exception 'FILE_DELETED'; end if;
   return to_jsonb(f);
  end if;
  insert into public.portal_uploaded_files(id,purpose,object_path,original_name,content_type,size_bytes,sha256,created_by)
  values(p_file_id,p_data->>'purpose',p_actor_id::text||'/'||p_file_id::text,p_data->>'original_name',
    p_data->>'content_type',(p_data->>'size_bytes')::bigint,p_data->>'sha256',p_actor_id) returning * into f;
  return to_jsonb(f);
 end if;
 if f.id is null or (f.created_by<>p_actor_id and actor.is_super_admin is not true)
 then raise exception 'FILE_NOT_FOUND'; end if;
 if p_action='get' then return to_jsonb(f); end if;
 if p_action='delete' then
  update public.portal_uploaded_files set status='deleted',updated_at=now() where id=f.id returning * into f;
 else
  if f.created_by<>p_actor_id then raise exception 'FORBIDDEN'; end if;
  if f.status='deleted' then raise exception 'FILE_DELETED'; end if;
  update public.portal_uploaded_files set status='ready',updated_at=now() where id=f.id returning * into f;
 end if;
 return to_jsonb(f);
end $$;
revoke all on function public.portal_uploaded_file_action(uuid,text,uuid,jsonb) from public,anon,authenticated;
grant execute on function public.portal_uploaded_file_action(uuid,text,uuid,jsonb) to service_role;
notify pgrst,'reload schema';
commit;
