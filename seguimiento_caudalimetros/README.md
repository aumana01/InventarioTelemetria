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
- Controla rectificación simultánea, calidad de medición y seguimiento histórico.
- Incorpora secciones de mantenimiento con semáforos automáticos por vencimiento (1, 6 y 12 meses).
- Controla como pendientes de reparación/mantenimiento la visualización en Perspective, Vision Client CCO, Vision Client SCADA vr2 y la descarga desde el módulo de reportes.
- Controla reparaciones pendientes con semáforo verde/rojo para señal, calibración, energía, cableado, visualización de datos, repuestos y sustituciones.
- Registra generalidades por tipo de equipo: ultrasónico, electromagnético, canal abierto e inserción.
- Permite cargar un HTML comparativo manual y almacenarlo en un bucket privado de Supabase.
- Para SharePoint, el agente extrae únicamente las trazas, layout y configuración de Plotly, las comprime como JSON gzip y evita almacenar Plotly.js repetidamente.
- Plotly.js 3.0.1 se instala una sola vez con la aplicación mediante `plotly==6.0.1`.
- Permite guardar un vínculo original de Microsoft List / SharePoint y extraer el ID del adjunto cuando el URL contiene `/Attachments/{id}/archivo.html`.
- Los vínculos de SharePoint quedan pendientes de sincronización local; un script abre Microsoft Edge con la sesión normal del usuario, extrae el HTML real y lo copia a Supabase.
- Permite registrar un punto WGS84 específico de la medición, independiente de la ubicación del macromedidor.
- Muestra el HTML directamente dentro de la ficha mediante un iframe `sandbox`.
- No requiere Microsoft Entra/App Registration para sincronizar adjuntos SharePoint: usa una sesión local persistente de Microsoft Edge.
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

Si la instalación ya existe y únicamente desea incorporar el nuevo módulo de mantenimiento, ejecute:

`migration_20261005_maintenance_tracking.sql`

Esta migración agrega únicamente columnas nuevas y conserva los registros históricos existentes. Los semáforos no se almacenan como colores: se calculan en tiempo real a partir de las fechas y estados registrados.

Si ya ejecutó esa migración y desea incorporar los ajustes posteriores de aplicabilidad, limpieza de sensor/panel solar y número de serie del equipo, ejecute además:

`migration_20261005_maintenance_tracking_v2.sql`

Los controles de Perspective, Vision Client y reportes se presentan dentro de **Aspectos de reparación o mantenimiento**.

Si ya utilizó la versión anterior de esos controles, ejecute además:

`migration_20261005_data_checks_as_repairs.sql`

Esta migración los convierte a pendientes de corrección con semáforo verde/rojo. Un valor histórico **No** se convierte en **Pendiente** y un valor **Sí** se convierte en **Sin pendiente**. Las columnas antiguas de fecha se conservan únicamente como histórico y dejan de mostrarse en la aplicación.

Para activar el almacenamiento optimizado de gráficos SharePoint, ejecute también:

`migration_20261005_compact_plotly_storage.sql`

El agente versión 1.2.0 detecta automáticamente revisiones SharePoint que todavía estén en formato HTML, vuelve a leer el vínculo original, genera un `.plotly.json.gz`, actualiza la revisión y elimina el archivo HTML anterior del bucket después de confirmar la nueva copia. Los HTML manuales se mantienen compatibles como formato legado.

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

## 6. Microsoft List / SharePoint

La aplicación web guarda el vínculo del adjunto y utiliza Supabase como punto de intercambio con un **agente externo de sincronización**.

El usuario de Streamlit no ejecuta comandos. El flujo es:

```text
Streamlit
   ↓
guarda vínculo SharePoint en Supabase
   ↓
Agente SharePoint externo
   ↓
lee el HTML con una sesión Microsoft 365 válida
   ↓
copia el HTML al bucket privado de Supabase
   ↓
Streamlit muestra el gráfico
```

Mientras `graph_storage_path` esté vacío, la ficha muestra **Pendiente de importación automática**. Cuando el agente termina, la ficha muestra **Sincronizado** y renderiza el HTML desde Supabase.

