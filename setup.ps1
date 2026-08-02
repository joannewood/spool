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

# A boxed "Step N of TotalSteps" banner for the main numbered sequence
# below (Docker check -> folders -> start SPOOL -> host-helper) -- reads
# more like a step-by-step wizard installer than a scrolling console log.
# Deliberately separate from the plain Step above, which is still used
# for one-off headers outside the main sequence (e.g. the quick-menu
# "Restarting SPOOL" path) that shouldn't consume a step count of their
# own or claim to be "step N of 4" when they're not part of that flow.
# Plain ASCII rule (not a Unicode box-drawing character) matching this
# file's existing convention of avoiding non-ASCII console output --
# never verified on a real Windows console's code page, so this doesn't
# introduce the first exception.
$TotalSteps = 4
$script:StepCount = 0
function WizardStep($msg) {
    $script:StepCount++
    Write-Host ""
    Write-Host ("-" * 44) -ForegroundColor DarkGray
    Write-Host "Step $($script:StepCount) of $($TotalSteps): $msg" -ForegroundColor Cyan
    Write-Host ("-" * 44) -ForegroundColor DarkGray
}
# Same framing, no step count, for the closing summary screen -- the
# "Completing the Setup Wizard" page every installer ends on.
function WizardDone($msg) {
    Write-Host ""
    Write-Host ("-" * 44) -ForegroundColor DarkGray
    Write-Host "Done: $msg" -ForegroundColor Cyan
    Write-Host ("-" * 44) -ForegroundColor DarkGray
}

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

# Shown instead of the full folder-setup flow when .env already exists --
# lets someone who just wants to check/restart SPOOL (e.g. re-opening the
# installer .exe later, the way you'd click Docker Desktop's whale icon)
# do that in one click. A custom form for the same reason Confirm-
# Destructive is one: MessageBox can't offer three custom-labeled buttons.
function Show-QuickActionMenu {
    $form = New-Object System.Windows.Forms.Form
    $form.Text = "SPOOL Setup"
    $form.StartPosition = "CenterScreen"
    $form.FormBorderStyle = "FixedDialog"
    $form.MaximizeBox = $false
    $form.MinimizeBox = $false
    $form.TopMost = $true
    $form.ClientSize = New-Object System.Drawing.Size(420, 160)

    $label = New-Object System.Windows.Forms.Label
    $label.Text = "SPOOL is already set up here. What would you like to do?"
    $label.SetBounds(20, 15, 380, 50)
    $form.Controls.Add($label)

    $exitButton = New-Object System.Windows.Forms.Button
    $exitButton.Text = "Exit"
    $exitButton.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
    $exitButton.SetBounds(20, 100, 90, 30)
    $form.Controls.Add($exitButton)
    $form.CancelButton = $exitButton

    $reconfigureButton = New-Object System.Windows.Forms.Button
    $reconfigureButton.Text = "Re-run Full Setup"
    $reconfigureButton.DialogResult = [System.Windows.Forms.DialogResult]::No
    $reconfigureButton.SetBounds(130, 100, 140, 30)
    $form.Controls.Add($reconfigureButton)

    $restartButton = New-Object System.Windows.Forms.Button
    $restartButton.Text = "Restart SPOOL"
    $restartButton.DialogResult = [System.Windows.Forms.DialogResult]::Yes
    $restartButton.SetBounds(290, 100, 110, 30)
    $form.Controls.Add($restartButton)
    $form.AcceptButton = $restartButton

    return $form.ShowDialog()
}

# Best-effort desktop shortcut -- a .url file is the direct Windows
# equivalent of macOS's .webloc (double-click opens the URL in your
# default browser), needing no browser-specific scripting or extra
# permissions. Never fatal if the Desktop folder is missing/unwritable
# for some reason -- this is a convenience, not a requirement.
function New-DesktopShortcut {
    try {
        $desktop = [Environment]::GetFolderPath("Desktop")
        $shortcutPath = Join-Path $desktop "SPOOL.url"
        $content = "[InternetShortcut]`r`nURL=http://localhost:8000`r`n"
        [System.IO.File]::WriteAllText($shortcutPath, $content, (New-Object System.Text.UTF8Encoding($false)))
    } catch {
        # Convenience only -- ignored on failure.
    }
}

