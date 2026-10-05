# Seguimiento de Caudalímetros

Aplicación Streamlit para control técnico e historial de caudalímetros del AyA.

## Arquitectura actual

La aplicación soporta dos fuentes para el inventario de caudalímetros:

- **Supabase**: recomendada para Streamlit Community Cloud.
- **SQL Server**: para ejecución dentro de la red AyA.

En Streamlit Cloud ya no es necesario instalar el ODBC de SQL Server ni exponer el servidor institucional.

```text
SQL Server AyA
AYA.MSG_Medidores_de_Caudal
        |
        |  sincronizar_caudalimetros.py
        |  (se ejecuta dentro de la red AyA)
        v
Supabase
  ├── caudalimetros
  ├── caudalimetro_revisiones
  └── caudalimetros-graficos
        |
        v
Streamlit Cloud
```

La geodatabase continúa siendo la fuente maestra. Supabase mantiene una copia operacional de solo lectura para que el aplicativo publicado pueda funcionar fuera de la red institucional.

## Funcionalidad

- Lee todos los atributos de `AYA.MSG_Medidores_de_Caudal`, excluyendo `SHAPE`.
- Obtiene `SHAPE.STX` / `SHAPE.STY` y transforma CRTM05 EPSG:5367 a WGS84 EPSG:4326.
- Sincroniza el inventario a `public.caudalimetros` mediante UPSERT.
- Presenta mapa y atributos de geodatabase en modo solo lectura.
- Registra revisiones históricas en Supabase sin modificar la geodatabase.
- Controla rectificación simultánea, equipo utilizado, condición ultrasónica, circunferencia, espesor, distancia de transductores, calidad de medición, último mantenimiento y fallas.
- Permite cargar un HTML comparativo y almacenarlo en un bucket privado de Supabase.
- Permite guardar un vínculo original de Microsoft List / SharePoint y extraer el ID del adjunto cuando el URL contiene `/Attachments/{id}/archivo.html`.
- El vínculo puede complementarse con una copia HTML de visualización en Supabase para abrir el gráfico directamente dentro de la ficha sin descargarlo al escritorio.
- Permite registrar un punto WGS84 específico de la medición, independiente de la ubicación del macromedidor.
- Muestra el HTML directamente dentro de la ficha mediante un iframe `sandbox`.
- Incluye integración opcional con Microsoft List mediante SharePoint REST y Microsoft Entra. No depende del conector de SharePoint de ChatGPT.
- Incluye diagnóstico separado para SQL, inventario Supabase, revisiones Supabase y Microsoft List.

## 1. Preparar Supabase

Abra **Supabase → SQL Editor** y ejecute el archivo:

`supabase_schema.sql`

Esto crea:

- `public.caudalimetros`: copia operacional del inventario;
- `public.caudalimetro_revisiones`: historial de revisiones;
- índice de sincronización;
- índice de revisiones por equipo y fecha;
- bucket privado `caudalimetros-graficos`.

Si ya había ejecutado una versión anterior de `supabase_schema.sql`, puede ejecutar nuevamente el archivo completo. Las instrucciones usan `create table if not exists`.

La aplicación usa una `service_role_key` únicamente del lado servidor. No debe colocarse en código fuente, HTML o JavaScript.

## 2. Secrets para Streamlit Cloud

En **Streamlit Community Cloud → App → Settings → Secrets** use, como mínimo:

```toml
[app]
demo_mode = false
data_source = "supabase"
password = ""

[supabase]
url = "https://TU-PROYECTO.supabase.co"
service_role_key = "TU_SERVICE_ROLE_KEY"
table = "caudalimetro_revisiones"
meters_table = "caudalimetros"
bucket = "caudalimetros-graficos"
```

Puede mantener también la sección `[sql]`, pero **Streamlit Cloud no la utiliza cuando `data_source = "supabase"`**.

## 3. Sincronizar SQL AyA → Supabase

La primera sincronización debe ejecutarse desde una computadora que:

1. esté dentro de la red AyA o tenga acceso válido al servidor SQL;
2. tenga instalado el ODBC utilizado por SQL Server;
3. tenga Python y las dependencias del proyecto;
4. tenga configuradas tanto las credenciales SQL como las de Supabase.

