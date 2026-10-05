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

    maintenance_gel_applicable boolean not null default true,
    maintenance_gel_date date,
    maintenance_transducers_alignment_applicable boolean not null default true,
    maintenance_transducers_alignment_date date,
    maintenance_internal_download_applicable boolean not null default true,
    maintenance_internal_download_date date,
    maintenance_simultaneous_installation_date date,
    maintenance_scada_working boolean,
    maintenance_scada_check_date date,
    maintenance_insertion_sensor_cleaning_date date,
    maintenance_solar_panel_applicable boolean not null default false,
    maintenance_solar_panel_cleaning_date date,

    data_perspective_visible boolean,
    data_perspective_check_date date,
    data_vision_cco_visible boolean,
    data_vision_cco_check_date date,
    data_vision_scada_vr2_visible boolean,
    data_vision_scada_vr2_check_date date,
    data_vision_reports_downloadable boolean,
    data_vision_reports_check_date date,

    repair_signal_pending boolean not null default false,
    repair_calibration_pending boolean not null default false,
    repair_power_pending boolean not null default false,
    repair_wiring_pending boolean not null default false,
    repair_spare_part_required boolean not null default false,
    repair_spare_part_detail text,
    repair_temporary_replacement boolean not null default false,
    repair_permanent_replacement boolean not null default false,

    equipment_type text not null default 'No definido',
    equipment_serial text,
    transducer_serial text,
    pipe_material text,
    electromagnetic_diameter numeric,
    calibration_factor numeric,
    open_channel_height numeric,
    open_channel_width numeric,
    open_channel_x_downstream numeric,
    open_channel_y_downstream numeric,
    open_channel_surface_type text,
    insertion_depth numeric,
    insertion_diameter numeric,

    constraint caudalimetro_rectification_status_chk
      check (rectification_status in ('No se ha realizado', 'Sí, con medición simultánea')),
    constraint caudalimetro_measurement_quality_chk
      check (measurement_quality in ('Excelente', 'Buena', 'Regular', 'Mala')),
    constraint caudalimetro_graph_source_chk
      check (graph_source in ('none', 'manual', 'sharepoint', 'sharepoint_link')),
    constraint caudalimetro_equipment_type_chk
      check (
        equipment_type in (
          'No definido',
          'Ultrasónico',
          'Electromagnético',
          'Canal Abierto',
          'Inserción'
        )
      ),
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
    add column if not exists maintenance_gel_applicable boolean not null default true,
    add column if not exists maintenance_gel_date date,
    add column if not exists maintenance_transducers_alignment_applicable boolean not null default true,
    add column if not exists maintenance_transducers_alignment_date date,
    add column if not exists maintenance_internal_download_applicable boolean not null default true,
    add column if not exists maintenance_internal_download_date date,
    add column if not exists maintenance_simultaneous_installation_date date,
    add column if not exists maintenance_scada_working boolean,
    add column if not exists maintenance_scada_check_date date,
    add column if not exists maintenance_insertion_sensor_cleaning_date date,
    add column if not exists maintenance_solar_panel_applicable boolean not null default false,
    add column if not exists maintenance_solar_panel_cleaning_date date,
    add column if not exists data_perspective_visible boolean,
    add column if not exists data_perspective_check_date date,
    add column if not exists data_vision_cco_visible boolean,
    add column if not exists data_vision_cco_check_date date,
    add column if not exists data_vision_scada_vr2_visible boolean,
    add column if not exists data_vision_scada_vr2_check_date date,
    add column if not exists data_vision_reports_downloadable boolean,
    add column if not exists data_vision_reports_check_date date,
    add column if not exists repair_signal_pending boolean not null default false,
    add column if not exists repair_calibration_pending boolean not null default false,
    add column if not exists repair_power_pending boolean not null default false,
    add column if not exists repair_wiring_pending boolean not null default false,
    add column if not exists repair_spare_part_required boolean not null default false,
    add column if not exists repair_spare_part_detail text,
    add column if not exists repair_temporary_replacement boolean not null default false,
    add column if not exists repair_permanent_replacement boolean not null default false,
    add column if not exists equipment_type text not null default 'No definido',
    add column if not exists equipment_serial text,
    add column if not exists transducer_serial text,
    add column if not exists pipe_material text,
    add column if not exists electromagnetic_diameter numeric,
    add column if not exists calibration_factor numeric,
    add column if not exists open_channel_height numeric,
    add column if not exists open_channel_width numeric,
    add column if not exists open_channel_x_downstream numeric,
    add column if not exists open_channel_y_downstream numeric,
    add column if not exists open_channel_surface_type text,
    add column if not exists insertion_depth numeric,
    add column if not exists insertion_diameter numeric;

alter table public.caudalimetro_revisiones
    drop constraint if exists caudalimetro_graph_source_chk;

alter table public.caudalimetro_revisiones
    add constraint caudalimetro_graph_source_chk
      check (graph_source in ('none', 'manual', 'sharepoint', 'sharepoint_link'));

alter table public.caudalimetro_revisiones
    drop constraint if exists caudalimetro_equipment_type_chk;

alter table public.caudalimetro_revisiones
    add constraint caudalimetro_equipment_type_chk
      check (
        equipment_type in (
          'No definido',
          'Ultrasónico',
          'Electromagnético',
          'Canal Abierto',
          'Inserción'
        )
      );

create index if not exists idx_caudalimetro_revisiones_equipment_date
    on public.caudalimetro_revisiones (equipment_key, reviewed_at desc);

insert into storage.buckets (id, name, public)
values ('caudalimetros-graficos', 'caudalimetros-graficos', false)
on conflict (id) do update set public = false;

-- La aplicación usa una service role key únicamente del lado servidor.
-- No exponga esa clave en HTML, JavaScript, GitHub ni en el navegador.
