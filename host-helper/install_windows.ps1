# Installs the SPOOL host-helper as a background process that starts
# automatically at login - the Windows equivalent of install.sh's launchd
# agent. Safe to re-run (stops any already-running instance before
# starting a fresh one, and each run re-copies host_helper_windows.py so
# code changes take effect).
#
# If Windows refuses to run this at all ("running scripts is disabled on
# this system"), that's PowerShell's default execution policy blocking
# unsigned scripts - run this first, in the same window, before trying
# again (only affects this one PowerShell process, not your whole
# machine):
#  Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

$ErrorActionPreference = "Stop"

$Dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$EnvFile = Join-Path $Dir "..\.env"

if (-not (Test-Path $EnvFile)) {
  Write-Error "error: $EnvFile not found - copy .env.example to .env and set your real paths first"
  exit 1
}

# Same three host paths docker-compose.yml reads from .env, so the
# delete-allowlist in host_helper_windows.py (ALLOWED_DELETE_ROOTS)
# matches what's actually mounted into the containers rather than being
# hardcoded to one machine's paths - same reasoning as install.sh's own
# read_env_var, just read with PowerShell instead of sed.
function Read-EnvVar($name) {
  $line = Get-Content $EnvFile | Where-Object { $_ -match "^$name=" } | Select-Object -First 1
  if ($line) { return ($line -replace "^$name=", "").Trim() }
  return $null
}

$DropfolderHostPath = Read-EnvVar "DROPFOLDER_HOST_PATH"
$LibraryHostPath = Read-EnvVar "LIBRARY_HOST_PATH"
$DownloadsHostPath = Read-EnvVar "DOWNLOADS_HOST_PATH"

# Only DROPFOLDER_HOST_PATH is required -- LIBRARY_HOST_PATH/
# DOWNLOADS_HOST_PATH may be blank (skipped entirely, see
# db/migrations/003_seed_watched_roots.sh), in which case they're just
# passed through as empty strings below; host_helper_windows.py's
# ALLOWED_DELETE_ROOTS already filters out any blank entry.
if ([string]::IsNullOrWhiteSpace($DropfolderHostPath)) {
    Write-Error "error: DROPFOLDER_HOST_PATH is not set in $EnvFile"
    exit 1
}

# macOS's install.sh copies host_helper.py out of ~/Documents to dodge a
# TCC read-permission quirk that's specific to that OS's privacy model - 
# Windows has no equivalent restriction, but copying it out to a stable
# location is still good practice (the source repo folder could get moved
# or deleted without this breaking).
$InstallDir = Join-Path $env:LOCALAPPDATA "spool-host-helper"
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Copy-Item -Path (Join-Path $Dir "host_helper_windows.py") -Destination (Join-Path $InstallDir "host_helper_windows.py") -Force
$ScriptPath = Join-Path $InstallDir "host_helper_windows.py"

$PythonCmd = Get-Command pythonw -ErrorAction SilentlyContinue
if (-not $PythonCmd) {
  $PythonCmd = Get-Command python -ErrorAction SilentlyContinue
}
if (-not $PythonCmd) {
  Write-Error "error: python isn't installed or isn't on PATH - install it from https://www.python.org/downloads/ (check ""Add python.exe to PATH"" during install), then re-run this script."
  exit 1
}

# VBS string literals escape an embedded double-quote as two double-quotes
# ("" -> a literal "). Used both for the command line handed to
# objShell.Run (itself needs its two paths individually quoted, since
# either can contain spaces) and for the three env var values.
function ConvertTo-VbsQuoted($s) {
  return '"' + ($s -replace '"', '""') + '"'
}

$CommandLine = "`"$($PythonCmd.Source)`" `"$ScriptPath`""
$VbsRunArg = ConvertTo-VbsQuoted $CommandLine

# A VBS launcher (not a plain .lnk shortcut) specifically so it can set
# the three watched-root env vars right before starting the script - 
# mirrors how install.sh injects them into the launchd plist's own
# EnvironmentVariables dict, since a Startup-folder item has no
# equivalent field of its own. Runs with window style 0 (hidden), so
# nothing flashes on screen at every login; there's deliberately no log
# redirection here (nested quoting a shell-redirected command inside a
# VBS string gets fragile fast) - run `python host_helper_windows.py`
# directly from a terminal instead if you need to see its output while
# debugging.
$VbsContent = @"
Set objShell = CreateObject("WScript.Shell")
objShell.Environment("Process")("DROPFOLDER_HOST_PATH") = $(ConvertTo-VbsQuoted $DropfolderHostPath)
objShell.Environment("Process")("LIBRARY_HOST_PATH") = $(ConvertTo-VbsQuoted $LibraryHostPath)
objShell.Environment("Process")("DOWNLOADS_HOST_PATH") = $(ConvertTo-VbsQuoted $DownloadsHostPath)
objShell.Run $VbsRunArg, 0, False
"@

$StartupDir = [Environment]::GetFolderPath("Startup")
$LauncherPath = Join-Path $StartupDir "spool-host-helper.vbs"
Set-Content -Path $LauncherPath -Value $VbsContent -Encoding ASCII

# Stop any already-running instance so re-running this script (e.g. after
# editing host_helper_windows.py) takes effect immediately rather than
# only at next login.
Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -and $_.CommandLine.Contains("host_helper_windows.py") } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Milliseconds 500

$Shell = New-Object -ComObject WScript.Shell
$Shell.Run("wscript.exe `"$LauncherPath`"", 0, $false) | Out-Null

Write-Host "host-helper installed and running (starts automatically at login)"
Write-Host "script: $ScriptPath"
Write-Host "startup launcher: $LauncherPath"
Write-Host "re-run this script after editing host_helper_windows.py or .env to pick up changes"
Write-Host "to debug: run '$($PythonCmd.Source) `"$ScriptPath`"' directly in a terminal to see its output"
