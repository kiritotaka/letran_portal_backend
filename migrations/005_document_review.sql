begin;
create table public.portal_document_reviews (
 id uuid primary key,
 request_id uuid not null references public.portal_document_requests,
 analysis_job_id uuid not null references public.portal_document_jobs,
 revision integer not null check (revision>0),
 confirmed boolean not null,
 fields jsonb not null check(jsonb_typeof(fields)='array' and jsonb_array_length(fields)=24),
 template_id uuid not null references public.portal_document_templates,
 template_path text not null,
 created_by uuid not null references public.profiles,
 created_at timestamptz not null default now(),
 original_payload jsonb not null,
 unique(request_id,revision)
);
create table public.portal_document_exports (
 review_id uuid primary key references public.portal_document_reviews,
 object_path text not null,
 sha256 text not null check(sha256 ~ '^[0-9a-f]{64}$'),
 created_by uuid not null references public.profiles,
 created_at timestamptz not null default now()
);
alter table public.portal_document_reviews enable row level security;
alter table public.portal_document_exports enable row level security;
revoke all on public.portal_document_reviews,public.portal_document_exports from public,anon,authenticated;
grant select,insert on public.portal_document_reviews,public.portal_document_exports to service_role;

create function public.portal_save_document_review(p_actor_id uuid,p_request_id uuid,p_id uuid,p_payload jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare actor public.profiles%rowtype; req public.portal_document_requests%rowtype;
 saved public.portal_document_reviews%rowtype; tpl public.portal_document_templates%rowtype;
 current_revision integer;
begin
 perform pg_catalog.pg_advisory_xact_lock(748201632);
 select * into actor from public.profiles where id=p_actor_id;
 if actor.id is null or actor."isActive" is not true or actor.is_first_login is not false or
 (actor.is_super_admin is not true and not exists(select 1 from public.user_permissions up
 join public.permissions p on p.id=up.permission_id where up.user_id=p_actor_id and p.permission_code='DOC_UPDATE'))
 then raise exception 'FORBIDDEN'; end if;
 select * into req from public.portal_document_requests where id=p_request_id;
 if not found then raise exception 'REQUEST_NOT_FOUND'; end if;
 select * into saved from public.portal_document_reviews where id=p_id;
 if found then
  if saved.request_id<>p_request_id or saved.created_by<>p_actor_id or saved.original_payload<>p_payload
  then raise exception 'IDEMPOTENCY_CONFLICT'; end if;
  return to_jsonb(saved);
 end if;
 if req.status<>'draft' then raise exception 'REQUEST_ARCHIVED'; end if;
 select coalesce(max(revision),0) into current_revision from public.portal_document_reviews where request_id=p_request_id;
 if current_revision<>(p_payload->>'expected_revision')::integer then raise exception 'REVISION_CONFLICT'; end if;
 if not exists(select 1 from public.portal_document_jobs where id=(p_payload->>'analysis_job_id')::uuid
  and request_id=p_request_id and status='completed' and schema_version='acceptance-v1')
 then raise exception 'JOB_NOT_READY'; end if;
 select * into tpl from public.portal_document_templates where id=req.template_id;
 if not found or tpl.object_path is null or tpl.bucket<>'portal_documents' or tpl.output_format<>'docx'
 or tpl.object_path not like 'templates/%' then raise exception 'TEMPLATE_NOT_ASSIGNED'; end if;
 if jsonb_typeof(p_payload->'fields') is distinct from 'array' or jsonb_typeof(p_payload->'confirmed') is distinct from 'boolean'
 then raise exception 'INVALID_INPUT'; end if;
 insert into public.portal_document_reviews(id,request_id,analysis_job_id,revision,confirmed,fields,
 template_id,template_path,created_by,original_payload) values(p_id,p_request_id,(p_payload->>'analysis_job_id')::uuid,
 current_revision+1,(p_payload->>'confirmed')::boolean,p_payload->'fields',tpl.id,tpl.object_path,p_actor_id,p_payload)
 returning * into saved;
 return to_jsonb(saved);
end $$;

create function public.portal_record_document_export(p_actor_id uuid,p_review_id uuid,p_path text,p_sha256 text)
returns jsonb language plpgsql security definer set search_path='' as $$
declare actor public.profiles%rowtype; saved public.portal_document_reviews%rowtype;
 exported public.portal_document_exports%rowtype;
begin
 perform pg_catalog.pg_advisory_xact_lock(748201632);
 select * into actor from public.profiles where id=p_actor_id;
 if actor.id is null or actor."isActive" is not true or actor.is_first_login is not false or
 (actor.is_super_admin is not true and not exists(select 1 from public.user_permissions up
 join public.permissions p on p.id=up.permission_id where up.user_id=p_actor_id and p.permission_code='DOC_UPDATE'))
 then raise exception 'FORBIDDEN'; end if;
 select * into saved from public.portal_document_reviews where id=p_review_id;
 if not found then raise exception 'REVIEW_NOT_FOUND'; end if;
 if not saved.confirmed then raise exception 'REVIEW_NOT_CONFIRMED'; end if;
 if not exists(select 1 from public.portal_document_requests where id=saved.request_id and status='draft')
 then raise exception 'REQUEST_ARCHIVED'; end if;
 if p_sha256 !~ '^[0-9a-f]{64}$' or p_path is distinct from
 'exports/'||saved.request_id::text||'/'||saved.id::text||'/'||p_sha256||'.docx'
 then raise exception 'INVALID_INPUT'; end if;
 insert into public.portal_document_exports(review_id,object_path,sha256,created_by)
 values(p_review_id,p_path,p_sha256,p_actor_id) on conflict(review_id) do nothing;
 select * into exported from public.portal_document_exports where review_id=p_review_id;
 return to_jsonb(exported);
end $$;
revoke all on function public.portal_save_document_review(uuid,uuid,uuid,jsonb) from public,anon,authenticated;
revoke all on function public.portal_record_document_export(uuid,uuid,text,text) from public,anon,authenticated;
grant execute on function public.portal_save_document_review(uuid,uuid,uuid,jsonb) to service_role;
grant execute on function public.portal_record_document_export(uuid,uuid,text,text) to service_role;
notify pgrst,'reload schema';
commit;
