-- Optimización de almacenamiento de gráficos Plotly.
-- Los HTML antiguos se consideran formato 'html'.
-- El agente nuevo reemplaza automáticamente los SharePoint HTML por JSON Plotly comprimido.

alter table public.caudalimetro_revisiones
    add column if not exists graph_format text not null default 'html';

alter table public.caudalimetro_revisiones
    drop constraint if exists caudalimetro_graph_format_chk;

alter table public.caudalimetro_revisiones
    add constraint caudalimetro_graph_format_chk
    check (graph_format in ('html', 'plotly_json_gzip'));

update public.caudalimetro_revisiones
set graph_format = 'html'
where graph_format is null;

notify pgrst, 'reload schema';
