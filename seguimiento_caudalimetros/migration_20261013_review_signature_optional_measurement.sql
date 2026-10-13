-- Ejecutar una sola vez en el SQL Editor del proyecto Supabase,
-- ANTES de utilizar la versión de la aplicación que guarda review_date.
-- Se conservan todas las revisiones históricas y su información original.

begin;

-- La calidad solo se registra cuando hubo medición simultánea.
alter table public.caudalimetro_revisiones
    alter column measurement_quality drop not null;

-- La fecha de revisión es la fecha que firma el responsable autorizado.
-- No reemplaza reviewed_at, que sigue siendo el momento de creación del registro.
alter table public.caudalimetro_revisiones
    add column if not exists review_date date;

-- Compatibilidad con el historial previo: asigna la fecha local de Costa Rica
-- del registro para revisiones que aún no tengan fecha de firma propia.
update public.caudalimetro_revisiones
set review_date = (reviewed_at at time zone 'America/Costa_Rica')::date
where review_date is null;

commit;
