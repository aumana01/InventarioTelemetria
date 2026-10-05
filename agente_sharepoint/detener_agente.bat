@echo off
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*agente_sharepoint*agent.py*' } | ForEach-Object { Invoke-CimMethod -InputObject $_ -MethodName Terminate | Out-Null }"
echo Agente detenido.
pause
