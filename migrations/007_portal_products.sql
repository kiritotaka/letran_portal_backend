-- Step 1: product master only. No import, CRUD API or data loading.
-- Run once after migration 006. Fails on an existing table to avoid changing shared data.
begin;
create table public.portal_products (
 id uuid primary key default gen_random_uuid(),
 product_code text not null unique check(length(product_code) between 1 and 100 and product_code=btrim(product_code)),
 product_name text not null check(length(btrim(product_name)) between 1 and 500),
 is_active boolean not null default true,
 created_at timestamptz not null default now(),
 updated_at timestamptz not null default now(),
 created_by uuid not null references public.profiles(id),
 updated_by uuid not null references public.profiles(id)
);
create index portal_products_active_code on public.portal_products(is_active,product_code);

create function public.portal_products_touch_updated_at() returns trigger
language plpgsql set search_path='' as $$
begin
 new.updated_at=now();
 return new;
end $$;
create trigger portal_products_updated_at before update on public.portal_products
 for each row execute function public.portal_products_touch_updated_at();
revoke all on function public.portal_products_touch_updated_at() from public,anon,authenticated;

alter table public.portal_products enable row level security;
revoke all on public.portal_products from public,anon,authenticated;
-- Deactivation is the normal removal operation. No direct DELETE grant.
grant select,insert,update on public.portal_products to service_role;
notify pgrst,'reload schema';
commit;
