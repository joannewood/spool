# Stops and removes the SPOOL host-helper background process and its
# Startup-folder launcher. Windows equivalent of uninstall.sh.

$ErrorActionPreference = "SilentlyContinue"

$InstallDir = Join-Path $env:LOCALAPPDATA "spool-host-helper"
$StartupDir = [Environment]::GetFolderPath("Startup")
$LauncherPath = Join-Path $StartupDir "spool-host-helper.vbs"

Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" |
  Where-Object { $_.CommandLine -and $_.CommandLine.Contains("host_helper_windows.py") } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

Remove-Item -Path $LauncherPath -Force
Remove-Item -Path $InstallDir -Recurse -Force

Write-Host "host-helper stopped and uninstalled"
