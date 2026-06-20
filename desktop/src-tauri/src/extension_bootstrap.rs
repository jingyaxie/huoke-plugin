use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

use serde::Serialize;

const DOUYIN_HOME: &str = "https://www.douyin.com/";
const BRIDGE_STATUS: &str = "http://127.0.0.1:18766/bridge/status";

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ExtensionSetupStatus {
    pub extension_installed: bool,
    pub extension_path: String,
    pub chrome_found: bool,
    pub chrome_path: Option<String>,
    pub bridge_connected: bool,
    pub connected_clients: u64,
    pub message: String,
}

pub fn extension_install_dir(data_dir: &Path) -> PathBuf {
    data_dir.join("extension")
}

pub fn chrome_profile_dir(data_dir: &Path) -> PathBuf {
    data_dir.join("chrome-profile")
}

pub fn ensure_extension_installed(bundle_dir: &Path, data_dir: &Path) -> Result<PathBuf, String> {
    let target = extension_install_dir(data_dir);
    let unpacked = bundle_dir.join("extension").join("manifest.json");
    let zip = bundle_dir.join("huoke-extension.zip");

    if unpacked.is_file() {
        copy_dir_all(&bundle_dir.join("extension"), &target)?;
        return Ok(target);
    }

    if zip.is_file() {
        extract_zip(&zip, &target)?;
        return Ok(target);
    }

    Err(format!(
        "安装包内未找到 Chrome 插件（{} 或 {}）",
        unpacked.display(),
        zip.display()
    ))
}

pub fn find_chrome_executable() -> Option<PathBuf> {
    if cfg!(windows) {
        let local = std::env::var("LOCALAPPDATA").ok()?;
        let candidates = [
            PathBuf::from(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
            PathBuf::from(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
            PathBuf::from(local).join(r"Google\Chrome\Application\chrome.exe"),
        ];
        return candidates.into_iter().find(|path| path.is_file());
    }

    if cfg!(target_os = "macos") {
        let path = PathBuf::from("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome");
        return path.is_file().then_some(path);
    }

    for name in ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"] {
        if let Ok(path) = which_command(name) {
            return Some(path);
        }
    }
    None
}

fn which_command(name: &str) -> Result<PathBuf, String> {
    let output = if cfg!(windows) {
        Command::new("where").arg(name).output()
    } else {
        Command::new("which").arg(name).output()
    }
    .map_err(|err| err.to_string())?;
    if !output.status.success() {
        return Err(format!("{name} not found"));
    }
    let text = String::from_utf8_lossy(&output.stdout);
    let line = text.lines().next().unwrap_or("").trim();
    if line.is_empty() {
        return Err(format!("{name} not found"));
    }
    Ok(PathBuf::from(line))
}

pub fn bridge_client_count() -> u64 {
    let client = match reqwest::blocking::Client::builder()
        .timeout(std::time::Duration::from_secs(2))
        .build()
    {
        Ok(client) => client,
        Err(_) => return 0,
    };
    let Ok(resp) = client.get(BRIDGE_STATUS).send() else {
        return 0;
    };
    let Ok(text) = resp.text() else {
        return 0;
    };
    let Ok(body) = serde_json::from_str::<serde_json::Value>(&text) else {
        return 0;
    };
    body.get("connected_clients")
        .and_then(|v| v.as_u64())
        .unwrap_or(0)
}

pub fn launch_chrome_with_extension(
    chrome: &Path,
    extension_dir: &Path,
    profile_dir: &Path,
) -> Result<(), String> {
    if !extension_dir.join("manifest.json").is_file() {
        return Err(format!(
            "插件目录无效，缺少 manifest.json: {}",
            extension_dir.display()
        ));
    }
    fs::create_dir_all(profile_dir).map_err(|err| err.to_string())?;

    let mut command = Command::new(chrome);
    command.args([
        &format!("--user-data-dir={}", profile_dir.display()),
        &format!("--load-extension={}", extension_dir.display()),
        "--no-first-run",
        "--no-default-browser-check",
        DOUYIN_HOME,
    ]);

    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const DETACHED_PROCESS: u32 = 0x00000008;
        command.creation_flags(DETACHED_PROCESS);
    }

    command
        .spawn()
        .map_err(|err| format!("启动 Chrome 失败: {err}"))?;
    Ok(())
}

