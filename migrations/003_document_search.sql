-- Apply after 002. Read-only function; no table/column/data changes.
begin;
create or replace function public.portal_search_document_requests(
 p_document_type_id uuid default null, p_search text default ''
) returns setof public.portal_document_requests
language sql stable security invoker set search_path='' as $$
 select r.* from public.portal_document_requests r
 where (p_document_type_id is null or exists (
   select 1 from public.portal_documents d where d.request_id=r.id
   and d.document_type_id=p_document_type_id
 )) and (
   coalesce(btrim(p_search),'')='' or
   strpos(lower(r.title),lower(btrim(p_search)))>0 or exists (
     select 1 from public.portal_documents d where d.request_id=r.id
     and (p_document_type_id is null or d.document_type_id=p_document_type_id)
     and strpos(lower(d.title),lower(btrim(p_search)))>0
   )
 );
$$;
revoke all on function public.portal_search_document_requests(uuid,text) from public,anon,authenticated;
grant execute on function public.portal_search_document_requests(uuid,text) to service_role;
notify pgrst,'reload schema';
commit;
