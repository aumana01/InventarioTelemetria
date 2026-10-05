-- Ajustes incrementales al control de mantenimiento.
-- Ejecutar después de migration_20261005_maintenance_tracking.sql.

alter table public.caudalimetro_revisiones
    add column if not exists maintenance_gel_applicable boolean not null default true,
    add column if not exists maintenance_transducers_alignment_applicable boolean not null default true,
    add column if not exists maintenance_insertion_sensor_cleaning_date date,
    add column if not exists maintenance_solar_panel_applicable boolean not null default false,
    add column if not exists maintenance_solar_panel_cleaning_date date,
    add column if not exists equipment_serial text;

notify pgrst, 'reload schema';
