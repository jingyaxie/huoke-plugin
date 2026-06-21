use std::process::Command;
use std::thread;
use std::time::Duration;

#[cfg(windows)]
use crate::win_process;

pub fn reclaim_huoke_ports(static_port: u16, local_service_port: u16) {
    reclaim_port(static_port);
    reclaim_port(local_service_port);
}

fn reclaim_port(port: u16) {
    let current = std::process::id();
    for pid in find_listeners(port) {
        if pid == current {
            continue;
        }
        log::info!("reclaiming port {port}: terminating pid {pid}");
        terminate_pid(pid);
    }
    thread::sleep(Duration::from_millis(300));
}

#[cfg(unix)]
fn find_listeners(port: u16) -> Vec<u32> {
    let output = match Command::new("lsof")
        .args(["-tiTCP", &port.to_string(), "-sTCP:LISTEN"])
        .output()
    {
        Ok(output) if output.status.success() => output,
        _ => return Vec::new(),
    };

    String::from_utf8_lossy(&output.stdout)
        .split_whitespace()
        .filter_map(|token| token.parse::<u32>().ok())
        .collect()
}

#[cfg(windows)]
fn find_listeners(port: u16) -> Vec<u32> {
    let mut command = Command::new("netstat");
    command.args(["-ano"]);
    win_process::hide_console(&mut command);
    let output = match command.output() {
        Ok(output) if output.status.success() => output,
        _ => return Vec::new(),
    };

    let needle = format!(":{port}");
    let mut pids = Vec::new();
    for line in String::from_utf8_lossy(&output.stdout).lines() {
        if !line.contains("LISTENING") || !line.contains(&needle) {
            continue;
        }
        if let Some(pid) = line.split_whitespace().last() {
            if let Ok(pid) = pid.parse::<u32>() {
                if pid > 0 {
                    pids.push(pid);
                }
            }
        }
    }
    pids.sort_unstable();
    pids.dedup();
    pids
}

#[cfg(unix)]
fn terminate_pid(pid: u32) {
    let _ = Command::new("kill")
        .arg(pid.to_string())
        .status()
        .and_then(|status| {
            if status.success() {
                return Ok(status);
            }
            Command::new("kill")
                .args(["-9", &pid.to_string()])
                .status()
        });
}

#[cfg(windows)]
fn terminate_pid(pid: u32) {
    let mut command = Command::new("taskkill");
    command.args(["/PID", &pid.to_string(), "/F"]);
    win_process::hide_console(&mut command);
    let _ = command.status();
}
