use std::time::Duration;

use axum::{extract::State, Json};
use serde::Serialize;
use serde_json::json;

use crate::state::AppState;

#[derive(Serialize)]
pub struct RuntimeInitResponse {
    pub ok: bool,
    pub stale_jobs_failed: usize,
    pub extension_clients: usize,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub extension_reset: Option<serde_json::Value>,
    pub message: String,
}

/// 重新初始化本地运行环境：清理 Hub 挂起命令、标记僵尸任务、通知插件重置会话与 WS。
pub async fn init(State(state): State<AppState>) -> Json<RuntimeInitResponse> {
    state.hub.reset_runtime().await;

    let stale_jobs = state
        .db
        .fail_stale_running_jobs("运行环境已重新初始化")
        .unwrap_or(0);

    let extension_clients = state.hub.extension_client_count();
    let extension_reset = if extension_clients > 0 {
        state
            .hub
            .request_command("huoke.runtime.init", json!({}), Duration::from_secs(8))
            .await
            .ok()
    } else {
        None
    };

    let message = if extension_clients > 0 {
        format!(
            "运行环境已初始化（清理 {stale_jobs} 个僵尸任务，已通知 {extension_clients} 个插件连接重置）"
        )
    } else {
        format!(
            "运行环境已初始化（清理 {stale_jobs} 个僵尸任务；插件未连接，请在 Chrome 重新加载扩展）"
        )
    };

    Json(RuntimeInitResponse {
        ok: true,
        stale_jobs_failed: stale_jobs,
        extension_clients,
        extension_reset,
        message,
    })
}
