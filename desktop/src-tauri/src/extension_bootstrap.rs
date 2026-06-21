use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

use serde::{Deserialize, Serialize};

use crate::win_process;

const BRIDGE_STATUS: &str = "http://127.0.0.1:18766/bridge/status";

#[derive(Debug, Clone, Deserialize)]
struct BundleManifest {
    #[serde(default)]
    app_version: String,
    #[serde(default)]
    extension_version: String,
    #[serde(default)]
    local_service_version: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct BundleInfo {
    app_version: String,
    extension_version: String,
    local_service_version: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ExtensionSetupStatus {
    pub extension_installed: bool,
    pub extension_path: String,
    pub bundle_extension_path: String,
    pub chrome_found: bool,
    pub chrome_path: Option<String>,
    pub bridge_connected: bool,
    pub connected_clients: u64,
    pub app_version: Option<String>,
    pub expected_extension_version: Option<String>,
    pub installed_extension_version: Option<String>,
    pub connected_extension_version: Option<String>,
    pub extension_version_matched: bool,
    pub extension_version_message: Option<String>,
    pub message: String,
}

pub fn extension_install_dir(data_dir: &Path) -> PathBuf {
    data_dir.join("extension")
}

pub fn chrome_profile_dir(data_dir: &Path) -> PathBuf {
    data_dir.join("chrome-profile")
}

pub fn ensure_extension_installed(bundle_dir: &Path, data_dir: &Path) -> Result<PathBuf, String> {
    let _ = sync_bundle_info(bundle_dir, data_dir);
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
        let mut command = Command::new("where");
        command.arg(name);
        win_process::hide_console(&mut command);
        command.output()
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
    ]);

    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const DETACHED_PROCESS: u32 = 0x00000008;
        const CREATE_NO_WINDOW: u32 = 0x08000000;
        command.creation_flags(DETACHED_PROCESS | CREATE_NO_WINDOW);
    }

    command
        .spawn()
        .map_err(|err| format!("启动 Chrome 失败: {err}"))?;
    Ok(())
}

fn prepare_explorer_target(path: &Path) -> Result<PathBuf, String> {
    if path.is_file() {
        return Ok(path.to_path_buf());
    }
    if !path.exists() {
        fs::create_dir_all(path)
            .map_err(|err| format!("创建目录失败: {} ({err})", path.display()))?;
    }
    let abs = path
        .canonicalize()
        .map_err(|err| format!("路径无效: {} ({err})", path.display()))?;
    let text = abs.to_string_lossy();
    if let Some(stripped) = text.strip_prefix(r"\\?\") {
        Ok(PathBuf::from(stripped))
    } else {
        Ok(abs)
    }
}

pub fn open_path_in_explorer(path: &Path) -> Result<(), String> {
    let target = prepare_explorer_target(path)?;

    if cfg!(windows) {
        let path_str = target.display().to_string();
        let mut command = Command::new("cmd");
        command.args(["/C", "start", "", &path_str]);
        win_process::hide_console(&mut command);
        command
            .spawn()
            .map_err(|err| format!("打开目录失败: {err}"))?;
        return Ok(());
    }
    if cfg!(target_os = "macos") {
        Command::new("open")
            .arg(&target)
            .spawn()
            .map_err(|err| err.to_string())?;
        return Ok(());
    }
    Command::new("xdg-open")
        .arg(&target)
        .spawn()
        .map_err(|err| err.to_string())?;
    Ok(())
}

pub fn build_setup_status(
    bundle_dir: &Path,
    data_dir: &Path,
    bootstrap_error: Option<&str>,
) -> ExtensionSetupStatus {
    let extension_path = extension_install_dir(data_dir);
    let bundle_extension_path = bundle_dir.join("extension");
    let extension_installed = extension_path.join("manifest.json").is_file();
    let chrome_path = find_chrome_executable();
    let connected_clients = bridge_client_count();
    let bridge_connected = connected_clients > 0;
    let bundle = read_bundle_manifest(bundle_dir);
    let installed_extension_version = read_manifest_version(&extension_path);
    let bridge_status = fetch_bridge_status_json();
    let connected_extension_version = bridge_status
        .as_ref()
        .and_then(|body| {
            body.get("connectedExtensionVersion")
                .or_else(|| body.get("connected_extension_version"))
                .and_then(|v| v.as_str())
                .map(str::to_string)
        });
    let version_eval = evaluate_extension_versions(
        bundle.as_ref(),
        installed_extension_version.as_deref(),
        connected_extension_version.as_deref(),
    );

    let message = if let Some(err) = bootstrap_error {
        err.to_string()
    } else if let Some(version_message) = version_eval.message.clone() {
        version_message
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
        bundle_extension_path: bundle_extension_path.to_string_lossy().replace('\\', "/"),
        chrome_found: chrome_path.is_some(),
        chrome_path: chrome_path.map(|p| p.to_string_lossy().replace('\\', "/")),
        bridge_connected,
        connected_clients,
        app_version: version_eval.app_version,
        expected_extension_version: version_eval.expected_extension_version,
        installed_extension_version: version_eval.installed_extension_version,
        connected_extension_version: version_eval.connected_extension_version,
        extension_version_matched: version_eval.matched,
        extension_version_message: version_eval.message,
        message,
    }
}

