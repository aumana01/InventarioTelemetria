-- Agrega seguimiento de actualización de software / firmware como pendiente de mantenimiento.

alter table public.caudalimetro_revisiones
    add column if not exists repair_software_firmware_pending boolean not null default false;

notify pgrst, 'reload schema';
