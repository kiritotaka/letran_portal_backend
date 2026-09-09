begin;
create table public.portal_document_jobs (
 id uuid primary key, request_id uuid not null references public.portal_document_requests,
 created_by uuid not null references public.profiles,
 status text not null default 'queued' check(status in ('queued','processing','completed','failed')),
 stage text not null default 'queued', model text not null,
 schema_version text not null default 'acceptance-v1',
 source_snapshot jsonb not null, extracted_data jsonb,
 error_code text, lease_token uuid, lease_until timestamptz,
 created_at timestamptz not null default now(), started_at timestamptz, finished_at timestamptz
);
create unique index portal_one_active_job on public.portal_document_jobs(request_id) where status in ('queued','processing');
create index portal_job_queue on public.portal_document_jobs(status,created_at);
create index portal_job_request_history on public.portal_document_jobs(request_id,created_at desc,id);
alter table public.portal_document_jobs enable row level security;
revoke all on public.portal_document_jobs from public,anon,authenticated;
grant all on public.portal_document_jobs to service_role;

create function public.portal_enqueue_analysis(p_actor_id uuid,p_request_id uuid,p_job_id uuid,p_model text)
returns jsonb language plpgsql security definer set search_path='' as $$
declare actor public.profiles%rowtype; req public.portal_document_requests%rowtype;
 j public.portal_document_jobs%rowtype; snapshot jsonb; total_bytes bigint;
begin
 perform pg_catalog.pg_advisory_xact_lock(748201632);
 select * into actor from public.profiles where id=p_actor_id;
 if actor.id is null or actor."isActive" is not true or actor.is_first_login is not false or
 (actor.is_super_admin is not true and not exists(select 1 from public.user_permissions up
 join public.permissions p on p.id=up.permission_id where up.user_id=p_actor_id and p.permission_code='DOC_UPDATE'))
 then raise exception 'FORBIDDEN'; end if;
 select * into req from public.portal_document_requests where id=p_request_id;
 if not found then raise exception 'REQUEST_NOT_FOUND'; end if;
 select * into j from public.portal_document_jobs where id=p_job_id;
 if found then
  if j.request_id<>p_request_id or j.created_by<>p_actor_id then raise exception 'IDEMPOTENCY_CONFLICT'; end if;
  return to_jsonb(j);
 end if;
 if req.status<>'draft' then raise exception 'REQUEST_ARCHIVED'; end if;
 if not exists(select 1 from public.portal_document_tasks where id=req.task_id and code='ACCEPTANCE_REPORT')
 then raise exception 'UNSUPPORTED_TASK'; end if;
 select * into j from public.portal_document_jobs where request_id=p_request_id and status in ('queued','processing');
 if found then return to_jsonb(j); end if;
 if exists(select 1 from public.portal_document_request_files l join public.portal_files f on f.id=l.file_id
  where l.request_id=p_request_id and f.status='uploading') then raise exception 'UPLOADS_PENDING'; end if;
 select jsonb_agg(jsonb_build_object('file_id',f.id,'bucket',f.bucket,'object_path',f.object_path,
   'sha256',f.sha256,'size_bytes',f.size_bytes,'content_type',f.content_type,'original_name',f.original_name,
   'document_id',d.id,'document_title',d.title,'document_type',t.code,'sort_order',l.sort_order)
   order by d.id,l.sort_order,f.id),sum(f.size_bytes) into snapshot,total_bytes
 from public.portal_document_request_files l join public.portal_files f on f.id=l.file_id
 join public.portal_documents d on d.id=l.document_id join public.portal_document_types t on t.id=d.document_type_id
 where l.request_id=p_request_id and f.status='ready';
 if snapshot is null then raise exception 'NO_SOURCE_FILES'; end if;
 if total_bytes>12582912 then raise exception 'ANALYSIS_INPUT_TOO_LARGE'; end if;
 insert into public.portal_document_jobs(id,request_id,created_by,model,source_snapshot)
 values(p_job_id,p_request_id,p_actor_id,p_model,snapshot) returning * into j;
 return to_jsonb(j);
end $$;

create function public.portal_claim_analysis() returns jsonb
language plpgsql security definer set search_path='' as $$
declare j public.portal_document_jobs%rowtype;
begin
 -- A crashed worker may already have called Gemini. Never auto-retry paid calls.
 update public.portal_document_jobs set status='failed',stage='failed',error_code='WORKER_INTERRUPTED',finished_at=now()
 where status='processing' and lease_until<now();
 update public.portal_document_jobs pending set status='failed',stage='failed',error_code='ACTOR_UNAVAILABLE',finished_at=now()
 where pending.status='queued' and not exists(select 1 from public.profiles pr where pr.id=pending.created_by
 and pr."isActive" is true and pr.is_first_login is false and (pr.is_super_admin is true or exists(
 select 1 from public.user_permissions up join public.permissions p on p.id=up.permission_id
 where up.user_id=pr.id and p.permission_code='DOC_UPDATE')));
 select * into j from public.portal_document_jobs where status='queued' order by created_at,id for update skip locked limit 1;
 if not found then return null; end if;
 update public.portal_document_jobs set status='processing',stage='reading_sources',started_at=now(),
 lease_token=gen_random_uuid(),lease_until=now()+interval '15 minutes' where id=j.id returning * into j;
 return to_jsonb(j);
end $$;

create function public.portal_finish_analysis(p_job_id uuid,p_lease_token uuid,p_result jsonb default null,p_error text default null)
returns boolean language plpgsql security definer set search_path='' as $$
begin
 update public.portal_document_jobs set status=case when p_error is null then 'completed' else 'failed' end,
 stage=case when p_error is null then 'completed' else 'failed' end,
 extracted_data=case when p_error is null then p_result else null end,error_code=p_error,finished_at=now()
 where id=p_job_id and status='processing' and lease_token=p_lease_token and lease_until>now();
 return found;
end $$;
revoke all on function public.portal_enqueue_analysis(uuid,uuid,uuid,text) from public,anon,authenticated;
revoke all on function public.portal_claim_analysis() from public,anon,authenticated;
revoke all on function public.portal_finish_analysis(uuid,uuid,jsonb,text) from public,anon,authenticated;
grant execute on function public.portal_enqueue_analysis(uuid,uuid,uuid,text) to service_role;
grant execute on function public.portal_claim_analysis() to service_role;
grant execute on function public.portal_finish_analysis(uuid,uuid,jsonb,text) to service_role;
notify pgrst,'reload schema';
commit;
