-- Ejecutar una vez en Supabase SQL Editor antes de usar
-- "Vínculo MS List / SharePoint" o coordenadas de medición puntual.

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

NOTIFY pgrst, 'reload schema';
