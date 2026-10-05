-- Convierte los controles de visualización/datos en pendientes de reparación.
-- Mantiene las columnas antiguas de Sí/No + fecha como histórico, pero la app deja de usarlas.

alter table public.caudalimetro_revisiones
    add column if not exists repair_perspective_pending boolean not null default false,
    add column if not exists repair_vision_cco_pending boolean not null default false,
    add column if not exists repair_vision_scada_vr2_pending boolean not null default false,
    add column if not exists repair_vision_reports_pending boolean not null default false;

-- Migración de sentido histórico:
-- antes: visible/descargable = true  -> sin pendiente
--        visible/descargable = false -> pendiente
--        null                         -> sin pendiente por defecto
update public.caudalimetro_revisiones
set
    repair_perspective_pending =
        case
            when data_perspective_visible is false then true
            else false
        end,
    repair_vision_cco_pending =
        case
            when data_vision_cco_visible is false then true
            else false
        end,
    repair_vision_scada_vr2_pending =
        case
            when data_vision_scada_vr2_visible is false then true
            else false
        end,
    repair_vision_reports_pending =
        case
            when data_vision_reports_downloadable is false then true
            else false
        end;

notify pgrst, 'reload schema';
