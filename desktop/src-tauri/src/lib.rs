// SPOOL desktop wrapper -- a thin native shell around the existing web app
// (services/api), not a reimplementation of it. Assumes SPOOL is already
// installed the normal way (the Mac/Windows installer, see README.md) at
// its conventional location; this app's only job is to bring the Docker
// stack up if it isn't already, wait for it to respond, and then show it
// in a real window instead of a browser tab.
//
// Deliberately never stops the stack on window-close/quit -- SPOOL is
// designed to run continuously in the background watching folders (see
// CLAUDE.md's architecture note), so quitting this window should behave
// like closing a browser tab, not like shutting SPOOL down. If you want to
// actually stop it, `docker compose down` in the install folder still
// works exactly as documented.

use std::env;
use std::path::PathBuf;
use std::process::Command;
use std::time::Duration;

use serde::Serialize;
use tauri::{AppHandle, Emitter};

const SPOOL_URL: &str = "http://localhost:8000";
const HEALTH_URL: &str = "http://localhost:8000/health";
// Matches setup.sh/setup.ps1's own Start-AndWait/start_and_wait retry
// shape (60 attempts, 2s apart == 2 minutes) -- first-run pulls a few GB
// of images even with the pre-built-image fix, so this needs real headroom.
const HEALTH_CHECK_ATTEMPTS: u32 = 60;
const HEALTH_CHECK_INTERVAL: Duration = Duration::from_secs(2);
const SLOW_START_NOTICE_AFTER: u32 = 10;

#[derive(Clone, Serialize)]
struct StartupError {
    summary: String,
    detail: String,
}

// GUI-launched apps on macOS don't inherit the interactive shell's PATH
// (the same gotcha setup.sh already documents and works around) -- Docker
// Desktop's own `docker` binary lives in /usr/local/bin or
// /opt/homebrew/bin, neither of which a double-clicked .app sees by
// default.
fn docker_command() -> Command {
    let mut cmd = Command::new("docker");
    let existing_path = env::var("PATH").unwrap_or_default();
    cmd.env(
        "PATH",
        format!("{existing_path}:/usr/local/bin:/opt/homebrew/bin"),
    );
    cmd
}

// Where the installer (README.md's Mac setup flow) puts SPOOL. Overridable
// via SPOOL_APP_DIR for development/testing against a non-default checkout
// without needing a real install there.
fn spool_dir() -> PathBuf {
    if let Ok(dir) = env::var("SPOOL_APP_DIR") {
        return PathBuf::from(dir);
    }
    let home = env::var("HOME").expect("HOME not set");
    PathBuf::from(home).join("Applications").join("SPOOL")
}

fn emit_error(app: &AppHandle, summary: &str, detail: &str) {
    log::error!("spool-error: {summary} -- {detail}");
    let _ = app.emit(
        "spool-error",
        StartupError {
            summary: summary.to_string(),
            detail: detail.to_string(),
        },
    );
}

fn emit_status(app: &AppHandle, message: &str) {
    log::info!("spool-status: {message}");
    let _ = app.emit("spool-status", message);
}

fn health_check_ok() -> bool {
    // Shelling out to curl rather than adding an HTTP client crate --
    // matches this project's existing minimal-dependency convention
    // (host-helper's stdlib-only design, setup.sh's own curl-based health
    // check) and curl ships with macOS/Windows either way.
    Command::new("curl")
        .args(["-sf", "-o", "/dev/null", HEALTH_URL])
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}

fn start_spool(app: AppHandle) {
    let dir = spool_dir();

    if !dir.join("docker-compose.yml").exists() {
        emit_error(
            &app,
            "SPOOL doesn't look installed yet.",
            &format!(
                "No docker-compose.yml found at {}. Run the SPOOL installer first (see the README), then reopen this app.",
                dir.display()
            ),
        );
        return;
    }

    if docker_command().arg("--version").output().is_err() {
        emit_error(
            &app,
            "Docker Desktop isn't installed or isn't on PATH.",
            "Install Docker Desktop, open it, and wait for it to say it's running, then reopen this app.",
        );
        return;
    }

    emit_status(&app, "Starting the SPOOL containers…");
    let up_result = docker_command()
        .args(["compose", "up", "-d"])
        .current_dir(&dir)
        .output();

    match up_result {
        Ok(output) if !output.status.success() => {
            emit_error(
                &app,
                "Docker couldn't start SPOOL's containers.",
                String::from_utf8_lossy(&output.stderr).trim(),
            );
            return;
        }
        Err(e) => {
            emit_error(&app, "Couldn't run `docker compose up -d`.", &e.to_string());
            return;
        }
        _ => {}
    }

    emit_status(&app, "Waiting for SPOOL to respond…");
    for attempt in 0..HEALTH_CHECK_ATTEMPTS {
        if health_check_ok() {
            log::info!("spool-ready: {SPOOL_URL}");
            let _ = app.emit("spool-ready", SPOOL_URL);
            return;
        }
        if attempt == SLOW_START_NOTICE_AFTER {
            emit_status(
                &app,
                "Still starting — first run after an update can take a few minutes while images download.",
            );
        }
        std::thread::sleep(HEALTH_CHECK_INTERVAL);
    }

    emit_error(
        &app,
        "SPOOL didn't respond in time.",
        &format!(
            "Open Terminal, cd to {}, and run `docker compose ps` and `docker compose logs api` to see what's happening.",
            dir.display()
        ),
    );
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }
            let handle = app.handle().clone();
            std::thread::spawn(move || start_spool(handle));
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
