-- Supabase SQL: run this in the Supabase SQL Editor to create the schema.

-- 1. Users table
create table if not exists public.users (
    telegram_id  bigint       primary key,
    username     text         not null default '',
    created_at   timestamptz  not null default now()
);

-- 2. Subscriptions table
create table if not exists public.user_subscriptions (
    id           uuid         primary key default gen_random_uuid(),
    telegram_id  bigint       not null references public.users(telegram_id) on delete cascade,
    provider     text         not null,
    symbol       text         not null,
    created_at   timestamptz  not null default now(),
    unique (telegram_id, provider, symbol)
);

create index if not exists idx_subs_user on public.user_subscriptions(telegram_id);

-- 3. Cached rates table
create table if not exists public.cached_rates (
    provider    text         not null,
    symbol      text         not null,
    rate_data   jsonb        not null default '{}'::jsonb,
    fetched_at  timestamptz  not null default now(),
    primary key (provider, symbol)
);
