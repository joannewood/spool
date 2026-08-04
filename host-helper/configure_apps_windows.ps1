# Configures SPOOL's "Open in..." apps on Windows via native file-picker
# dialogs instead of Python-based auto-detection (host-helper/
# configure_apps.py's Windows path) -- lets setup.ps1, and this project's
# whole Windows install flow, avoid depending on Python at all just to
# pick a CAD app and a slicer. Safe to re-run any time; run standalone
# (powershell -ExecutionPolicy Bypass -File host-helper\configure_apps_windows.ps1)
# or via setup.ps1.
#
# configure_apps.py still exists and still works on Windows (auto-scans
# Program Files and asks you to confirm/pick from a list) -- this script
# doesn't replace it, it's just what setup.ps1 calls by default now, so a
# fresh Windows setup never needs Python installed at all. Prefer
# configure_apps.py's scan-and-confirm flow instead? Run it directly with
# Python installed; both write to the exact same files in the exact same
# format, so it's fine to use either one, including switching between them
# across separate runs.

# See setup.ps1's own header comment for why this trap exists -- same
# "the window just vanishes on any uncaught error" risk applies here too,
# since this script is runnable standalone as well as via setup.ps1.
trap {
    Write-Host ""
    Write-Host "This hit an unexpected error and has to stop:" -ForegroundColor Red
    Write-Host "  $($_.Exception.Message)" -ForegroundColor Red
    Write-Host ""
    Write-Host "Where it happened:" -ForegroundColor DarkGray
    Write-Host "  $($_.InvocationInfo.PositionMessage)" -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "Please screenshot this and let Jo know (or open a GitHub issue)." -ForegroundColor Yellow
    if (-not $env:CI) {
        Write-Host ""
        Write-Host "Press Enter to close this window."
        Read-Host | Out-Null
    }
    exit 1
}

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName Microsoft.VisualBasic

$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$HostHelperTarget = Join-Path $RepoRoot "host-helper\host_helper_windows.py"
$HostHelperClientPy = Join-Path $RepoRoot "services\api\spool_api\host_helper_client.py"
$IconsDir = Join-Path $RepoRoot "services\api\spool_api\static\icons"

# label, extensions handled -- same three groups as configure_apps.py's
# GROUPS (kept in sync by hand; small and stable enough that a shared
# file across a Python script and a PowerShell script wasn't worth the
# indirection).
$AppGroups = @(
    @{ Label = "CAD app"; Extensions = @(".step", ".stp", ".f3d"); Hint = ".step / .stp / .f3d files" },
    @{ Label = "OpenSCAD"; Extensions = @(".scad"); Hint = ".scad files" },
    @{ Label = "Slicer app"; Extensions = @(".stl", ".3mf", ".svg", ".gcode", ".obj"); Hint = ".stl / .3mf / .svg / .gcode / .obj files" }
)

# A version number ("23.1.1.100") or hex build hash as an exe's immediate
# parent folder name -- confirmed against Autodesk Fusion's real webdeploy
# layout, where the actual .exe sits in exactly such a folder. Matches
# configure_apps.py's _MEANINGLESS_FOLDER_RE exactly, same reasoning: using
# that folder name as the label would show something meaningless in
# SPOOL's UI, so fall back to the exe's own filename instead.
function Get-DefaultAppLabel($exePath) {
    $parent = Split-Path -Path (Split-Path -Path $exePath -Parent) -Leaf
    if ($parent -and $parent -notmatch '^[0-9a-fA-F]{6,}$' -and $parent -notmatch '^[\d.]+$') {
        return $parent
    }
    return [System.IO.Path]::GetFileNameWithoutExtension($exePath)
}

