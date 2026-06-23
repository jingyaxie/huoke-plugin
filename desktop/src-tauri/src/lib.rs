use std::fs::OpenOptions;
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

use tauri::{AppHandle, Manager, RunEvent, WindowEvent};
use tauri::window::Color;

mod extension_bootstrap;
mod port_reclaim;
mod static_server;
mod win_process;

use extension_bootstrap::ExtensionSetupStatus;

const DESKTOP_PORT: u16 = 18765;
const LOCAL_SERVICE_PORT: u16 = 18766;
const STATIC_HEALTH_URL: &str = "http://127.0.0.1:18765/health";
const LOCAL_SERVICE_HEALTH_URL: &str = "http://127.0.0.1:18766/health";
const LOCAL_SERVICE_INIT_URL: &str = "http://127.0.0.1:18766/api/runtime/init";
const APP_HOME_URL: &str = "http://127.0.0.1:18765/extension-bridge";
const BACKEND_LOG_CAP: usize = 120;

struct ServiceState {
    backend: Mutex<Option<Child>>,
    bundle_dir: Mutex<Option<PathBuf>>,
    data_dir: Mutex<Option<PathBuf>>,
}

struct BackendLogState {
    lines: Mutex<Vec<String>>,
}

impl BackendLogState {
    fn push_line(&self, line: String) {
        let mut guard = self.lines.lock().expect("backend log lock");
        guard.push(line);
        if guard.len() > BACKEND_LOG_CAP {
            let drain = guard.len() - BACKEND_LOG_CAP;
            guard.drain(0..drain);
        }
    }

    fn tail(&self, max_lines: usize) -> String {
        let guard = self.lines.lock().expect("backend log lock");
        if guard.is_empty() {
            return String::new();
        }
        let start = guard.len().saturating_sub(max_lines);
        guard[start..].join("\n")
    }
}

struct BackendProcess {
    child: Child,
    log_readers: Vec<JoinHandle<()>>,
}

fn launch_marker_name() -> &'static str {
    "prepare-bundle.sh"
}

fn normalize_path(path: &Path) -> PathBuf {
    let text = path.to_string_lossy();
    if let Some(stripped) = text.strip_prefix(r"\\?\") {
        return PathBuf::from(stripped);
    }
    path.to_path_buf()
}

fn display_path(path: &Path) -> String {
    path.to_string_lossy().replace('\\', "/")
}

fn resolve_app_log_file(app: &AppHandle) -> Result<PathBuf, String> {
    let log_dir = app.path().app_log_dir().map_err(|err| err.to_string())?;
    std::fs::create_dir_all(&log_dir).map_err(|err| err.to_string())?;
    let file_name = app
        .config()
        .product_name
        .clone()
        .unwrap_or_else(|| "huoke".to_string());
    Ok(log_dir.join(format!("{file_name}.log")))
}

fn desktop_log_hint(app: &AppHandle) -> String {
    resolve_app_log_file(app)
        .map(|path| display_path(&path))
        .unwrap_or_else(|_| {
            if cfg!(windows) {
                "%LOCALAPPDATA%/com.huoke.desktop/logs/AI获客平台.log".into()
            } else if cfg!(target_os = "macos") {
                "~/Library/Logs/com.huoke.desktop/AI获客平台.log".into()
            } else {
                "~/.local/share/com.huoke.desktop/logs/AI获客平台.log".into()
            }
        })
}

fn append_unified_log(log_file: &Path, line: &str) {
    let Ok(mut file) = OpenOptions::new().create(true).append(true).open(log_file) else {
        return;
    };
    let _ = writeln!(file, "{line}");
}

fn is_project_root(path: &Path) -> bool {
    if path.join("desktop/bundle/BUNDLE_MANIFEST.json").is_file() {
        return true;
    }
    if path.join("bundle/BUNDLE_MANIFEST.json").is_file() {
        return true;
    }
    path.join("scripts").join(launch_marker_name()).is_file()
}

