param(
    [Parameter(Mandatory=$true)][string]$PythonwPath,
    [Parameter(Mandatory=$true)][string]$AgentPath,
    [Parameter(Mandatory=$true)][string]$WorkingDirectory
)

$startup = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startup "Agente SharePoint Caudalimetros.lnk"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $PythonwPath
$shortcut.Arguments = '"' + $AgentPath + '"'
$shortcut.WorkingDirectory = $WorkingDirectory
$shortcut.WindowStyle = 7
$shortcut.Save()
Write-Host "Inicio automatico configurado:" $shortcutPath
