use huoke_local_service::{app, config};

use tracing::info;

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "info,huoke_local_service=debug".into()),
        )
        .init();

    let config = config::AppConfig::from_env();
    let app_state = app::build_app_state(&config);
    let router = app::build_router(app_state);

    let addr = config.addr();
    info!("huoke-local-service listening on http://{addr}");
    info!("websocket endpoint: ws://{addr}/ws");
    info!("sqlite database: {}", config.db_path().display());
    if huoke_local_service::simulate::enabled() {
        info!("HUOKE_SIMULATE=1 — orchestration sleeps compressed");
    }

    let listener = match tokio::net::TcpListener::bind(&addr).await {
        Ok(listener) => listener,
        Err(err) if err.kind() == std::io::ErrorKind::AddrInUse => {
            eprintln!(
                "端口 {addr} 已被占用。请关闭其它获客平台实例，或执行: lsof -tiTCP:{port} -sTCP:LISTEN | xargs kill",
                port = config.port
            );
            std::process::exit(101);
        }
        Err(err) => {
            eprintln!("绑定 local-service 端口 {addr} 失败: {err}");
            std::process::exit(1);
        }
    };
    if let Err(err) = axum::serve(listener, router).await {
        eprintln!("local-service 运行失败: {err}");
        std::process::exit(1);
    }
}