fn find_launch_root(base: &Path) -> Option<PathBuf> {
    let mut queue = vec![base.to_path_buf()];

    while let Some(current) = queue.pop() {
        if is_project_root(&current) {
            return Some(current);
        }
        if let Ok(entries) = std::fs::read_dir(&current) {
            for entry in entries.filter_map(Result::ok) {
                let path = entry.path();
                if path.is_dir() {
                    queue.push(path);
                }
            }
        }
    }
    None
}

fn find_bundle_dir(base: &Path) -> Option<PathBuf> {
    let direct = [
        base.join("desktop/bundle"),
        base.join("bundle"),
    ];
    for dir in direct {
        if is_bundle_dir(&dir) {
            return Some(dir);
        }
    }

    let mut queue = vec![base.to_path_buf()];
    while let Some(current) = queue.pop() {
        if current.ends_with("desktop/bundle") || current.ends_with("bundle") {
            if is_bundle_dir(&current) {
                return Some(current);
            }
        }
        if let Ok(entries) = std::fs::read_dir(&current) {
            for entry in entries.filter_map(Result::ok) {
                let path = entry.path();
                if path.is_dir() {
                    queue.push(path);
                }
            }
        }
    }
    None
}

fn local_service_binary_name() -> &'static str {
    if cfg!(windows) {
        "huoke-local-service.exe"
    } else {
        "huoke-local-service"
    }
}

fn is_bundle_dir(dir: &Path) -> bool {
    if dir.join("frontend-dist").join("index.html").is_file() {
        return true;
    }
    if dir.join("runtime").join(local_service_binary_name()).is_file() {
        return true;
    }
    dir.join("runtime").is_dir()
}

fn resolve_frontend_dist(root: &Path, bundle_dir: &Path) -> Result<PathBuf, String> {
    for candidate in [
        bundle_dir.join("frontend-dist"),
        root.join("frontend/dist"),
    ] {
        if candidate.join("index.html").is_file() {
            return Ok(candidate);
        }
    }
    Err("未找到前端静态资源 frontend-dist".into())
}

fn find_local_service_binary(root: &Path, bundle_dir: &Path) -> Result<PathBuf, String> {
    let name = local_service_binary_name();
    let candidates = [
        root.join("local-service/target/release").join(&name),
        bundle_dir.join("runtime").join(&name),
        root.join("local-service/target/debug").join(&name),
    ];
    let mut best: Option<(PathBuf, std::time::SystemTime)> = None;
    for candidate in candidates {
        if !candidate.is_file() {
            continue;
        }
        let Ok(modified) = candidate.metadata().and_then(|m| m.modified()) else {
            continue;
        };
        if best
            .as_ref()
            .map(|(_, ts)| modified > *ts)
            .unwrap_or(true)
        {
            best = Some((candidate, modified));
        }
    }
    if let Some((path, _)) = best {
        return Ok(path);
    }
    Err(format!(
        "未找到 local-service 二进制 ({name})，请先运行 npm run bundle"
    ))
}

fn repo_root(app: &AppHandle) -> Result<PathBuf, String> {
    if let Ok(root) = std::env::var("HUOKE_ROOT") {
        let path = normalize_path(&PathBuf::from(root));
        if let Some(found) = find_launch_root(&path) {
            return Ok(found);
        }
    }

    let resource_dir = normalize_path(
        &app
            .path()
            .resource_dir()
            .map_err(|err| err.to_string())?,
    );
    if let Some(found) = find_launch_root(&resource_dir) {
        return Ok(found);
    }

    if cfg!(windows) {
        if let Ok(exe_dir) = app.path().executable_dir() {
            let exe_dir = normalize_path(&exe_dir);
            if let Some(found) = find_launch_root(&exe_dir) {
                return Ok(found);
            }
        }
    }

    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let dev_root = manifest_dir
        .parent()
        .and_then(|p| p.parent())
        .ok_or_else(|| "无法定位 Huoke 工程根目录".to_string())?;
    if let Some(found) = find_launch_root(dev_root) {
        return Ok(found);
    }

    Err("无法定位 Huoke 工程根目录，请重新安装应用".into())
}