pub fn open_path_in_explorer(path: &Path) -> Result<(), String> {
    if cfg!(windows) {
        Command::new("explorer")
            .arg(path)
            .spawn()
            .map_err(|err| err.to_string())?;
        return Ok(());
    }
    if cfg!(target_os = "macos") {
        Command::new("open")
            .arg(path)
            .spawn()
            .map_err(|err| err.to_string())?;
        return Ok(());
    }
    Command::new("xdg-open")
        .arg(path)
        .spawn()
        .map_err(|err| err.to_string())?;
    Ok(())
}

pub fn build_setup_status(
    _bundle_dir: &Path,
    data_dir: &Path,
    bootstrap_error: Option<&str>,
) -> ExtensionSetupStatus {
    let extension_path = extension_install_dir(data_dir);
    let extension_installed = extension_path.join("manifest.json").is_file();
    let chrome_path = find_chrome_executable();
    let connected_clients = bridge_client_count();
    let bridge_connected = connected_clients > 0;

    let message = if let Some(err) = bootstrap_error {
        err.to_string()
    } else if !extension_installed {
        "正在准备 Chrome 插件…".into()
    } else if chrome_path.is_none() {
        "未检测到 Google Chrome，请先安装 Chrome 后点击「启动浏览器插件」。".into()
    } else if bridge_connected {
        "Chrome 插件已连接，可以创建采集任务。".into()
    } else {
        "请点击「启动浏览器插件」，在打开的 Chrome 窗口登录抖音后即可使用。".into()
    };

    ExtensionSetupStatus {
        extension_installed,
        extension_path: extension_path.to_string_lossy().replace('\\', "/"),
        chrome_found: chrome_path.is_some(),
        chrome_path: chrome_path.map(|p| p.to_string_lossy().replace('\\', "/")),
        bridge_connected,
        connected_clients,
        message,
    }
}

pub fn bootstrap_extension(bundle_dir: &Path, data_dir: &Path) -> Result<ExtensionSetupStatus, String> {
    fs::create_dir_all(data_dir).map_err(|err| err.to_string())?;
    let extension_dir = ensure_extension_installed(bundle_dir, data_dir)?;
    let profile_dir = chrome_profile_dir(data_dir);

    if bridge_client_count() > 0 {
        return Ok(build_setup_status(bundle_dir, data_dir, None));
    }

    if let Some(chrome) = find_chrome_executable() {
        launch_chrome_with_extension(&chrome, &extension_dir, &profile_dir)?;
        for _ in 0..20 {
            std::thread::sleep(std::time::Duration::from_millis(500));
            if bridge_client_count() > 0 {
                break;
            }
        }
    }

    Ok(build_setup_status(bundle_dir, data_dir, None))
}

fn copy_dir_all(src: &Path, dst: &Path) -> Result<(), String> {
    if !src.is_dir() {
        return Err(format!("源目录不存在: {}", src.display()));
    }
    fs::create_dir_all(dst).map_err(|err| err.to_string())?;
    for entry in fs::read_dir(src).map_err(|err| err.to_string())? {
        let entry = entry.map_err(|err| err.to_string())?;
        let target = dst.join(entry.file_name());
        let file_type = entry.file_type().map_err(|err| err.to_string())?;
        if file_type.is_dir() {
            copy_dir_all(&entry.path(), &target)?;
        } else {
            fs::copy(entry.path(), target).map_err(|err| err.to_string())?;
        }
    }
    Ok(())
}

fn extract_zip(zip_path: &Path, dest_dir: &Path) -> Result<(), String> {
    if dest_dir.exists() {
        fs::remove_dir_all(dest_dir).map_err(|err| err.to_string())?;
    }
    fs::create_dir_all(dest_dir).map_err(|err| err.to_string())?;

    if cfg!(windows) {
        let script = format!(
            "Expand-Archive -LiteralPath '{}' -DestinationPath '{}' -Force",
            zip_path.display(),
            dest_dir.display()
        );
        let status = Command::new("powershell")
            .args(["-NoProfile", "-Command", &script])
            .status()
            .map_err(|err| err.to_string())?;
        if !status.success() {
            return Err("解压 huoke-extension.zip 失败".into());
        }
        return Ok(());
    }

    let status = Command::new("unzip")
        .args(["-oq", &zip_path.to_string_lossy(), "-d", &dest_dir.to_string_lossy()])
        .status()
        .map_err(|err| err.to_string())?;
    if !status.success() {
        return Err("解压 huoke-extension.zip 失败".into());
    }
    Ok(())
}
