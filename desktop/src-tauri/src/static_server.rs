use std::net::SocketAddr;
use std::path::PathBuf;
use std::thread::JoinHandle;

use axum::routing::get;
use axum::Router;
use tower_http::services::{ServeDir, ServeFile};

pub fn spawn_static_server(dist_dir: PathBuf, port: u16) -> Result<JoinHandle<()>, String> {
    let index = dist_dir.join("index.html");
    if !index.is_file() {
        return Err(format!(
            "frontend dist missing index.html: {}",
            dist_dir.display()
        ));
    }

    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    let serve_dir = ServeDir::new(dist_dir.clone()).fallback(ServeFile::new(index));
    let app = Router::new()
        .route("/health", get(|| async { "ok" }))
        .fallback_service(serve_dir);

    let handle = std::thread::spawn(move || {
        let rt = tokio::runtime::Builder::new_multi_thread()
            .enable_all()
            .worker_threads(2)
            .build()
            .expect("static server runtime");
        rt.block_on(async move {
            let listener = tokio::net::TcpListener::bind(addr)
                .await
                .expect("bind static server port");
            log::info!("desktop static server listening on http://{addr}");
            if let Err(err) = axum::serve(listener, app).await {
                log::error!("static server failed: {err}");
            }
        });
    });

    Ok(handle)
}
