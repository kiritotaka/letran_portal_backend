-- Run once in Supabase SQL Editor before deploying user-management endpoints.
-- No tables/columns added. Only the backend service role can execute this function.
begin;
create or replace function public.portal_manage_user(
    p_actor_id uuid,
    p_action text,
    p_user_id uuid default null,
    p_email text default null,
    p_permission_ids bigint[] default null,
    p_is_super_admin boolean default null,
    p_is_active boolean default null,
    p_validate_only boolean default false
) returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    actor public.profiles%rowtype;
    target public.profiles%rowtype;
    required_code text;
    output jsonb;
begin
    -- Serialize mutations from this function, including last-admin checks.
    perform pg_catalog.pg_advisory_xact_lock(748201631);
    if p_action not in ('create', 'update', 'deactivate') then
        raise exception 'INVALID_ACTION';
    end if;
    select * into actor from public.profiles where id = p_actor_id for update;
    if not found or actor."isActive" is not true or actor.is_first_login is not false then
        raise exception 'FORBIDDEN';
    end if;
    required_code := case p_action when 'create' then 'USER_CREATE'
        when 'update' then 'USER_UPDATE' else 'USER_REMOVE' end;
    if actor.is_super_admin is not true and not exists (
        select 1 from public.user_permissions up join public.permissions p on p.id=up.permission_id
        where up.user_id=p_actor_id and p.permission_code=required_code
    ) then raise exception 'FORBIDDEN'; end if;

    if p_action='update' and p_is_active is false and actor.is_super_admin is not true
       and not exists (
           select 1 from public.user_permissions up join public.permissions p on p.id=up.permission_id
           where up.user_id=p_actor_id and p.permission_code='USER_REMOVE'
       ) then raise exception 'FORBIDDEN'; end if;

    if p_permission_ids is not null then
        if cardinality(p_permission_ids)>500 or exists (
            select 1 from unnest(p_permission_ids) wanted(id)
            where wanted.id is null or not exists(select 1 from public.permissions p where p.id=wanted.id)
        ) then raise exception 'INVALID_PERMISSION_IDS'; end if;
        if actor.is_super_admin is not true and exists (
            select 1 from unnest(p_permission_ids) wanted(id)
            where not exists(select 1 from public.user_permissions up
                where up.user_id=p_actor_id and up.permission_id=wanted.id)
        ) then raise exception 'FORBIDDEN'; end if;
    end if;
    if actor.is_super_admin is not true and p_is_super_admin is true then
        raise exception 'FORBIDDEN';
    end if;
    if p_action <> 'create' then
        select * into target from public.profiles where id=p_user_id for update;
        if not found then raise exception 'USER_NOT_FOUND'; end if;
        -- Manage other accounts here; self-service passwords have separate endpoints.
        if p_user_id=p_actor_id then raise exception 'SELF_UPDATE_FORBIDDEN'; end if;
        if actor.is_super_admin is not true and (
            target.is_super_admin is true or exists (
                select 1 from public.user_permissions up where up.user_id=p_user_id
                and not exists(select 1 from public.user_permissions own
                    where own.user_id=p_actor_id and own.permission_id=up.permission_id)
            )
        ) then raise exception 'FORBIDDEN'; end if;
        if target.is_super_admin is true and target."isActive" is true
           and (p_action='deactivate' or p_is_active is false or p_is_super_admin is false)
           and not exists(select 1 from public.profiles where id<>p_user_id
               and is_super_admin is true and "isActive" is true and is_first_login is false)
        then raise exception 'LAST_ADMIN_REQUIRED'; end if;
    end if;
    if p_email is not null and exists (
        select 1 from public.profiles where lower(email)=lower(p_email) and id is distinct from p_user_id
    ) then raise exception 'EMAIL_ALREADY_EXISTS'; end if;
    if p_validate_only then return jsonb_build_object('validated',true); end if;

    if p_action='create' then
        if p_user_id is null or p_email is null then raise exception 'INVALID_INPUT'; end if;
        insert into public.profiles (id,email,is_super_admin,is_first_login,"isActive",created_by,updated_by)
        values (p_user_id,p_email,coalesce(p_is_super_admin,false),true,coalesce(p_is_active,true),p_actor_id,p_actor_id)
        on conflict (id) do update set email=excluded.email,
            is_super_admin=excluded.is_super_admin, is_first_login=true,
            "isActive"=excluded."isActive",created_by=p_actor_id,updated_by=p_actor_id,updated_at=now();
    else
        update public.profiles set
            email=coalesce(p_email,email),
            is_super_admin=coalesce(p_is_super_admin,is_super_admin),
            "isActive"=case when p_action='deactivate' then false else coalesce(p_is_active,"isActive") end,
            updated_by=p_actor_id,updated_at=now()
        where id=p_user_id;
    end if;
    if p_permission_ids is not null then
        delete from public.user_permissions where user_id=p_user_id
            and not (permission_id=any(p_permission_ids));
        insert into public.user_permissions (user_id,permission_id,created_by)
        select p_user_id,wanted.id,p_actor_id from (select distinct unnest(p_permission_ids) id) wanted
        on conflict (user_id,permission_id) do nothing;
    end if;
    select jsonb_build_object(
        'id',pr.id,'email',pr.email,'is_super_admin',coalesce(pr.is_super_admin,false),
        'is_first_login',coalesce(pr.is_first_login,true),'is_active',coalesce(pr."isActive",false),
        'created_at',pr.created_at,'updated_at',pr.updated_at,
        'permissions',coalesce((select jsonb_agg(p.permission_code order by p.permission_code)
            from public.user_permissions up join public.permissions p on p.id=up.permission_id
            where up.user_id=pr.id),'[]'::jsonb)
    ) into output from public.profiles pr where pr.id=p_user_id;
    return output;
end;
$$;
revoke all on function public.portal_manage_user(uuid,text,uuid,text,bigint[],boolean,boolean,boolean) from public, anon, authenticated;
grant execute on function public.portal_manage_user(uuid,text,uuid,text,bigint[],boolean,boolean,boolean) to service_role;
notify pgrst, 'reload schema';
commit;