fn sync_bundle_info(bundle_dir: &Path, data_dir: &Path) -> Result<(), String> {
    let manifest = read_bundle_manifest(bundle_dir).ok_or_else(|| {
        format!(
            "未找到 bundle 版本信息: {}",
            bundle_dir.join("BUNDLE_MANIFEST.json").display()
        )
    })?;
    if manifest.extension_version.is_empty() {
        return Err("BUNDLE_MANIFEST.json 缺少 extension_version".into());
    }
    let info = BundleInfo {
        app_version: if manifest.app_version.is_empty() {
            env!("CARGO_PKG_VERSION").into()
        } else {
            manifest.app_version
        },
        extension_version: manifest.extension_version,
        local_service_version: if manifest.local_service_version.is_empty() {
            "0.1.0".into()
        } else {
            manifest.local_service_version
        },
    };
    let path = data_dir.join("bundle-info.json");
    let json = serde_json::to_string_pretty(&info).map_err(|err| err.to_string())?;
    fs::write(path, json).map_err(|err| err.to_string())?;
    Ok(())
}

fn read_bundle_manifest(bundle_dir: &Path) -> Option<BundleManifest> {
    let path = bundle_dir.join("BUNDLE_MANIFEST.json");
    let text = fs::read_to_string(path).ok()?;
    serde_json::from_str(&text).ok()
}

fn read_manifest_version(dir: &Path) -> Option<String> {
    let path = dir.join("manifest.json");
    let text = fs::read_to_string(path).ok()?;
    let json: serde_json::Value = serde_json::from_str(&text).ok()?;
    json.get("version")
        .and_then(|v| v.as_str())
        .map(str::to_string)
}

fn fetch_bridge_status_json() -> Option<serde_json::Value> {
    let client = reqwest::blocking::Client::builder()
        .timeout(std::time::Duration::from_secs(2))
        .build()
        .ok()?;
    let resp = client.get(BRIDGE_STATUS).send().ok()?;
    resp.json().ok()
}

struct VersionEval {
    app_version: Option<String>,
    expected_extension_version: Option<String>,
    installed_extension_version: Option<String>,
    connected_extension_version: Option<String>,
    matched: bool,
    message: Option<String>,
}

fn evaluate_extension_versions(
    bundle: Option<&BundleManifest>,
    installed: Option<&str>,
    connected: Option<&str>,
) -> VersionEval {
    let expected = bundle
        .map(|item| item.extension_version.as_str())
        .filter(|value| !value.is_empty());
    let app_version = bundle
        .map(|item| {
            if item.app_version.is_empty() {
                env!("CARGO_PKG_VERSION").to_string()
            } else {
                item.app_version.clone()
            }
        });

    let mut matched = true;
    let mut message = None;

    if let Some(expected_version) = expected {
        if let Some(connected_version) = connected {
            if version_older_than(connected_version, expected_version) {
                matched = false;
                message = Some(format!(
                    "当前 Chrome 插件 v{connected_version} 低于 App 要求 v{expected_version}，请更新插件。"
                ));
            } else if !versions_equal(connected_version, expected_version) {
                matched = false;
                message = Some(format!(
                    "当前 Chrome 插件 v{connected_version} 与 App 要求 v{expected_version} 不一致，请更新插件。"
                ));
            }
        } else if let Some(installed_version) = installed {
            if version_older_than(installed_version, expected_version)
                || !versions_equal(installed_version, expected_version)
            {
                matched = false;
                message = Some(format!(
                    "本地插件目录仍为 v{installed_version}，App 要求 v{expected_version}，请重启 App 或点击「启动浏览器插件」。"
                ));
            }
        }
    }

    VersionEval {
        app_version,
        expected_extension_version: expected.map(str::to_string),
        installed_extension_version: installed.map(str::to_string),
        connected_extension_version: connected.map(str::to_string),
        matched,
        message,
    }
}

fn compare_versions(left: &str, right: &str) -> Option<std::cmp::Ordering> {
    let parse = |value: &str| -> Vec<u32> {
        value
            .split(|c: char| !c.is_ascii_digit())
            .filter(|part| !part.is_empty())
            .filter_map(|part| part.parse().ok())
            .collect()
    };
    let mut left_parts = parse(left);
    let mut right_parts = parse(right);
    let max_len = left_parts.len().max(right_parts.len());
    left_parts.resize(max_len, 0);
    right_parts.resize(max_len, 0);
    left_parts.partial_cmp(&right_parts)
}

fn versions_equal(left: &str, right: &str) -> bool {
    compare_versions(left, right) == Some(std::cmp::Ordering::Equal)
}

fn version_older_than(actual: &str, expected: &str) -> bool {
    matches!(
        compare_versions(actual, expected),
        Some(std::cmp::Ordering::Less)
    )
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
        let mut command = Command::new("powershell");
        command.args(["-NoProfile", "-Command", &script]);
        win_process::hide_console(&mut command);
        let status = command.status().map_err(|err| err.to_string())?;
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
