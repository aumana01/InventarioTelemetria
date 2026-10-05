-- Historial de reportes por correo. No altera inventario ni revisiones existentes.
create table if not exists public.caudalimetro_reportes_envios (
    id uuid primary key,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    status text not null default 'prepared'
        check (status in ('prepared', 'accepted', 'error', 'unknown')),
    provider text not null default 'resend',
    provider_message_id text,
    sender text not null,
    recipients jsonb not null default '[]'::jsonb,
    cc jsonb not null default '[]'::jsonb,
    subject text not null,
    scope text,
    filters jsonb not null default '{}'::jsonb,
    total_rows integer not null,
    shown_rows integer not null,
    equipment_count integer not null,
    html_sha256 text not null,
    test_mode boolean not null default true,
    error text
);
create index if not exists idx_caudalimetro_reportes_envios_created
    on public.caudalimetro_reportes_envios (created_at desc);
alter table public.caudalimetro_reportes_envios enable row level security;
revoke all on table public.caudalimetro_reportes_envios from anon, authenticated;
grant select, insert, update on table public.caudalimetro_reportes_envios to service_role;
-- Solo el backend usa service_role. No almacene API keys ni credenciales aquí.