# Shared by the fast "Restart SPOOL" path above and the full setup flow's
# own Step 3 below, so re-running the whole guided setup doesn't need a
# second, duplicate copy of this.
function ConvertTo-SqlLiteral($s) {
    return $s -replace "'", "''"
}

# Keeps watched_roots in sync with whatever DROPFOLDER_HOST_PATH/
# LIBRARY_HOST_PATH/DOWNLOADS_HOST_PATH currently say in .env -- this is
# what used to require a manual `docker compose exec postgres psql ...
# INSERT` by hand (see README's old "Adding a folder you initially
# skipped" instructions) every time a previously-blank folder was filled
# in, an existing one's path changed, or one was cleared. Safe to call
# every time Start-AndWait finishes, not just after a reconfigure -- it's
# a no-op UPDATE-to-the-same-value when .env hasn't actually changed.
# Deliberately never touches label/kind/ingest_mode on a row that
# already exists, only host_path/active -- an admin-page customization
# (e.g. a renamed label) must survive this running again.
function Sync-WatchedRoots {
    $envContent = Get-Content ".env"
    $dropfolder = ConvertTo-SqlLiteral (($envContent | Where-Object { $_ -match "^DROPFOLDER_HOST_PATH=" }) -replace "^DROPFOLDER_HOST_PATH=", "")
    $library = ConvertTo-SqlLiteral (($envContent | Where-Object { $_ -match "^LIBRARY_HOST_PATH=" }) -replace "^LIBRARY_HOST_PATH=", "")
    $downloads = ConvertTo-SqlLiteral (($envContent | Where-Object { $_ -match "^DOWNLOADS_HOST_PATH=" }) -replace "^DOWNLOADS_HOST_PATH=", "")

    $sql = "UPDATE watched_roots SET host_path = '$dropfolder', active = TRUE WHERE container_path = '/roots/dropfolder';`n"

    if ($library) {
        $sql += "INSERT INTO watched_roots (host_path, container_path, label, kind, ingest_mode, active) SELECT '$library', '/roots/library', 'Library', 'library', 'index_in_place', TRUE WHERE NOT EXISTS (SELECT 1 FROM watched_roots WHERE container_path = '/roots/library');`n"
        $sql += "UPDATE watched_roots SET host_path = '$library', active = TRUE WHERE container_path = '/roots/library';`n"
    } else {
        $sql += "UPDATE watched_roots SET active = FALSE WHERE container_path = '/roots/library';`n"
    }

    if ($downloads) {
        $sql += "INSERT INTO watched_roots (host_path, container_path, label, kind, ingest_mode, active) SELECT '$downloads', '/roots/downloads', 'Downloads', 'downloads', 'relocate_to_dropfolder', TRUE WHERE NOT EXISTS (SELECT 1 FROM watched_roots WHERE container_path = '/roots/downloads');`n"
        $sql += "UPDATE watched_roots SET host_path = '$downloads', active = TRUE WHERE container_path = '/roots/downloads';`n"
    } else {
        $sql += "UPDATE watched_roots SET active = FALSE WHERE container_path = '/roots/downloads';`n"
    }

    $sql | docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U spool -d spool | Out-Null
}

# No --build: docker-compose.yml's api/watcher/worker/worker-step all
# carry a ghcr.io image: tag now, so a plain `up` pulls the pre-built
# image instead of compiling everything from source on the tester's own
# machine. Developers working on SPOOL itself still use
# `docker compose up -d --build` directly (see CONTRIBUTING.md).
function Start-AndWait {
    docker compose up -d

    Write-Host -NoNewline "Waiting for the web app to respond"
    $ready = $false
    for ($i = 0; $i -lt 60; $i++) {
        try {
            $resp = Invoke-WebRequest -Uri "http://localhost:8000/health" -UseBasicParsing -TimeoutSec 3
            if ($resp.StatusCode -eq 200) { $ready = $true; break }
        } catch { }
        Write-Host -NoNewline "."
        Start-Sleep -Seconds 2
    }
    Write-Host ""
    if ($ready) {
        Write-Host "SPOOL is up: http://localhost:8000"
        Sync-WatchedRoots
        New-DesktopShortcut
    } else {
        Write-Host "SPOOL didn't respond within two minutes -- check what's happening with:"
        Note "docker compose ps"
        Note "docker compose logs api"
    }
}