En el `.streamlit/secrets.toml` de esa computadora:

```toml
[app]
demo_mode = false
data_source = "sql"
password = ""

[sql]
server = "SERVIDOR_SQL_INTERNO"
database = "GIS_RME"
username = "USUARIO_SQL"
password = "CONTRASENA_SQL"
driver = "ODBC Driver 13 for SQL Server"
schema = "AYA"
table = "MSG_Medidores_de_Caudal"
key_field = "Código_Caudalimetro"

[supabase]
url = "https://TU-PROYECTO.supabase.co"
service_role_key = "TU_SERVICE_ROLE_KEY"
table = "caudalimetro_revisiones"
meters_table = "caudalimetros"
bucket = "caudalimetros-graficos"
```

Luego ejecute:

```cmd
cd seguimiento_caudalimetros
python sincronizar_caudalimetros.py
```

El proceso:

1. consulta la geodatabase;
2. transforma CRTM05 a WGS84;
3. detecta la clave del caudalímetro;
4. guarda todos los atributos en JSON;
5. ejecuta UPSERT en `public.caudalimetros`.

La sincronización no modifica SQL Server y no elimina registros de Supabase que hayan desaparecido de SQL.

Después de sincronizar, en Streamlit Cloud pulse **Actualizar datos**.

## 4. Ejecución local directa contra SQL

Dentro de la red AyA puede hacer que Streamlit consulte directamente SQL:

```toml
[app]
data_source = "sql"
demo_mode = false
```

Ejecute:

```cmd
streamlit run app.py
```

En este modo sí se requiere el driver ODBC configurado.

## 5. Valores de data_source

```toml
data_source = "supabase"
```

Usa `public.caudalimetros`. Es la opción recomendada para Streamlit Cloud.

```toml
data_source = "sql"
```

Consulta directamente `AYA.MSG_Medidores_de_Caudal`. Úselo dentro de la red AyA.

```toml
data_source = "auto"
```

Usa Supabase si está configurado y, en caso contrario, SQL.

## 6. Microsoft List: vínculo y API opcional

El aplicativo funciona sin API de Microsoft List. En **Vínculo MS List / SharePoint** puede guardar el URL original del adjunto HTML. Como SharePoint puede exigir autenticación o responder con descarga forzada, el aplicativo no depende de incrustar directamente ese URL en un iframe.

Para garantizar visualización dentro de la ficha, puede adjuntar el mismo archivo HTML como **copia de visualización**. El archivo se conserva en el bucket privado de Supabase y el vínculo original sigue almacenado como referencia oficial.

Antes de utilizar el vínculo o las coordenadas de medición puntual en una instalación existente, ejecute en Supabase SQL Editor:

`migration_20261005_sharepoint_link_location.sql`

Si más adelante se configura Microsoft Entra / SharePoint REST, el aplicativo puede aprovechar el ID extraído del vínculo para recuperar el adjunto por API.

El aplicativo funciona también sin Microsoft List mediante carga manual del HTML.

Si posteriormente se desea consultar la lista `Seguimiento de Detección de Fugas GAM`, se debe registrar una aplicación en Microsoft Entra ID y configurar:

- `tenant_id`
- `client_id`
- `client_secret`

La aplicación consulta los `AttachmentFiles`, identifica un archivo `.html` o `.htm` y lo muestra en la ficha.

## 7. Instalación local

Desde esta carpeta:

```cmd
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
streamlit run app.py
```

## 8. Modo demo

Para probar la interfaz sin SQL ni Supabase:

```cmd
set APP_DEMO_MODE=true
streamlit run app.py
```

## 9. Pruebas

```bash
PYTHONPATH=. pytest -q
```

GitHub Actions:

- compila `app.py`, el sincronizador, módulos y pruebas;
- ejecuta pruebas unitarias;
- inicia Streamlit en modo demo;
- consulta `/_stcore/health`.

## Seguridad

- No se escriben cambios en la geodatabase.
- SQL Server no necesita quedar expuesto a Internet.
- Los secretos quedan fuera del repositorio.
- Los HTML externos se muestran dentro de un iframe con `sandbox`.
- El bucket de gráficos es privado.
- La `service_role_key` permanece únicamente del lado servidor.
- Puede habilitarse una contraseña básica mediante `[app].password`.
