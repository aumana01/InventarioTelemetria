# Seguimiento de Caudalímetros

Aplicación Streamlit para control técnico e historial de caudalímetros del AyA.

## Funcionalidad

- Lee todos los atributos de `AYA.MSG_Medidores_de_Caudal` desde SQL Server, excluyendo `SHAPE`.
- Obtiene `SHAPE.STX` / `SHAPE.STY` y transforma CRTM05 EPSG:5367 a WGS84 EPSG:4326.
- Presenta mapa y atributos de geodatabase en modo solo lectura.
- Registra revisiones históricas en Supabase sin modificar la geodatabase.
- Controla rectificación simultánea, equipo utilizado, condición ultrasónica, circunferencia, espesor, distancia de transductores, calidad de medición, último mantenimiento y fallas.
- Permite cargar un HTML comparativo y almacenarlo en un bucket privado de Supabase.
- Muestra el HTML directamente dentro de la ficha mediante un iframe `sandbox`.
- Incluye una integración opcional con Microsoft List mediante SharePoint REST y una aplicación Microsoft Entra. No depende del conector de SharePoint de ChatGPT.
- Incluye vista de diagnóstico para SQL Server, Supabase y la integración opcional con Microsoft List.

## Arquitectura

```
Geodatabase SQL Server (solo lectura)
            |
            v
        Streamlit
       /    |     \
      /     |      \
  mapa   formulario  ficha
            |
            v
       Supabase
  PostgreSQL + Storage

Microsoft List
(opcional por REST)
```

GitHub contiene **el código fuente**, pero no sustituye la conectividad con el SQL Server interno. El servidor que ejecute Streamlit debe poder resolver y alcanzar el host SQL institucional.

## 1. Supabase

Abra el SQL Editor del proyecto Supabase y ejecute:

`supabase_schema.sql`

Esto crea:

- tabla `public.caudalimetro_revisiones`;
- índice por caudalímetro y fecha;
- bucket privado `caudalimetros-graficos`.

La aplicación usa una `service_role_key` únicamente del lado servidor. No debe colocarse en código fuente, HTML o JavaScript.

## 2. Configuración

Copie:

`.streamlit/secrets.example.toml`

a:

`.streamlit/secrets.toml`

y complete los valores reales.

La contraseña SQL que se haya utilizado en pruebas anteriores **no está incluida** en este repositorio.

### SQL

Configure el driver ODBC instalado en el servidor. En el entorno AyA actualmente puede utilizarse, por ejemplo:

`ODBC Driver 13 for SQL Server`

La clave de identificación del caudalímetro se intenta tomar de `Código_Caudalimetro`; si esa columna no existe, el aplicativo busca claves comunes como `OBJECTID`, `GlobalID` o `ID`.

## 3. Microsoft List: opcional

El aplicativo funciona completamente sin Microsoft List mediante carga manual del HTML.

Si posteriormente se desea consultar la lista:

`Seguimiento de Detección de Fugas GAM`

se debe registrar una aplicación en Microsoft Entra ID y configurar:

- `tenant_id`
- `client_id`
- `client_secret`

con permisos autorizados sobre el sitio SharePoint correspondiente.

La aplicación consulta el ID del elemento y sus `AttachmentFiles`, busca un archivo `.html` o `.htm` y lo muestra en la ficha. Para este origen se guarda la referencia del ID, no una copia adicional del archivo en Supabase.

## 4. Ejecución local

Desde esta carpeta:

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
streamlit run app.py
```

En Linux:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
streamlit run app.py
```

## 5. Modo demo

Permite probar interfaz, mapa y validaciones sin conexión SQL:

Windows CMD:

```cmd
set APP_DEMO_MODE=true
streamlit run app.py
```

PowerShell:

```powershell
$env:APP_DEMO_MODE="true"
streamlit run app.py
```

## 6. Despliegue recomendado

Para producción se recomienda ejecutar Streamlit en una VM o servidor dentro de la red AyA que tenga:

1. acceso de red a SQL Server;
2. Python 3.11+;
3. el driver ODBC requerido;
4. acceso HTTPS a Supabase;
5. secretos configurados fuera de GitHub.

GitHub debe usarse como repositorio de código y control de versiones. Si el SQL Server no es accesible desde Internet, un despliegue estándar en Streamlit Community Cloud no podrá consultarlo directamente sin VPN, túnel o una API intermedia segura.

## 7. Pruebas

```bash
PYTHONPATH=. pytest -q
```

El workflow de GitHub además:

- compila los módulos Python;
- ejecuta las pruebas unitarias;
- inicia Streamlit en modo demo;
- consulta `/_stcore/health`.

## Seguridad

- No se escriben cambios en la geodatabase.
- Los secretos quedan fuera del repositorio.
- Los HTML externos se muestran dentro de un iframe con `sandbox`.
- El bucket de gráficos es privado.
- Puede habilitarse una contraseña básica de acceso mediante `[app].password`; para un despliegue institucional se recomienda además protección de red o autenticación corporativa delante de Streamlit.
