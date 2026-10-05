@echo off
setlocal
cd /d "%~dp0"

for /f "usebackq delims=" %%P in (`python -c "import pathlib,sys; print(pathlib.Path(sys.executable).with_name('pythonw.exe'))"`) do set "PYTHONW=%%P"

if not exist "%PYTHONW%" (
  echo No se encontro pythonw.exe.
  pause
  exit /b 1
)

start "" "%PYTHONW%" "%CD%\agent.py"
echo Agente SharePoint iniciado.
