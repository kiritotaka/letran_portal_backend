-- Run in Supabase SQL Editor after 001-005. Allows MECHANICAL_* permission
-- holders to upload files (reserve_file/complete_file), and allows .xlsx uploads.
begin;

update storage.buckets
 set allowed_mime_types = array(select distinct unnest(allowed_mime_types || array[
   'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet']))
 where id = 'portal_documents';

create or replace function public.portal_documents_write(p_actor_id uuid,p_action text,p_data jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare
 required_codes text[]; actor public.profiles%rowtype; req public.portal_document_requests%rowtype;
 doc public.portal_documents%rowtype; f public.portal_files%rowtype;
 link public.portal_document_request_files%rowtype; result jsonb; target_id uuid;
begin
 perform pg_catalog.pg_advisory_xact_lock(748201632);
 select * into actor from public.profiles where id=p_actor_id;
 required_codes := case
  when p_action in ('create_request','create_document') then array['DOC_CREATE']
  when p_action in ('reserve_file','complete_file') then
   array['DOC_CREATE','MECHANICAL_CREATE','MECHANICAL_UPDATE','MECHANICAL_REMOVE','MECHANICAL_VIEW']
  when p_action in ('update_request','reorder_file') then array['DOC_UPDATE']
  when p_action='delete_file' then array['DOC_REMOVE'] else null end;
 if required_codes is null then raise exception 'INVALID_INPUT'; end if;
 if actor.id is null or actor."isActive" is not true or actor.is_first_login is not false
 or (actor.is_super_admin is not true and not exists(
  select 1 from public.user_permissions up join public.permissions p on p.id=up.permission_id
  where up.user_id=p_actor_id and p.permission_code=any(required_codes)))
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