function Select-AppExecutable($groupLabel, $hint) {
    # A real tester reported the file dialog opening behind other windows
    # ("you see a file explorer window but have to go and look for the
    # prompt dialog") -- OpenFileDialog.ShowDialog() with no owner has no
    # window to anchor its Z-order to, especially when launched from a
    # background/detached process the way setup.ps1 does. A hidden,
    # TopMost owner form fixes this: passing it to ShowDialog(owner)
    # ties the dialog to a real foreground window instead of floating
    # with no anchor.
    $owner = New-Object System.Windows.Forms.Form
    $owner.TopMost = $true
    $owner.ShowInTaskbar = $false
    $owner.StartPosition = "CenterScreen"
    $owner.WindowState = "Minimized"
    $owner.Show()
    $owner.Activate()

    $dialog = New-Object System.Windows.Forms.OpenFileDialog
    # Explicit about needing the .exe specifically, not the app's folder --
    # a real tester wasn't sure which to pick ("not clear whether to point
    # to folder or executable").
    $dialog.Title = "Select the $groupLabel's .exe file (for $hint) -- look inside its install folder -- Cancel to skip"
    $dialog.Filter = "Programs (*.exe)|*.exe|All files (*.*)|*.*"
    $dialog.CheckFileExists = $true
    if (Test-Path $env:ProgramFiles) { $dialog.InitialDirectory = $env:ProgramFiles }
    $result = $dialog.ShowDialog($owner)
    $owner.Close()
    if ($result -eq [System.Windows.Forms.DialogResult]::OK) {
        return $dialog.FileName
    }
    return $null
}

# .NET's simplest icon-extraction API, built into every Windows
# PowerShell install -- no extra dependency needed, unlike
# configure_apps.py's Windows path, which has no icon extraction at all
# (its own comment: "extraction is macOS-only for now"). Typically
# returns a 32x32 icon (Windows' "associated icon" convention) --
# smaller than the Mac side's 64x64 (sips downscales a much larger
# source .icns), but a real extracted icon beats the plain two-letter
# badge fallback either way; the UI already scales icons down to fit
# their button regardless of source size. Never fatal on failure -- same
# "just falls back to the badge" treatment as a skipped Mac extraction.
function Get-IconSlug($appName) {
    return ($appName.ToLower() -replace '[^a-z0-9]+', '-').Trim('-')
}

function Export-AppIcon($appName, $exePath) {
    try {
        $icon = [System.Drawing.Icon]::ExtractAssociatedIcon($exePath)
        if ($null -eq $icon) { return $null }
        $bitmap = $icon.ToBitmap()
        $slug = Get-IconSlug $appName
        New-Item -ItemType Directory -Force -Path $IconsDir | Out-Null
        $outPath = Join-Path $IconsDir "$slug.png"
        $bitmap.Save($outPath, [System.Drawing.Imaging.ImageFormat]::Png)
        $bitmap.Dispose()
        $icon.Dispose()
        return "$slug.png"
    } catch {
        return $null
    }
}

function Confirm-AppLabel($default) {
    $typed = [Microsoft.VisualBasic.Interaction]::InputBox("Name to show in SPOOL for this app:", "SPOOL Setup", $default)
    if ([string]::IsNullOrWhiteSpace($typed)) { return $default }
    return $typed
}

# Matches configure_apps.py's _quote()/format_dict() exactly, so either
# script can write (and the other can safely re-write) the same block.
function ConvertTo-PyQuoted($s) {
    $escaped = $s -replace '\\', '\\'
    $escaped = $escaped -replace '"', '\"'
    return '"' + $escaped + '"'
}

function Format-PyDict($varName, $mapping) {
    $lines = New-Object System.Collections.Generic.List[string]
    $lines.Add("$varName = {")
    foreach ($key in $mapping.Keys) {
        $lines.Add("    $(ConvertTo-PyQuoted $key): $(ConvertTo-PyQuoted $mapping[$key]),")
    }
    $lines.Add("}")
    return ($lines -join "`n")
}

