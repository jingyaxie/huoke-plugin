mod config;
mod protocol;
mod ws;
mod api;
mod db;
mod douyin;
mod capture;
mod outreach;
mod plugin_lab;
mod state;

use std::sync::Arc;

use axum::{
    routing::{get, post},
    Router,
};
use axum::extract::ws::{WebSocket, WebSocketUpgrade};
use axum::extract::State;
use axum::response::IntoResponse;
use tower_http::cors::{Any, CorsLayer};
use tracing::info;

use capture::CaptureService;
use config::AppConfig;
use db::Database;
use outreach::OutreachService;
use state::AppState;
use ws::BridgeHub;

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "info,huoke_local_service=debug".into()),
        )
        .init();

    let config = AppConfig::from_env();
    let hub = BridgeHub::new();
    let db = Database::open(&config.db_path()).expect("open sqlite database");
    let default_daily_quota = std::env::var("HUOKE_DAILY_REPLY_QUOTA")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(50);
    let capture = Arc::new(CaptureService::new(db.clone(), hub.clone()));
    capture.spawn_event_listener();
    let outreach = Arc::new(OutreachService::new(db.clone(), hub.clone(), default_daily_quota));

    let app_state = AppState {
        hub: hub.clone(),
        db,
        capture,
        outreach,
        default_daily_quota,
    };

    let app = Router::new()
        .route("/health", get(api::health))
        .route("/ws", get(ws_handler))
        .route("/bridge/status", get(api::bridge_status))
        .route("/bridge/ping", post(api::bridge_ping))
        .route("/bridge/command", post(api::bridge_command))
        .route("/api/douyin/jobs", post(api::douyin::create_job).get(api::douyin::list_jobs))
        .route("/api/douyin/jobs/:job_id", get(api::douyin::get_job))
        .route(
            "/api/douyin/jobs/:job_id/videos",
            get(api::douyin::list_job_videos),
        )
        .route(
            "/api/douyin/jobs/:job_id/comments",
            get(api::douyin::list_job_comments),
        )
        .route(
            "/api/douyin/jobs/:job_id/start",
            post(api::douyin::start_job),
        )
        .route("/api/douyin/quota", get(api::outreach::get_quota))
        .route("/api/douyin/reply", post(api::outreach::reply_once))
        .route(
            "/api/douyin/outreach/tasks",
            post(api::outreach::create_outreach_task).get(api::outreach::list_outreach_tasks),
        )
        .route(
            "/api/douyin/outreach/tasks/:task_id",
            get(api::outreach::get_outreach_task),
        )
        .route(
            "/api/douyin/outreach/tasks/:task_id/items",
            get(api::outreach::list_outreach_items),
        )
        .route(
            "/api/douyin/outreach/tasks/:task_id/start",
            post(api::outreach::start_outreach_task),
        )
        .route(
            "/api/douyin/outreach/tasks/:task_id/pause",
            post(api::outreach::pause_outreach_task),
        )
        .route("/api/plugin-lab/status", get(api::plugin_lab::status))
        .route(
            "/api/plugin-lab/actions/:action_id",
            post(api::plugin_lab::run_action),
        )
        .with_state(app_state)
        .layer(
            CorsLayer::new()
                .allow_origin(Any)
                .allow_methods(Any)
                .allow_headers(Any),
        );

    let addr = config.addr();
    info!("huoke-local-service listening on http://{addr}");
    info!("websocket endpoint: ws://{addr}/ws");
    info!("sqlite database: {}", config.db_path().display());

    let listener = tokio::net::TcpListener::bind(&addr)
        .await
        .expect("bind local-service port");
    axum::serve(listener, app).await.expect("server failed");
}

async fn ws_handler(ws: WebSocketUpgrade, State(state): State<AppState>) -> impl IntoResponse {
    ws.on_upgrade(move |socket: WebSocket| async move {
        state.hub.handle_socket(socket).await;
    })
}
