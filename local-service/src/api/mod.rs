use axum::{extract::State, Json};
use serde::Serialize;
use serde_json::json;
use std::time::Duration;

use crate::state::AppState;

#[derive(Serialize)]
pub struct HealthResponse {
    pub ok: bool,
    pub service: &'static str,
    pub version: &'static str,
}

pub async fn health() -> Json<HealthResponse> {
    Json(HealthResponse {
        ok: true,
        service: "huoke-local-service",
        version: env!("CARGO_PKG_VERSION"),
    })
}

#[derive(Serialize)]
pub struct BridgeStatusResponse {
    pub connected_clients: usize,
    pub ws_path: &'static str,
}

pub async fn bridge_status(State(state): State<AppState>) -> Json<BridgeStatusResponse> {
    Json(BridgeStatusResponse {
        connected_clients: state.hub.client_count(),
        ws_path: "/ws",
    })
}

#[derive(serde::Deserialize)]
pub struct BridgeCommandRequest {
    pub action: String,
    #[serde(default)]
    pub payload: serde_json::Value,
    #[serde(default)]
    pub wait: bool,
    #[serde(default = "default_timeout_ms")]
    pub timeout_ms: u64,
}

fn default_timeout_ms() -> u64 {
    30_000
}

#[derive(Serialize)]
pub struct BridgeCommandResponse {
    pub queued: bool,
    pub action: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub result: Option<serde_json::Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

pub async fn bridge_command(
    State(state): State<AppState>,
    Json(body): Json<BridgeCommandRequest>,
) -> Json<BridgeCommandResponse> {
    if body.wait {
        match state
            .hub
            .request_command(
                &body.action,
                body.payload,
                Duration::from_millis(body.timeout_ms.clamp(1000, 120_000)),
            )
            .await
        {
            Ok(result) => Json(BridgeCommandResponse {
                queued: true,
                action: body.action,
                result: Some(result),
                error: None,
            }),
            Err(err) => Json(BridgeCommandResponse {
                queued: false,
                action: body.action,
                result: None,
                error: Some(err),
            }),
        }
    } else {
        let queued = state.hub.broadcast_command(&body.action, body.payload).await;
        Json(BridgeCommandResponse {
            queued,
            action: body.action,
            result: None,
            error: None,
        })
    }
}

pub async fn bridge_ping(State(state): State<AppState>) -> Json<serde_json::Value> {
    let queued = state.hub.broadcast_command("ping", json!({})).await;
    Json(json!({ "queued": queued }))
}

pub mod douyin;
pub mod outreach;
pub mod plugin_lab;
