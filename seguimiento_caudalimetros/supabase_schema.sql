create extension if not exists pgcrypto;

-- Copia operacional del inventario de caudalímetros.
-- Se alimenta desde la red AyA con sincronizar_caudalimetros.py.
create table if not exists public.caudalimetros (
    equipment_key text primary key,
    sql_key_field text not null,
    attributes jsonb not null default '{}'::jsonb,
    longitude double precision,
    latitude double precision,
    x_crtm05 double precision,
    y_crtm05 double precision,
    srid_original integer,
    synced_at timestamptz not null default now()
);

create index if not exists idx_caudalimetros_synced_at
    on public.caudalimetros (synced_at desc);

create table if not exists public.caudalimetro_revisiones (
    id uuid primary key default gen_random_uuid(),
    reviewed_at timestamptz not null default now(),
    equipment_key text not null,
    equipment_label text,
    sql_key_field text,
    geodatabase_snapshot jsonb not null default '{}'::jsonb,

    rectification_status text not null,
    rectification_equipment text,
    is_ultrasonic boolean not null default false,
    circumference_mm numeric,
    wall_thickness_mm numeric,
    transducer_distance_mm numeric,
    measurement_quality text not null,

    graph_source text not null default 'none',
    graph_storage_path text,
    graph_original_url text,
    sharepoint_item_id bigint,
    sharepoint_file_name text,

    measurement_latitude double precision,
    measurement_longitude double precision,
    measurement_location_notes text,

    last_maintenance_date date,
    failures text,
    notes text,
    reviewed_by text,

    constraint caudalimetro_rectification_status_chk
      check (rectification_status in ('No se ha realizado', 'Sí, con medición simultánea')),
    constraint caudalimetro_measurement_quality_chk
      check (measurement_quality in ('Excelente', 'Buena', 'Regular', 'Mala')),
    constraint caudalimetro_graph_source_chk
      check (graph_source in ('none', 'manual', 'sharepoint', 'sharepoint_link')),
    constraint caudalimetro_ultrasonic_values_chk
      check (
        not is_ultrasonic
        or (
          coalesce(circumference_mm, 0) > 0
          and coalesce(wall_thickness_mm, 0) > 0
          and coalesce(transducer_distance_mm, 0) > 0
        )
      )
);


-- Migración segura para instalaciones existentes.
alter table public.caudalimetro_revisiones
    add column if not exists graph_original_url text;

alter table public.caudalimetro_revisiones
    add column if not exists measurement_latitude double precision;

alter table public.caudalimetro_revisiones
    add column if not exists measurement_longitude double precision;

alter table public.caudalimetro_revisiones
    add column if not exists measurement_location_notes text;

alter table public.caudalimetro_revisiones
    drop constraint if exists caudalimetro_graph_source_chk;

alter table public.caudalimetro_revisiones
    add constraint caudalimetro_graph_source_chk
      check (graph_source in ('none', 'manual', 'sharepoint', 'sharepoint_link'));

create index if not exists idx_caudalimetro_revisiones_equipment_date
    on public.caudalimetro_revisiones (equipment_key, reviewed_at desc);

insert into storage.buckets (id, name, public)
values ('caudalimetros-graficos', 'caudalimetros-graficos', false)
on conflict (id) do update set public = false;

-- La aplicación usa una service role key únicamente del lado servidor.
-- No exponga esa clave en HTML, JavaScript, GitHub ni en el navegador.