El agente está preparado de forma autocontenida en la carpeta `/agente_sharepoint`, con sus propias dependencias, configuración y scripts de instalación para Windows. Está diseñado para vivir en un repositorio independiente y comunicarse con este aplicativo únicamente por Supabase.

No requiere Microsoft Entra App Registration, `client_id`, `client_secret`, Power Automate ni Microsoft Graph.


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

## 10. Dashboard de seguimiento

En **Vista → Dashboard** se consulta el inventario completo, sin seleccionar un equipo individual.

- **Estado actual**: usa la última revisión global de cada equipo y agrega los equipos sin revisión. Primero se determina la última revisión y después se filtran las fechas, evitando presentar pendientes antiguos ya corregidos como si fueran actuales.
- **Historial**: consulta todas las revisiones, con paginación de Supabase para superar el límite habitual de 500 registros. Los equipos sin revisión no tienen registros históricos.
- **Resumen por equipo**: una fila por equipo/revisión, con cantidad y descripción de pendientes.
- **Detalle por aspecto**: una fila por control de mantenimiento, reparación o control general; incluye fecha y vencimiento cuando corresponda.

Los filtros incluyen sistema, tipo, semáforo, estado, calidad, rectificación, responsable, estado del inventario, disponibilidad del gráfico, código de equipo y búsqueda por código/nombre/serie/observaciones. En detalle también se puede filtrar por categoría y aspecto, incluyendo Software / Firmware.

Los períodos disponibles son última semana (7 fechas, incluida hoy), mes, 2 meses, trimestre y año móviles, fecha específica y rango personalizado. Los meses se calculan como meses calendario. Se pueden aplicar sobre fecha de revisión o último mantenimiento; en detalle también sobre fecha del aspecto y vencimiento. Los límites son inclusivos y las fechas de revisión se convierten a **America/Costa_Rica**. La opción **Incluir registros sin fecha** mantiene los equipos sin revisión o aspectos sin fecha dentro de un período seleccionado.

Las reglas de mantenimiento y reparación son las mismas que en la ficha. Calidad Excelente/Buena es verde; Regular/Mala/sin dato es roja. La rectificación sin realizar es roja. Un equipo sin revisión aparece rojo. El resumen es rojo cuando cualquier aspecto es rojo; los aspectos no aplicables se muestran grises en detalle. Los vencimientos se evalúan al día actual, incluso al consultar registros históricos. El estado del gráfico es un filtro informativo y no cambia el semáforo.

La tabla conserva los colores de las filas, permite ordenar columnas y descargar los resultados filtrados en CSV compatible con Excel. Los contadores corresponden al resultado filtrado: en detalle cuentan aspectos y en historial pueden incluir varias revisiones de un mismo equipo.

**Actualizar datos** recarga el inventario y las revisiones. Las revisiones tienen una caché de 60 segundos, invalidada al guardar, editar o eliminar una revisión desde la aplicación. El Dashboard es de consulta y **no requiere una nueva migración de Supabase**.

## 11. Reportes HTML por correo desde Dashboard

Debajo de los resultados filtrados, **Reporte por correo → Preparar reporte y ver correo** permite generar un mensaje HTML sin adjuntos. El reporte incluye título, responsable, mensaje introductorio, filtros, indicadores, resumen por sistema y filas con estados rojos/verdes/grises. Se puede limitar a estados rojos y elegir 25, 50, 100 o 200 filas de detalle. Los indicadores abarcan todos los resultados del reporte; las filas rojas tienen prioridad. Si se omiten filas o se resumen textos extensos, el correo lo indica. El HTML se limita a 90 KB para mantener un cuerpo de correo razonable.

El diseño usa tablas y estilos en línea, con ajuste para pantallas pequeñas; la apariencia final puede variar según el cliente de correo. Se incluye una versión en texto plano. La vista previa y su descarga HTML funcionan sin configurar Resend. El modo demo permite revisar el diseño, pero no enviar.