fn resolve_bundle_dir(root: &Path, app: &AppHandle) -> Result<PathBuf, String> {
    if let Some(dir) = find_bundle_dir(root) {
        return Ok(dir);
    }

    if let Ok(resource_dir) = app.path().resource_dir() {
        let resource_dir = normalize_path(&resource_dir);
        for candidate in [
            resource_dir.join("desktop/bundle"),
            resource_dir.join("bundle"),
        ] {
            if is_bundle_dir(&candidate) {
                return Ok(candidate);
            }
        }
    }

    if cfg!(windows) {
        if let Ok(exe_dir) = app.path().executable_dir() {
            let exe_dir = normalize_path(&exe_dir);
            for candidate in [
                exe_dir.join("resources/desktop/bundle"),
                exe_dir.join("desktop/bundle"),
                exe_dir.join("bundle"),
            ] {
                if is_bundle_dir(&candidate) {
                    return Ok(candidate);
                }
            }
        }
    }

    Err(format!(
        "未找到桌面 bundle。HUOKE_ROOT={}",
        root.display()
    ))
}

fn desktop_data_dir(app: &AppHandle) -> PathBuf {
    if let Some(data_dir) = windows_data_dir() {
        return PathBuf::from(data_dir);
    }
    app.path()
        .app_data_dir()
        .unwrap_or_else(|_| PathBuf::from("."))
}

fn start_local_service(
    root: &Path,
    bundle_dir: &Path,
    data_dir: &Path,
    log_file: &Path,
    log_state: Arc<BackendLogState>,
) -> Result<BackendProcess, String> {
    let binary = find_local_service_binary(root, bundle_dir)?;
    let mut command = Command::new(&binary);
    command
        .env("HUOKE_LOCAL_PORT", LOCAL_SERVICE_PORT.to_string())
        .env("HUOKE_DATA_DIR", data_dir)
        .env("HUOKE_LOG_FILE", log_file)
        .env("HUOKE_ROOT", root)
        .current_dir(root)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());

    win_process::hide_console(&mut command);

    let log_file = Arc::new(log_file.to_path_buf());
    let mut child = command
        .spawn()
        .map_err(|err| format!("启动 local-service 失败: {err}"))?;

    let mut log_readers = Vec::new();
    if let Some(handle) = spawn_log_reader(
        child.stdout.take(),
        Arc::clone(&log_file),
        Arc::clone(&log_state),
    ) {
        log_readers.push(handle);
    }
    if let Some(handle) = spawn_log_reader(child.stderr.take(), log_file, log_state) {
        log_readers.push(handle);
    }

    Ok(BackendProcess { child, log_readers })
}

fn start_thin_stack(
    root: &PathBuf,
    bundle_dir: &Path,
    app: &AppHandle,
    log_file: &Path,
    log_state: Arc<BackendLogState>,
) -> Result<(BackendProcess, JoinHandle<()>), String> {
    let frontend_dist = resolve_frontend_dist(root, bundle_dir)?;
    let data_dir = desktop_data_dir(app);
    std::fs::create_dir_all(&data_dir).map_err(|err| err.to_string())?;

    port_reclaim::reclaim_huoke_ports(DESKTOP_PORT, LOCAL_SERVICE_PORT);

    let static_handle =
        static_server::spawn_static_server(frontend_dist, DESKTOP_PORT).map_err(|err| err.to_string())?;
    let local_service = start_local_service(root, bundle_dir, &data_dir, log_file, log_state)?;
    Ok((local_service, static_handle))
}

fn windows_data_dir() -> Option<String> {
    if !cfg!(windows) {
        return None;
    }
    std::env::var("APPDATA")
        .ok()
        .map(|app_data| format!(r"{app_data}\com.huoke.desktop"))
}

fn spawn_log_reader<R>(
    stream: Option<R>,
    log_file: Arc<PathBuf>,
    log_state: Arc<BackendLogState>,
) -> Option<JoinHandle<()>>
where
    R: std::io::Read + Send + 'static,
{
    stream.map(|stream| {
        thread::spawn(move || {
            let reader = BufReader::new(stream);
            for line in reader.lines().map_while(Result::ok) {
                append_unified_log(&log_file, &line);
                log::info!("[backend] {line}");
                log_state.push_line(line);
            }
        })
    })
}

fn drain_log_readers(handles: Vec<JoinHandle<()>>) {
    for handle in handles {
        let _ = handle.join();
    }
}