# ---- Step 1: Docker Desktop ----------------------------------------------

WizardStep "Checking for Docker Desktop"

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

WizardStep "Configuring your folders"

# Tracked before anything below touches the filesystem -- the wipe-check
# further down (a fresh .env that doesn't match an already-provisioned
# database) only makes sense when .env genuinely didn't exist yet at the
# start of this run. Reconfiguring folders on an *already* set-up install
# ("Re-run Full Setup" -> "no, reconfigure" below) also sets
# $Reconfigure = $true, but there .env already exists with a real,
# working POSTGRES_PASSWORD -- that path preserves it instead (see the
# password-generation step further down) rather than needing the wipe
# warning at all.
$EnvExistedBefore = Test-Path ".env"

$Reconfigure = $true
if (Test-Path ".env") {
    Write-Host "Found an existing .env file -- SPOOL looks like it's already set up here."
    $choice = Show-QuickActionMenu
    if ($choice -eq [System.Windows.Forms.DialogResult]::Yes) {
        Step "Restarting SPOOL"
        Start-AndWait
        Start-Process "http://localhost:8000"
        exit 0
    } elseif ($choice -eq [System.Windows.Forms.DialogResult]::No) {
        $Reconfigure = -not (Read-YesNo "Keep your existing folder configuration as-is?")
        if (-not $Reconfigure) { Write-Host "Keeping your existing .env -- skipping folder setup." }
    } else {
        Write-Host "Exiting -- nothing has been changed."
        exit 0
    }
}

# Shows a small dialog with a "Browse..." button first, rather than the
# native folder browser just appearing unprompted mid-flow -- you
# explicitly click to open it. "Use Suggested Path" is the other button
# (not a plain Cancel), so falling back to the suggested path is a
# deliberate, visible choice rather than a side effect of dismissing a
# picker you didn't mean to dismiss. Same custom-Form pattern as
# Confirm-Destructive/Show-QuickActionMenu, for the same reason: a plain
# MessageBox can't relabel its buttons.
function Confirm-BrowseFolder($description, $defaultPath) {
    $form = New-Object System.Windows.Forms.Form
    $form.Text = "SPOOL Setup"
    $form.StartPosition = "CenterScreen"
    $form.FormBorderStyle = "FixedDialog"
    $form.MaximizeBox = $false
    $form.MinimizeBox = $false
    $form.TopMost = $true
    $form.ClientSize = New-Object System.Drawing.Size(440, 150)

    $label = New-Object System.Windows.Forms.Label
    $label.Text = "$description`r`n`r`nSuggested: $defaultPath"
    $label.SetBounds(20, 15, 400, 80)
    $form.Controls.Add($label)

    $useDefaultButton = New-Object System.Windows.Forms.Button
    $useDefaultButton.Text = "Use Suggested Path"
    $useDefaultButton.DialogResult = [System.Windows.Forms.DialogResult]::No
    $useDefaultButton.SetBounds(110, 105, 160, 30)
    $form.Controls.Add($useDefaultButton)
    $form.CancelButton = $useDefaultButton
    $form.AcceptButton = $useDefaultButton

    $browseButton = New-Object System.Windows.Forms.Button
    $browseButton.Text = "Browse..."
    $browseButton.DialogResult = [System.Windows.Forms.DialogResult]::Yes
    $browseButton.SetBounds(280, 105, 130, 30)
    $form.Controls.Add($browseButton)

    $result = $form.ShowDialog()
    return $result -eq [System.Windows.Forms.DialogResult]::Yes
}

