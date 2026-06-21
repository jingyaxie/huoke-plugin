use std::sync::Arc;

use axum::{
    extract::ws::{WebSocket, WebSocketUpgrade},
    extract::State,
    response::IntoResponse,
    routing::{delete, get, post},
    Router,
};
use tower_http::cors::{Any, CorsLayer};

use crate::api;
use crate::capture::CaptureService;
use crate::config::AppConfig;
use crate::db::Database;
use crate::outreach::OutreachService;
use crate::state::AppState;
use crate::ws::BridgeHub;

pub fn build_app_state(config: &AppConfig) -> AppState {
    let hub = BridgeHub::new();
    hub.reset_on_boot();
    let db = Database::open(&config.db_path()).expect("open sqlite database");
    if let Ok(n) = db.fail_stale_running_jobs("服务重启，任务已中断") {
        if n > 0 {
            tracing::info!("marked {n} stale running collect job(s) as failed on boot");
        }
    }
    let default_daily_quota = std::env::var("HUOKE_DAILY_REPLY_QUOTA")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(50);
    let capture = Arc::new(CaptureService::new(
        db.clone(),
        hub.clone(),
        default_daily_quota,
    ));
    capture.spawn_event_listener();
    let outreach = Arc::new(OutreachService::new(
        db.clone(),
        hub.clone(),
        default_daily_quota,
    ));

    AppState {
        hub,
        db,
        capture,
        outreach,
        default_daily_quota,
    }
}

pub fn build_router(state: AppState) -> Router {
    Router::new()
        .route("/health", get(api::health))
        .route("/ws", get(ws_handler))
        .route("/bridge/status", get(api::bridge_status))
        .route("/bridge/ping", post(api::bridge_ping))
        .route("/api/runtime/init", post(api::runtime::init))
        .route("/bridge/command", post(api::bridge_command))
        .route(
            "/api/douyin/jobs",
            post(api::douyin::create_job).get(api::douyin::list_jobs),
        )
        .route(
            "/api/douyin/jobs/:job_id/delete",
            post(api::douyin::delete_job),
        )
        .route("/api/douyin/jobs/:job_id", get(api::douyin::get_job).delete(api::douyin::delete_job))
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
        .route(
            "/api/douyin/interaction/stats",
            get(api::douyin::get_interaction_stats),
        )
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
        .route("/api/plugin-lab/snapshot", get(api::plugin_lab::snapshot))
        .route(
            "/api/plugin-lab/actions/:action_id/readiness",
            get(api::plugin_lab::readiness),
        )
        .route(
            "/api/plugin-lab/actions/:action_id",
            post(api::plugin_lab::run_action),
        )
        .with_state(state)
        .layer(
            CorsLayer::new()
                .allow_origin(Any)
                .allow_methods(Any)
                .allow_headers(Any),
        )
}

async fn ws_handler(ws: WebSocketUpgrade, State(state): State<AppState>) -> impl IntoResponse {
    ws.on_upgrade(move |socket: WebSocket| async move {
        state.hub.handle_socket(socket).await;
    })
}