fn verify_static_frontend_route(client: &reqwest::blocking::Client) -> bool {
    client
        .get(APP_HOME_URL)
        .send()
        .map(|resp| resp.status().is_success())
        .unwrap_or(false)
}

fn format_backend_failure(base: &str, log_state: &BackendLogState) -> String {
    let tail = log_state.tail(80);
    if tail.is_empty() {
        return base.to_string();
    }
    format!("{base}\n\n后端输出（最近 80 行）:\n{tail}")
}

fn wait_backend_ready(
    timeout: Duration,
    backend: &mut BackendProcess,
    log_state: &BackendLogState,
    log_hint: &str,
) -> Result<(), String> {
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(2))
        .build()
        .map_err(|err| err.to_string())?;
    let deadline = Instant::now() + timeout;

    loop {
        if Instant::now() >= deadline {
            drain_log_readers(std::mem::take(&mut backend.log_readers));
            let base = format!(
                "桌面服务启动超时（静态 {DESKTOP_PORT} / local-service {LOCAL_SERVICE_PORT}）。请查看日志:\n{log_hint}",
                DESKTOP_PORT = DESKTOP_PORT,
                LOCAL_SERVICE_PORT = LOCAL_SERVICE_PORT,
            );
            return Err(format_backend_failure(&base, log_state));
        }

        let static_ok = client
            .get(STATIC_HEALTH_URL)
            .send()
            .map(|resp| resp.status().is_success())
            .unwrap_or(false);
        let local_ok = client
            .get(LOCAL_SERVICE_HEALTH_URL)
            .send()
            .map(|resp| resp.status().is_success())
            .unwrap_or(false);

        if static_ok && local_ok && verify_static_frontend_route(&client) {
            return Ok(());
        }

        if let Ok(Some(status)) = backend.child.try_wait() {
            drain_log_readers(std::mem::take(&mut backend.log_readers));
            let code = status
                .code()
                .map(|c| c.to_string())
                .unwrap_or_else(|| status.to_string());
            let base = format!("local-service 进程异常退出 (code={code})。\n日志: {log_hint}");
            return Err(format_backend_failure(&base, log_state));
        }

        thread::sleep(Duration::from_millis(500));
    }
}

fn initialize_runtime_env() {
    let client = match reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(10))
        .build()
    {
        Ok(client) => client,
        Err(err) => {
            log::warn!("runtime init client failed: {err}");
            return;
        }
    };
    match client.post(LOCAL_SERVICE_INIT_URL).send() {
        Ok(resp) if resp.status().is_success() => {
            log::info!("runtime environment initialized");
        }
        Ok(resp) => {
            log::warn!("runtime init HTTP {}", resp.status());
        }
        Err(err) => {
            log::warn!("runtime init request failed: {err}");
        }
    }
}

fn stop_backend(state: &ServiceState) {
    let mut guard = state.backend.lock().expect("backend lock");
    if let Some(mut child) = guard.take() {
        let _ = child.kill();
        let _ = child.wait();
    }
}

fn with_main_thread<R, F>(app: &AppHandle, f: F) -> Result<R, String>
where
    F: FnOnce(&AppHandle) -> Result<R, String> + Send + 'static,
    R: Send + 'static,
{
    let (tx, rx) = std::sync::mpsc::channel();
    let handle = app.clone();
    app.run_on_main_thread(move || {
        let _ = tx.send(f(&handle));
    })
    .map_err(|err| err.to_string())?;
    rx.recv()
        .map_err(|_| "主线程任务未完成".to_string())?
}

fn percent_encode_data_url(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    for byte in text.bytes() {
        match byte {
            65..=90 | 97..=122 | 48..=57 | 45 | 95 | 46 | 126 => {
                out.push(byte as char);
            }
            _ => out.push_str(&format!("%{byte:02X}")),
        }
    }
    out
}

fn escape_html(text: &str) -> String {
    text.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
}

fn navigate_html_page(window: &tauri::WebviewWindow, html: &str) -> Result<(), String> {
    let url = format!(
        "data:text/html;charset=utf-8,{}",
        percent_encode_data_url(html)
    );
    window
        .navigate(
            url.parse()
                .map_err(|err| format!("invalid data url: {err}"))?,
        )
        .map_err(|err| format!("navigate failed: {err}"))
}

