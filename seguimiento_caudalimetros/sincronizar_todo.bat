@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo SINCRONIZACION SEGUIMIENTO DE CAUDALIMETROS
echo ============================================================
echo.

echo [1/2] Sincronizando inventario SQL AyA -^> Supabase...
python sincronizar_caudalimetros.py
if errorlevel 1 (
    echo.
    echo ERROR en la sincronizacion del inventario.
    pause
    exit /b 1
)

echo.
echo [2/2] Sincronizando HTML SharePoint -^> Supabase...
python sincronizar_html_sharepoint.py
if errorlevel 1 (
    echo.
    echo La sincronizacion de HTML termino con uno o mas errores.
    pause
    exit /b 1
)

echo.
echo Sincronizacion completa.
pause
