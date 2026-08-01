# Interactive, guided setup for SPOOL on Windows -- the automated
# equivalent of the README's manual setup steps. Safe to re-run any time
# (e.g. after downloading an updated copy of SPOOL): it detects an
# existing .env and offers to keep it rather than clobbering your
# configuration. The manual, step-by-step process in the README still
# works exactly as documented if you'd rather do this by hand.
#
# If Windows refuses to run this at all ("running scripts is disabled on
# this system"), that's PowerShell's default execution policy blocking
# unsigned scripts -- run this first, in the same window, before trying
# again (only affects this one PowerShell process, not your whole
# machine):
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

$ErrorActionPreference = "Stop"
$Dir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Dir

function Step($msg) { Write-Host ""; Write-Host "==> $msg" -ForegroundColor Cyan }
function Note($msg) { Write-Host "    $msg" -ForegroundColor DarkGray }

# Native dialogs instead of reading stdin -- this script never reads input
# from the console at all now, so it works identically whether run from a
# PowerShell window or from inside a wrapped installer (e.g. an Inno Setup
# .exe running this as a post-install step), which isn't something to
# depend on forwarding keystrokes correctly. Loaded once up front since
# Read-YesNo's first real call (the "keep existing .env?" prompt) happens
# before Select-Folder's own later Add-Type call used to.
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

function Read-YesNo($prompt, $defaultYes = $true) {
    $buttons = [System.Windows.Forms.MessageBoxButtons]::YesNo
    $icon = [System.Windows.Forms.MessageBoxIcon]::Question
    $defaultButton = if ($defaultYes) {
        [System.Windows.Forms.MessageBoxDefaultButton]::Button1
    } else {
        [System.Windows.Forms.MessageBoxDefaultButton]::Button2
    }
    $result = [System.Windows.Forms.MessageBox]::Show($prompt, "SPOOL Setup", $buttons, $icon, $defaultButton)
    return $result -eq [System.Windows.Forms.DialogResult]::Yes
}

# For the one destructive prompt -- MessageBox can't relabel its buttons
# ("Yes"/"No" only), so this builds a small custom dialog instead, so the
# affirmative button reads "Delete Everything" rather than a bare "Yes"
# and the stakes are clear from the dialog alone. Enter/Escape/closing the
# window all resolve to the safe Cancel option, matching the original
# prompt's "press Enter to stop" default.
function Confirm-Destructive($message) {
    $form = New-Object System.Windows.Forms.Form
    $form.Text = "SPOOL Setup"
    $form.StartPosition = "CenterScreen"
    $form.FormBorderStyle = "FixedDialog"
    $form.MaximizeBox = $false
    $form.MinimizeBox = $false
    $form.TopMost = $true
    $form.ClientSize = New-Object System.Drawing.Size(440, 190)

    $label = New-Object System.Windows.Forms.Label
    $label.Text = $message
    $label.SetBounds(20, 15, 400, 120)
    $form.Controls.Add($label)

    $cancelButton = New-Object System.Windows.Forms.Button
    $cancelButton.Text = "Cancel"
    $cancelButton.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
    $cancelButton.SetBounds(180, 145, 100, 30)
    $form.Controls.Add($cancelButton)
    $form.CancelButton = $cancelButton
    $form.AcceptButton = $cancelButton

    $deleteButton = New-Object System.Windows.Forms.Button
    $deleteButton.Text = "Delete Everything"
    $deleteButton.DialogResult = [System.Windows.Forms.DialogResult]::Yes
    $deleteButton.SetBounds(290, 145, 130, 30)
    $form.Controls.Add($deleteButton)

    $result = $form.ShowDialog()
    return $result -eq [System.Windows.Forms.DialogResult]::Yes
}

# ---- Step 1: Docker Desktop ----------------------------------------------

Step "Checking for Docker Desktop"

$DockerCmd = Get-Command docker -ErrorAction SilentlyContinue
if (-not $DockerCmd) {
    Write-Host "Docker isn't installed."
    Note "Download Docker Desktop for Windows from https://www.docker.com/products/docker-desktop/"
    Note "then run this script again."
    Start-Process "https://www.docker.com/products/docker-desktop/"
    exit 1
}

function Test-DockerRunning {
    docker info 2>$null 1>$null
    return $LASTEXITCODE -eq 0
}

if (-not (Test-DockerRunning)) {
    Write-Host "Docker Desktop isn't running -- starting it now..."
    $DockerExe = "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe"
    if (Test-Path $DockerExe) {
        Start-Process $DockerExe
    } else {
        Note "Couldn't find Docker Desktop at the usual location -- open it yourself from the Start menu."
    }
    Write-Host -NoNewline "Waiting for Docker to be ready"
    $ready = $false
    for ($i = 0; $i -lt 60; $i++) {
        if (Test-DockerRunning) { $ready = $true; break }
        Write-Host -NoNewline "."
        Start-Sleep -Seconds 2
    }
    Write-Host ""
    if (-not $ready) {
        Write-Host "Docker Desktop still isn't responding after two minutes."
        Note "Open Docker Desktop from the Start menu yourself, wait for it to say"
        Note "it's running, then run this script again."
        exit 1
    }
} else {
    Write-Host "Docker is running."
}

