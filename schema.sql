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

-- 6. Globally managed calculated formulas.
create table if not exists public.calculated_formulas (
    id                   text         primary key,
    title                text         not null,
    left_operand         jsonb        not null,
    operator             text         not null check (operator in ('+', '-', '*', '/')),
    right_operand        jsonb        not null,
    adjustment_percent   numeric,
    precision            smallint     not null default 2 check (precision between 0 and 8),
    enabled              boolean      not null default true,
    sort_order           integer      not null default 0,
    created_at           timestamptz  not null default now(),
    updated_at           timestamptz  not null default now(),
    deleted_at           timestamptz
);

create index if not exists idx_calculated_formulas_order
    on public.calculated_formulas(deleted_at, sort_order);

insert into public.calculated_formulas (
    id, title, left_operand, operator, right_operand,
    adjustment_percent, precision, sort_order
) values
    (
        'delcrado',
        'ДЕЛЬКРАДО',
        '{"kind":"rate","provider":"MongolBank","symbol":"RUB/MNT","field":"rate"}',
        '*',
        '{"kind":"constant","value":"1.005"}',
        null,
        2,
        0
    ),
    (
        'triquetra',
        'ТРИКУЭТРА',
        '{"kind":"rate","provider":"TDB","symbol":"USD/MNT","field":"sell"}',
        '/',
        '{"kind":"rate","provider":"CBR","symbol":"USD/RUB","field":"rate"}',
        1,
        2,
        1
    ),
    (
        'rub-cash',
        'RUB БЭЛЭН',
        '{"kind":"rate","provider":"Binance","symbol":"P2P USDT/MNT","field":"min_price"}',
        '/',
        '{"kind":"rate","provider":"Rapira","symbol":"USDT/RUB","field":"buy"}',
        null,
        2,
        2
    )
on conflict (id) do nothing;

-- 7. Global app and source branding metadata.
create table if not exists public.app_branding (
    singleton    boolean      primary key default true check (singleton),
    logo_path    text,
    updated_at   timestamptz  not null default now()
);

insert into public.app_branding (singleton)
values (true)
on conflict (singleton) do nothing;

create table if not exists public.source_branding (
    provider     text         primary key,
    logo_path    text,
    updated_at   timestamptz  not null default now()
);

-- Public reads are intentional: these are non-sensitive logos. Uploads and
-- deletes are performed only by the backend with a storage-capable key.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
    'branding',
    'branding',
    true,
    2097152,
    array['image/png', 'image/jpeg', 'image/webp']
)
on conflict (id) do update set
    public = excluded.public,
    file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;
