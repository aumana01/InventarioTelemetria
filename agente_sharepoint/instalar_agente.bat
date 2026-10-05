@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo INSTALACION - AGENTE SHAREPOINT CAUDALIMETROS
echo ============================================================
echo.

python -m pip install -r requirements.txt
if errorlevel 1 (
  echo Error instalando dependencias.
  pause
  exit /b 1
)

if not exist agent_secrets.toml (
  copy /Y agent_secrets.example.toml agent_secrets.toml >nul
  echo.
  echo Se creo agent_secrets.toml.
  echo Complete URL y service_role_key de Supabase.
  start "" notepad agent_secrets.toml
  echo.
  pause
)

echo.
echo Configurando sesion Microsoft 365...
python configurar_sesion.py
if errorlevel 1 (
  echo No fue posible configurar la sesion.
  pause
  exit /b 1
)

for /f "usebackq delims=" %%P in (`python -c "import pathlib,sys; print(pathlib.Path(sys.executable).with_name('pythonw.exe'))"`) do set "PYTHONW=%%P"

powershell -NoProfile -ExecutionPolicy Bypass -File "%CD%\instalar_inicio_windows.ps1" ^
  -PythonwPath "%PYTHONW%" ^
  -AgentPath "%CD%\agent.py" ^
  -WorkingDirectory "%CD%"

call iniciar_agente.bat

echo.
echo Instalacion completada. El agente iniciara automaticamente con Windows.
pause