# ---- Step 2: .env ---------------------------------------------------------

Step "Configuring your folders"

$Reconfigure = $true
if (Test-Path ".env") {
    Write-Host "Found an existing .env file."
    $Reconfigure = -not (Read-YesNo "Keep it as-is?")
    if (-not $Reconfigure) { Write-Host "Keeping your existing .env -- skipping folder setup." }
}

function Select-Folder($description, $default) {
    # FolderBrowserDialog needs an STA thread -- Windows PowerShell 5.1
    # (the default on most Windows installs, what most people get from
    # right-click > "Run with PowerShell") already runs as STA, but
    # PowerShell 7's "pwsh" defaults to MTA and would throw here instead.
    # Falls back to a typed-path dialog either way rather than failing
    # the whole script over one folder prompt -- Microsoft.VisualBasic's
    # InputBox rather than Read-Host, for the same stdin-independence
    # reason the Yes/No prompts above were converted.
    try {
        $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
        $dialog.Description = $description
        $dialog.ShowNewFolderButton = $true
        if (Test-Path $default) { $dialog.SelectedPath = $default }
        $result = $dialog.ShowDialog()
        if ($result -eq [System.Windows.Forms.DialogResult]::OK) {
            return $dialog.SelectedPath
        }
        return $default
    } catch {
        Write-Host "Couldn't open a folder picker window (this can happen under PowerShell 7's 'pwsh' -- try re-running this script with plain 'powershell.exe' instead if you'd rather use the picker)."
        Add-Type -AssemblyName Microsoft.VisualBasic
        $typed = [Microsoft.VisualBasic.Interaction]::InputBox("Type the full folder path instead:", "SPOOL Setup", $default)
        if ([string]::IsNullOrWhiteSpace($typed)) { return $default }
        return $typed
    }
}

if ($Reconfigure) {
    # Safety net for the most likely way to lose data without realizing
    # it: docker-compose.yml pins the project name to "spool" (see its
    # own comment) specifically so your database survives a downloaded
    # update landing in a differently-named folder -- but that only
    # helps if this fresh setup doesn't also generate a *new* database
    # password that can't authenticate against that already-existing
    # database. Detected by checking for the volume before writing
    # anything.
    docker volume inspect spool_pgdata 2>$null 1>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host ""
        Write-Host "Found an existing SPOOL database from a previous setup, but there's"
        Write-Host "no .env in this folder yet to match it. This usually means you're"
        Write-Host "running setup fresh after downloading an update into a new folder."
        Write-Host ""
        Write-Host "If you want to keep your existing library: stop now, and see"
        Write-Host "'Updating SPOOL' in README.md instead -- copying your old .env into"
        Write-Host "this folder keeps everything. Generating a new one here instead"
        Write-Host "cannot connect to that existing database (the password won't match),"
        Write-Host "and continuing anyway means permanently deleting it first."
        Write-Host ""
        $confirmWipe = Confirm-Destructive "Found an existing SPOOL database from a previous setup, but there's no .env in this folder yet to match it.`n`nIf you want to keep your existing library, stop now and see 'Updating SPOOL' in README.md instead. Continuing here permanently deletes that existing database."
        if ($confirmWipe) {
            Write-Host "Removing the old database..."
            docker volume rm spool_pgdata spool_thumbnails 2>$null 1>$null
            Write-Host "Done -- continuing with a fresh setup."
        } else {
            Write-Host "Stopping -- nothing has been changed. See README.md's 'Updating SPOOL' section."
            exit 1
        }
    }

    if (-not (Test-Path ".env") -and (Test-Path ".env.example")) {
        Copy-Item ".env.example" ".env"
    }

    Write-Host ""
    Write-Host "A folder picker will pop up for each folder below -- navigate to (or use"
    Write-Host "its 'Make New Folder' button to create) the right one, then click OK."
    Write-Host ""

    Note "1 of 3 -- your drop folder (where new downloads/exports land to be indexed)"
    Write-Host "This one's required -- it's SPOOL's main working folder."
    $DefaultDrop = Join-Path $env:USERPROFILE "Documents\3DPrintFiles"
    New-Item -ItemType Directory -Force -Path $DefaultDrop | Out-Null
    $DropfolderHostPath = Select-Folder "Choose your SPOOL drop folder" $DefaultDrop

    Note "2 of 3 -- your existing 3D print library (optional; read-only, SPOOL only indexes it)"
    $LibraryHostPath = ""
    if (Read-YesNo "Do you have an existing 3D print library folder you'd like SPOOL to index too?" $false) {
        $DefaultLibrary = Join-Path $env:USERPROFILE "Documents\3D Printing"
        New-Item -ItemType Directory -Force -Path $DefaultLibrary | Out-Null
        $LibraryHostPath = Select-Folder "Choose your existing 3D print library folder" $DefaultLibrary
    } else {
        Write-Host "    skipping -- SPOOL will only watch your drop folder for now. You can add"
        Write-Host "    this later; see 'Known limitations' in README.md for how."
    }

    Note "3 of 3 -- your Downloads folder (optional; new model files here get moved into your drop folder)"
    $DownloadsHostPath = ""
    if (Read-YesNo "Auto-move new 3D-print files out of your Downloads folder into your drop folder?") {
        $DownloadsHostPath = Join-Path $env:USERPROFILE "Downloads"
        Write-Host "    using $DownloadsHostPath"
    } else {
        Write-Host "    skipping -- you can add this later; see 'Known limitations' in README.md for how."
    }

    # Docker Compose (and this project's own container-side code, see
    # common/paths.py) both work fine with forward slashes in a Windows
    # path, but NOT with backslashes read as POSIX strings inside the
    # Linux containers -- so every path written to .env is normalized to
    # forward slashes here, regardless of which form the folder picker
    # handed back.
    $DropfolderHostPath = $DropfolderHostPath -replace '\\', '/'
    $LibraryHostPath = $LibraryHostPath -replace '\\', '/'
    $DownloadsHostPath = $DownloadsHostPath -replace '\\', '/'

    $chars = (48..57) + (65..90) + (97..122)
    $GeneratedPassword = -join ((1..24) | ForEach-Object { [char](Get-Random -InputObject $chars) })

    $envContent = Get-Content ".env"
    $envContent = $envContent -replace '^DROPFOLDER_HOST_PATH=.*', "DROPFOLDER_HOST_PATH=$DropfolderHostPath"
    $envContent = $envContent -replace '^LIBRARY_HOST_PATH=.*', "LIBRARY_HOST_PATH=$LibraryHostPath"
    $envContent = $envContent -replace '^DOWNLOADS_HOST_PATH=.*', "DOWNLOADS_HOST_PATH=$DownloadsHostPath"
    $envContent = $envContent -replace '^POSTGRES_PASSWORD=.*', "POSTGRES_PASSWORD=$GeneratedPassword"
    Set-Content -Path ".env" -Value $envContent

    Write-Host "Wrote .env -- a random database password was generated for you (nothing to remember)."
}

