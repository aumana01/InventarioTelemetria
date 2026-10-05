# Agente SharePoint Caudalímetros

Agente local independiente para importar automáticamente a Supabase los HTML de SharePoint asociados a revisiones del aplicativo de caudalímetros.

## Arquitectura

```text
Streamlit -> Supabase <- Agente local -> SharePoint
```

La aplicación web únicamente guarda el vínculo. El agente consulta Supabase cada minuto, usa una sesión persistente de Microsoft Edge para leer el HTML real y extrae solamente la especificación Plotly (trazas + layout + configuración). Esa información se comprime como JSON gzip y se copia al bucket privado de Supabase; el Plotly.js completo no se almacena con cada gráfico.

No usa Microsoft Entra App Registration, client_id, client_secret, Power Automate ni Microsoft Graph.

## Instalación en Windows

1. Copie esta carpeta a una ubicación permanente.
2. Ejecute `instalar_agente.bat`.
3. Complete `agent_secrets.toml` cuando se abra el Bloc de notas.
4. Inicie sesión en Microsoft 365 en la ventana de Edge cuando se solicite.
5. El instalador crea un acceso directo en Inicio de Windows y deja el agente ejecutándose en segundo plano.

## Configuración

`agent_secrets.toml`:

```toml
[supabase]
url = "https://TU-PROYECTO.supabase.co"
service_role_key = "TU_SERVICE_ROLE_KEY"
table = "caudalimetro_revisiones"
bucket = "caudalimetros-graficos"

[sharepoint]
site_url = "https://intranetaya.sharepoint.com/sites/MejoramientodeSistemas769"

[agent]
poll_seconds = 60
```

No suba `agent_secrets.toml` a GitHub.

## Operación

El usuario de Streamlit solo pega el vínculo y guarda. Si `graph_storage_path` está vacío, el agente lo detecta y sincroniza el HTML automáticamente.

Además, el agente publica una **señal de vida (heartbeat)** en el bucket privado de Supabase cada ciclo. La vista **Diagnóstico** del aplicativo utiliza esa señal para indicar si existe un agente activo, en qué equipo está corriendo y hace cuántos segundos se recibió la última señal. No se requiere una tabla nueva ni una migración SQL.

Para renovar la sesión Microsoft 365:

```text
configurar_sesion.bat
```

Para iniciar o detener manualmente:

```text
iniciar_agente.bat
detener_agente.bat
```

El log local se guarda normalmente en:

```text
%LOCALAPPDATA%\AyA\AgenteSharePointCaudalimetros\agent.log
```


## Optimización de gráficos Plotly

Desde la versión 1.2.0 el agente busca tanto vínculos pendientes como gráficos SharePoint antiguos almacenados en HTML. Cuando encuentra un HTML legado:

1. descarga temporalmente el HTML desde SharePoint;
2. extrae las llamadas `Plotly.newPlot(...)`;
3. conserva únicamente `data`, `layout` y `config`;
4. genera un archivo `.plotly.json.gz`;
5. lo sube a Supabase;
6. actualiza `graph_format = plotly_json_gzip`;
7. elimina del bucket el HTML pesado anterior.

La aplicación Streamlit instala Plotly.js 3.0.1 una sola vez y reconstruye el gráfico desde el archivo compacto.