### Preparación de Supabase

Para una instalación existente, ejecute **migration_20261005_email_reports.sql** en SQL Editor. Esta migración crea únicamente `public.caudalimetro_reportes_envios`, con RLS activado y acceso reservado al backend mediante service role. No modifica el inventario ni las revisiones. Las instalaciones nuevas que ejecuten el esquema completo ya incluyen esta tabla.

El registro conserva destinatarios, asunto, filtros, cantidades, hash del HTML, identificador de solicitud y respuesta del proveedor. No guarda el cuerpo HTML, adjuntos ni claves API. Si no puede registrarse la solicitud, no se realiza el envío.

### Primera prueba, sin dominio propio

1. Cree una cuenta en **https://resend.com** y obtenga una clave API con permiso de envío.
2. En **Streamlit → Settings → Secrets**, agregue esta sección; la clave real no se coloca en GitHub ni en el formulario:

```toml
[email]
resend_api_key = "TU_CLAVE_API_RESEND"
from_email = "caudales@OSgam"
from_name = "OS GAM · Caudales"
test_mode = true
test_recipient = "CORREO_CON_EL_QUE_CREASTE_TU_CUENTA_RESEND"
reply_to = ""
dashboard_url = ""
```

3. Abra Dashboard, aplique los filtros, revise la vista previa y pulse **Enviar reporte por correo**. El modo de prueba usa automáticamente **onboarding@resend.dev** y solo permite el correo de la cuenta Resend, sin copias.
4. Consulte **Consultar historial de correos** y compruebe la recepción en su bandeja, incluyendo correo no deseado.

`caudales@OSgam` expresa el nombre deseado, pero **no contiene un dominio completo verificable**. Se conserva como remitente previsto y nunca se utiliza para un envío de producción mientras esté incompleto. No se agrega ni registra automáticamente una extensión de dominio.

### Producción con remitente propio

Verifique un dominio que controle en Resend mediante los registros DNS solicitados. Actualice `from_email` a la dirección completa sobre ese dominio y establezca `test_mode = false`. Puede configurar `reply_to` con un buzón existente y `dashboard_url` con la URL pública del aplicativo para incluir el botón **Consultar Dashboard**. Los destinatarios se ingresan como direcciones completas separadas por coma, punto y coma o salto de línea; se admiten hasta 50 incluyendo las copias.

El envío se ejecuta desde Python en el servidor de Streamlit usando la API HTTPS de Resend. No depende de Outlook ni del agente SharePoint. También se admiten variables de entorno: `RESEND_API_KEY`, `EMAIL_FROM`, `EMAIL_FROM_NAME`, `EMAIL_REPLY_TO`, `DASHBOARD_URL`, `EMAIL_TEST_MODE`, `EMAIL_TEST_RECIPIENT`.

### Estados y reintentos

- **Preparado**: solicitud registrada antes de contactar al proveedor.
- **Aceptado por Resend**: el proveedor devolvió un identificador. No confirma entrega en la bandeja del destinatario.
- **Error**: respuesta de rechazo o validación.
- **Sin confirmación**: timeout o respuesta incierta; debe verificarse en Resend o reintentarse la misma solicitud.

Cada solicitud conserva su identificador de idempotencia y contenido en los reintentos. Un envío aceptado deshabilita el botón; **Preparar otro envío** inicia una solicitud nueva de forma explícita. Después de 23 horas se bloquea el reintento para evitar exceder la vigencia de 24 horas de idempotencia de Resend. El historial no utiliza webhooks de entrega en esta versión. La cuota efectiva corresponde a la cuenta Resend; se deben consultar sus límites y consumo allí.

## Seguridad

- No se escriben cambios en la geodatabase.
- SQL Server no necesita quedar expuesto a Internet.
- Los secretos quedan fuera del repositorio.
- Los HTML externos se muestran dentro de un iframe con `sandbox`.
- El bucket de gráficos es privado.
- La `service_role_key` permanece únicamente del lado servidor.
- Puede habilitarse una contraseña básica mediante `[app].password`.