# ---- Step 3: bring up the stack -------------------------------------------

Step "Starting SPOOL (this can take several minutes the first time)"

docker compose up -d --build

Write-Host -NoNewline "Waiting for the web app to respond"
$Ready = $false
for ($i = 0; $i -lt 60; $i++) {
    try {
        $resp = Invoke-WebRequest -Uri "http://localhost:8000/health" -UseBasicParsing -TimeoutSec 3
        if ($resp.StatusCode -eq 200) { $Ready = $true; break }
    } catch { }
    Write-Host -NoNewline "."
    Start-Sleep -Seconds 2
}
Write-Host ""
if ($Ready) {
    Write-Host "SPOOL is up: http://localhost:8000"
} else {
    Write-Host "SPOOL didn't respond within two minutes -- check what's happening with:"
    Note "docker compose ps"
    Note "docker compose logs api"
}

# ---- Step 4: host-helper (Open in Fusion/Bambu Studio/etc.) ---------------

Step "Setting up 'Open in...' for your CAD/slicer apps"

$PythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $PythonCmd) { $PythonCmd = Get-Command python3 -ErrorAction SilentlyContinue }

if (Read-YesNo "Auto-detect your installed CAD/slicer apps now?") {
    if ($PythonCmd) {
        & $PythonCmd.Source "host-helper\configure_apps.py"
    } else {
        Write-Host "python isn't installed or isn't on PATH -- skipping."
        Note "Install it from https://www.python.org/downloads/ (check 'Add python.exe to PATH'"
        Note "during install), then run: python host-helper\configure_apps.py"
    }
} else {
    Note "Skipped -- 'Open in...' buttons won't work until you run"
    Note "python host-helper\configure_apps.py (or edit host_helper_windows.py by hand) later."
}

powershell -ExecutionPolicy Bypass -File "host-helper\install_windows.ps1"

# ---- Done -------------------------------------------------------------------

Step "All set"

Write-Host "SPOOL is running at http://localhost:8000"
Start-Process "http://localhost:8000"
Write-Host ""
Write-Host "Unlike on a Mac, there's no extra permission step needed for the"
Write-Host "duplicate-file delete feature -- Windows' normal file permissions"
Write-Host "already cover it."
Write-Host ""
Write-Host "See README.md's 'Using SPOOL' section for a walkthrough, and"
Write-Host "'Known limitations' / 'Gotchas and best practices' before you dive in."
