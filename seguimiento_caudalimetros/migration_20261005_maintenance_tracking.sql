-- Seguimiento de mantenimiento, datos, reparaciones y generalidades.
-- Ejecutar una sola vez en Supabase SQL Editor.

alter table public.caudalimetro_revisiones
    add column if not exists maintenance_gel_date date,
    add column if not exists maintenance_transducers_alignment_date date,
    add column if not exists maintenance_internal_download_applicable boolean not null default true,
    add column if not exists maintenance_internal_download_date date,
    add column if not exists maintenance_simultaneous_installation_date date,
    add column if not exists maintenance_scada_working boolean,
    add column if not exists maintenance_scada_check_date date,

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

notify pgrst, 'reload schema';
