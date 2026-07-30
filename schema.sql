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

-- 3. Whitelist table
create table if not exists public.whitelist (
    telegram_id  bigint       primary key,
    added_at     timestamptz  not null default now()
);

-- Seed initial whitelisted users
insert into public.whitelist (telegram_id)
values (1447446407), (1932946217)
on conflict (telegram_id) do nothing;

-- 4. Cached rates table
create table if not exists public.cached_rates (
    provider    text         not null,
    symbol      text         not null,
    rate_data   jsonb        not null default '{}'::jsonb,
    fetched_at  timestamptz  not null default now(),
    primary key (provider, symbol)
);

-- 5. Short-lived selections used to hand browser sharing into the Mini App.
create table if not exists public.share_bundles (
    token        text         primary key,
    telegram_id  bigint       not null references public.users(telegram_id) on delete cascade,
    payload      jsonb        not null default '{}'::jsonb,
    created_at   timestamptz  not null default now(),
    expires_at   timestamptz  not null
);

create index if not exists idx_share_bundles_owner
    on public.share_bundles(telegram_id, expires_at);
