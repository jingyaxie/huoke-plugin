use axum::{extract::State, Json};
use serde::Serialize;
use serde_json::json;
use std::time::Duration;

use crate::bundle_info::{
    evaluate_extension_versions, read_bundle_info, read_installed_extension_version,
};
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
    pub extension_clients: usize,
    pub ws_path: &'static str,
    pub extension_ready: bool,
    #[serde(flatten)]
    pub version: crate::bundle_info::ExtensionVersionStatus,
}

pub async fn bridge_status(State(state): State<AppState>) -> Json<BridgeStatusResponse> {
    let extension_clients = state.hub.extension_client_count();
    let bundle = read_bundle_info(&state.data_dir);
    let installed = read_installed_extension_version(&state.data_dir);
    let connected = state.hub.connected_extension_version();
    let build_id = state.hub.connected_extension_build_id();
    let version = evaluate_extension_versions(
        bundle.as_ref(),
        installed.as_deref(),
        connected.as_deref(),
        build_id.as_deref(),
    );
    Json(BridgeStatusResponse {
        connected_clients: extension_clients,
        extension_clients,
        ws_path: "/ws",
        extension_ready: extension_clients > 0,
        version,
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

pub mod collect;
pub mod douyin;
pub mod outreach;
pub mod plugin_lab;
pub mod runtime;
pub mod settings;