# Same BEGIN/END marker convention as configure_apps.py's replace_block()
# -- substring-splice rather than a regex -replace, specifically to avoid
# .NET regex replacement-string special-casing of "$" in the new content
# (an app label or path is very unlikely to contain one, but this avoids
# needing to reason about it at all).
function Set-PyBlock($path, $marker, $newBody) {
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    $text = [System.IO.File]::ReadAllText($path, $utf8NoBom)
    $pattern = "(?s)# ${marker}:BEGIN.*?# ${marker}:END"
    $match = [regex]::Match($text, $pattern)
    if (-not $match.Success) {
        throw "marker $marker not found in $path -- was it edited by hand into a different shape?"
    }
    $replacement = "# ${marker}:BEGIN (auto-generated by host-helper/configure_apps_windows.ps1 -- edit here directly, or just re-run that script)`n$newBody`n# ${marker}:END"
    $newText = $text.Substring(0, $match.Index) + $replacement + $text.Substring($match.Index + $match.Length)
    [System.IO.File]::WriteAllText($path, $newText, $utf8NoBom)
}

Write-Host ""
Write-Host "For each app below, a file browser window will open -- navigate to"
Write-Host "where that app is installed and select its .exe file directly (not"
Write-Host "the folder it's in). Cancel skips that one."
Write-Host ""

$AppMap = [ordered]@{}    # ext -> label
$AppPaths = [ordered]@{}  # label -> exe path
$AppIcons = [ordered]@{}  # label -> icon filename

foreach ($group in $AppGroups) {
    $rawExePath = Select-AppExecutable $group.Label $group.Hint
    if (-not $rawExePath) {
        Write-Host "$($group.Label): skipped"
        continue
    }
    # APP_PATHS values use forward slashes, matching every other
    # Windows-host path in this project (host_helper_windows.py's own
    # docstring, DROPFOLDER_HOST_PATH, etc.) -- os.path.isfile/subprocess
    # on Windows accept forward slashes just as readily as backslashes,
    # so this is purely for consistency with the rest of the codebase.
    # Icon extraction below deliberately uses $rawExePath (real
    # backslashes) instead, since that's a plain Windows file path, not
    # a value this project's own path conventions apply to.
    $exePath = $rawExePath -replace '\\', '/'
    $defaultLabel = Get-DefaultAppLabel $exePath
    $label = Confirm-AppLabel $defaultLabel
    $AppPaths[$label] = $exePath
    $iconFile = Export-AppIcon $label $rawExePath
    if ($iconFile) { $AppIcons[$label] = $iconFile }
    foreach ($ext in $group.Extensions) { $AppMap[$ext] = $label }
    Write-Host "$($group.Label): $label ($exePath)"
}

if ($AppMap.Count -eq 0) {
    Write-Host ""
    Write-Host "No apps configured -- 'Open in...' buttons won't do anything until you edit"
    Write-Host "host-helper\host_helper_windows.py's APP_MAP by hand, or re-run this script."
    exit 0
}

Set-PyBlock $HostHelperClientPy "APP_MAP" (Format-PyDict "APP_MAP" $AppMap)
Set-PyBlock $HostHelperTarget "APP_MAP" (Format-PyDict "APP_MAP" $AppMap)
Set-PyBlock $HostHelperTarget "APP_PATHS" (Format-PyDict "APP_PATHS" $AppPaths)
# APP_ICONS only exists in host_helper_client.py (an api-side UI concern --
# host_helper_windows.py itself never needs to know an app has an icon,
# only how to launch it) -- if every app's icon extraction failed for some
# reason, leave the existing block alone rather than overwriting real
# icons with an empty dict.
if ($AppIcons.Count -gt 0) {
    Set-PyBlock $HostHelperClientPy "APP_ICONS" (Format-PyDict "APP_ICONS" $AppIcons)
}

Write-Host ""
Write-Host "Configured:"
foreach ($ext in $AppMap.Keys) {
    Write-Host "  $ext -> $($AppMap[$ext])"
}
if ($AppIcons.Count -lt $AppPaths.Count) {
    Write-Host ""
    Write-Host "Note: couldn't extract a real icon for every app -- any without one"
    Write-Host "just shows a plain badge in SPOOL instead, nothing else is affected."
}
Write-Host ""
Write-Host "Re-run host-helper\install_windows.ps1 and rebuild the api container"
Write-Host "(docker compose up -d --build api) to pick this up."
