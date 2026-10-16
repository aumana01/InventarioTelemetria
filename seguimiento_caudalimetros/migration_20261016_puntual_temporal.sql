-- Ejecutar en Supabase SQL Editor antes de usar la nueva captura
-- de Medición Puntual Comparativa.
-- Mantiene intactos los registros históricos anteriores.
begin;

alter table public.caudalimetro_revisiones
    add column if not exists measurement_method text,
    add column if not exists point_flow_lps numeric,
    add column if not exists point_observations text;

alter table public.caudalimetro_revisiones
    drop constraint if exists caudalimetro_measurement_method_chk;
alter table public.caudalimetro_revisiones
    add constraint caudalimetro_measurement_method_chk
        check (measurement_method in ('puntual', 'temporal'));

alter table public.caudalimetro_revisiones
    drop constraint if exists caudalimetro_point_flow_chk;
alter table public.caudalimetro_revisiones
    add constraint caudalimetro_point_flow_chk
        check (point_flow_lps >= 0);

-- Se mantienen con NULL las modalidades no registradas históricamente.
-- La interfaz interpreta su contenido anterior al editar.
commit;
