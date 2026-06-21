use huoke_local_service::simulate::run_mock_extension;

#[tokio::main]
async fn main() {
    let port = std::env::var("HUOKE_LOCAL_PORT")
        .ok()
        .unwrap_or_else(|| "18767".into());
    let ws_url = std::env::var("HUOKE_WS_URL")
        .ok()
        .unwrap_or_else(|| format!("ws://127.0.0.1:{port}/ws"));

    if let Err(err) = run_mock_extension(&ws_url).await {
        eprintln!("mock-extension failed: {err}");
        std::process::exit(1);
    }
}