function Select-Folder($description, $default) {
    if (-not (Confirm-BrowseFolder $description $default)) {
        return $default
    }
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
    # database. Only meaningful when .env didn't exist yet at the start
    # of this run -- if it did, we're reconfiguring an already-set-up
    # install and preserve its real POSTGRES_PASSWORD below regardless,
    # so there's no mismatch risk to warn about here.
    docker volume inspect spool_pgdata 2>$null 1>$null
    if ((-not $EnvExistedBefore) -and $LASTEXITCODE -eq 0) {
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
    Write-Host "For each folder below, you'll see a small dialog first -- click 'Browse...'"
    Write-Host "to open a folder picker (use its 'Make New Folder' button if it doesn't"
    Write-Host "exist yet), or 'Use Suggested Path' to accept the suggestion shown without"
    Write-Host "opening a picker at all."
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

    # Preserve an existing real password rather than generating a new one
    # that can't authenticate against an already-provisioned database --
    # a real bug this used to have: reconfiguring folders on an already
    # set-up install (.env existed, with a real password matching the
    # live Postgres volume) silently regenerated POSTGRES_PASSWORD every
    # time, breaking every service's connection to that same database.
    # Only generate fresh when .env is genuinely new or still has the
    # unfilled "changeme" placeholder from .env.example.
    $ExistingPassword = (Get-Content ".env" | Where-Object { $_ -match "^POSTGRES_PASSWORD=" }) -replace "^POSTGRES_PASSWORD=", ""
    if ($ExistingPassword -and $ExistingPassword -ne "changeme") {
        $GeneratedPassword = $ExistingPassword
        $KeptExistingPassword = $true
    } else {
        $chars = (48..57) + (65..90) + (97..122)
        $GeneratedPassword = -join ((1..24) | ForEach-Object { [char](Get-Random -InputObject $chars) })
        $KeptExistingPassword = $false
    }

    $envContent = Get-Content ".env"
    $envContent = $envContent -replace '^DROPFOLDER_HOST_PATH=.*', "DROPFOLDER_HOST_PATH=$DropfolderHostPath"
    $envContent = $envContent -replace '^LIBRARY_HOST_PATH=.*', "LIBRARY_HOST_PATH=$LibraryHostPath"
    $envContent = $envContent -replace '^DOWNLOADS_HOST_PATH=.*', "DOWNLOADS_HOST_PATH=$DownloadsHostPath"
    $envContent = $envContent -replace '^POSTGRES_PASSWORD=.*', "POSTGRES_PASSWORD=$GeneratedPassword"
    Set-Content -Path ".env" -Value $envContent

    if ($KeptExistingPassword) {
        Write-Host "Wrote .env -- kept your existing database password."
    } else {
        Write-Host "Wrote .env -- a random database password was generated for you (nothing to remember)."
    }
}

# ---- Step 3: bring up the stack -------------------------------------------

WizardStep "Starting SPOOL (first time only: downloads a few GB and can take several minutes)"

Start-AndWait

# ---- Step 4: host-helper (Open in Fusion/Bambu Studio/etc.) ---------------

WizardStep "Setting up 'Open in...' for your CAD/slicer apps"

# A native file-picker per app (host-helper\configure_apps_windows.ps1)
# instead of the Python-based auto-detect-and-confirm flow
# (configure_apps.py) this used to call -- means Windows setup needs no
# Python at all now. configure_apps.py still exists and still works if
# you'd rather have it scan Program Files and offer a pick-from-list
# instead of browsing directly to the .exe yourself.
if (Read-YesNo "Set up your CAD/slicer apps now?") {
    powershell -ExecutionPolicy Bypass -File "host-helper\configure_apps_windows.ps1"
} else {
    Note "Skipped -- 'Open in...' buttons won't work until you run"
    Note "host-helper\configure_apps_windows.ps1 (or edit host_helper_windows.py by hand) later."
}

powershell -ExecutionPolicy Bypass -File "host-helper\install_windows.ps1"

# ---- Done -------------------------------------------------------------------

WizardDone "All set"

Write-Host "SPOOL is running at http://localhost:8000"
Write-Host "A SPOOL shortcut has been added to your Desktop -- double-click it any time to open SPOOL."
Start-Process "http://localhost:8000"
Write-Host ""
Write-Host "Unlike on a Mac, there's no extra permission step needed for the"
Write-Host "duplicate-file delete feature -- Windows' normal file permissions"
Write-Host "already cover it."
Write-Host ""
Write-Host "See README.md's 'Using SPOOL' section for a walkthrough, and"
Write-Host "'Known limitations' / 'Gotchas and best practices' before you dive in."