const SPLASH_BACKGROUND: Color = Color(6, 8, 24, 255);

fn apply_splash_window_theme(window: &tauri::WebviewWindow) {
    let _ = window.set_background_color(Some(SPLASH_BACKGROUND));
}

fn focus_main_window(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
}

fn show_startup_error(app: &AppHandle, message: &str) {
    let log_hint = desktop_log_hint(app);
    let html = format!(
        r#"<!doctype html><html><head><meta charset="utf-8"><title>启动失败</title>
<style>body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;padding:32px;line-height:1.6;color:#222}}
h1{{color:#c0392b}}pre{{white-space:pre-wrap;background:#f6f6f6;padding:16px;border-radius:8px;font-size:13px}}</style></head>
<body><h1>获客平台启动失败</h1><pre>{}</pre>
<p>日志文件: {}</p>
<p>请打开上述日志；确认端口 {}（静态 UI）与 {}（插件桥接）未被占用后重试。</p></body></html>"#,
        escape_html(message),
        escape_html(&log_hint),
        DESKTOP_PORT,
        LOCAL_SERVICE_PORT,
    );
    if let Some(window) = app.get_webview_window("main") {
        let _ = navigate_html_page(&window, &html);
    }
}

fn open_app_home(app: &AppHandle) -> Result<(), String> {
    let main = app
        .get_webview_window("main")
        .ok_or_else(|| "主窗口不存在".to_string())?;
    let parsed = APP_HOME_URL
        .parse()
        .map_err(|err| format!("invalid url: {err}"))?;
    main.navigate(parsed)
        .map_err(|err| format!("打开获客首页失败: {err}"))?;
    Ok(())
}

fn bootstrap(app: &AppHandle, log_state: Arc<BackendLogState>) -> Result<(), String> {
    let root = repo_root(app)?;
    let log_file = resolve_app_log_file(app)?;
    let log_hint = display_path(&log_file);
    log::info!("Huoke root: {}", root.display());
    log::info!("Unified log file: {log_hint}");

    let bundle_dir = resolve_bundle_dir(&root, app)?;
    let data_dir = desktop_data_dir(app);
    let (mut backend, _static_server) =
        start_thin_stack(&root, &bundle_dir, app, &log_file, Arc::clone(&log_state))?;
    wait_backend_ready(
        Duration::from_secs(60),
        &mut backend,
        &log_state,
        &log_hint,
    )?;

    // Do not join log reader threads here: they block until backend stdout/stderr
    // close, which only happens when the process exits — leaving the UI on about:blank.
    let BackendProcess { child, log_readers: _ } = backend;

    {
        let state = app.state::<ServiceState>();
        state
            .backend
            .lock()
            .expect("backend lock")
            .replace(child);
        *state.bundle_dir.lock().expect("bundle lock") = Some(bundle_dir.clone());
        *state.data_dir.lock().expect("data lock") = Some(data_dir.clone());
    }

    with_main_thread(app, open_app_home)?;
    log::info!("Huoke thin desktop ready at {APP_HOME_URL}");

    thread::spawn(initialize_runtime_env);

    let bundle_dir_bg = bundle_dir.clone();
    let data_dir_bg = data_dir.clone();
    thread::spawn(move || {
        let status =
            extension_bootstrap::build_setup_status(&bundle_dir_bg, &data_dir_bg, None);
        log::info!(
            "extension status (deferred): installed={} chrome={} connected={}",
            status.extension_installed,
            status.chrome_found,
            status.bridge_connected
        );
        if !status.bridge_connected && !status.chrome_found {
            log::warn!("Chrome not found — user must install Chrome to use automation");
        }
    });

    Ok(())
}

#[tauri::command]
fn restart_desktop_app(app: AppHandle) -> Result<(), String> {
    stop_backend(&*app.state::<ServiceState>());
    app.restart();
}

#[tauri::command]
fn get_extension_setup_status(app: AppHandle) -> Result<ExtensionSetupStatus, String> {
    let state = app.state::<ServiceState>();
    let bundle_dir = state
        .bundle_dir
        .lock()
        .expect("bundle lock")
        .clone()
        .ok_or_else(|| "桌面服务尚未就绪".to_string())?;
    let data_dir = state
        .data_dir
        .lock()
        .expect("data lock")
        .clone()
        .ok_or_else(|| "桌面服务尚未就绪".to_string())?;
    Ok(extension_bootstrap::build_setup_status(
        &bundle_dir,
        &data_dir,
        None,
    ))
}

#[tauri::command]
fn launch_chrome_extension(app: AppHandle) -> Result<ExtensionSetupStatus, String> {
    let state = app.state::<ServiceState>();
    let bundle_dir = state
        .bundle_dir
        .lock()
        .expect("bundle lock")
        .clone()
        .ok_or_else(|| "桌面服务尚未就绪".to_string())?;
    let data_dir = state
        .data_dir
        .lock()
        .expect("data lock")
        .clone()
        .ok_or_else(|| "桌面服务尚未就绪".to_string())?;

    let extension_dir = extension_bootstrap::ensure_extension_installed(&bundle_dir, &data_dir)?;
    let chrome = extension_bootstrap::find_chrome_executable()
        .ok_or_else(|| "未找到 Google Chrome，请先安装 https://www.google.com/chrome/".to_string())?;
    extension_bootstrap::launch_chrome_with_extension(
        &chrome,
        &extension_dir,
        &extension_bootstrap::chrome_profile_dir(&data_dir),
    )?;

    for _ in 0..24 {
        std::thread::sleep(Duration::from_millis(500));
        if extension_bootstrap::bridge_client_count() > 0 {
            break;
        }
    }

    Ok(extension_bootstrap::build_setup_status(
        &bundle_dir,
        &data_dir,
        None,
    ))
}

#[tauri::command]
fn open_external_url(url: String) -> Result<(), String> {
    extension_bootstrap::open_external_url(&url)
}

#[tauri::command]
fn open_extension_folder(app: AppHandle) -> Result<(), String> {
    let data_dir = app
        .state::<ServiceState>()
        .data_dir
        .lock()
        .expect("data lock")
        .clone()
        .unwrap_or_else(|| desktop_data_dir(&app));

    if let Ok(root) = repo_root(&app) {
        if let Ok(bundle_dir) = resolve_bundle_dir(&root, &app) {
            let _ = extension_bootstrap::ensure_extension_installed(&bundle_dir, &data_dir);
        }
    }

    extension_bootstrap::open_path_in_explorer(&extension_bootstrap::extension_install_dir(
        &data_dir,
    ))
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            log::info!("single-instance: focusing existing window");
            focus_main_window(app);
        }))
        .plugin(
            tauri_plugin_log::Builder::default()
                .level(log::LevelFilter::Info)
                .build(),
        )
        .manage(ServiceState {
            backend: Mutex::new(None),
            bundle_dir: Mutex::new(None),
            data_dir: Mutex::new(None),
        })
        .manage(Arc::new(BackendLogState {
            lines: Mutex::new(Vec::new()),
        }))
        .invoke_handler(tauri::generate_handler![
            restart_desktop_app,
            get_extension_setup_status,
            launch_chrome_extension,
            open_extension_folder,
            open_external_url,
        ])
        .setup(|app| {
            if let Some(window) = app.get_webview_window("main") {
                apply_splash_window_theme(&window);
            }
            focus_main_window(app.handle());

            let handle = app.handle().clone();
            let log_state = {
                let state = app.state::<Arc<BackendLogState>>();
                Arc::clone(&state)
            };
            std::thread::spawn(move || match bootstrap(&handle, log_state) {
                Ok(()) => {}
                Err(err) => {
                    log::error!("bootstrap failed: {err}");
                    let app = handle.clone();
                    let message = err;
                    let _ = handle.run_on_main_thread(move || show_startup_error(&app, &message));
                }
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                stop_backend(&*app.state::<ServiceState>());
                return;
            }

            if let RunEvent::WindowEvent {
                label,
                event: WindowEvent::CloseRequested { .. },
                ..
            } = event
            {
                if label == "main" {
                    stop_backend(&*app.state::<ServiceState>());
                }
            }
        });
}
