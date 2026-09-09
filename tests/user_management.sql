-- Isolated PostgreSQL/PGlite test database ONLY. Never run on a real project.
create role anon;
create role authenticated;
create role service_role;
create schema auth;
create table auth.users(id uuid primary key);
create table public.profiles (
 id uuid primary key references auth.users(id), email text not null,
 is_super_admin boolean default false, is_first_login boolean default true,
 "isActive" boolean default true, permissions text[] not null default '{}',
 created_at timestamptz default now(), updated_at timestamptz default now(),
 created_by uuid, updated_by uuid
);
create table public.permissions(id bigint primary key, permission_code text unique);
create table public.user_permissions(
 user_id uuid references profiles(id), permission_id bigint references permissions(id),
 created_by uuid, created_at timestamptz default now(), primary key(user_id,permission_id)
);
insert into auth.users values
 ('11111111-1111-4111-8111-111111111111'),
 ('22222222-2222-4222-8222-222222222222'),
 ('33333333-3333-4333-8333-333333333333');
insert into profiles(id,email,is_super_admin,is_first_login) values
 ('11111111-1111-4111-8111-111111111111','admin@example.com',true,false),
 ('22222222-2222-4222-8222-222222222222','manager@example.com',false,false);
insert into permissions values (1,'USER_CREATE'),(2,'USER_UPDATE'),(3,'USER_REMOVE'),(4,'USER_VIEW');
insert into user_permissions(user_id,permission_id) values
 ('22222222-2222-4222-8222-222222222222',1),('22222222-2222-4222-8222-222222222222',2);
