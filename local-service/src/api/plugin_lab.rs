use std::time::Duration;

use axum::{
    extract::{Path, State},
    http::StatusCode,
    Json,
};
use serde::Serialize;
use serde_json::Value;

use crate::plugin_lab;
use crate::state::AppState;

#[derive(Serialize)]
pub struct PluginLabStatusResponse {
    pub ok: bool,
    pub connected_clients: usize,
    pub supported_actions: &'static [&'static str],
}

pub async fn status(State(state): State<AppState>) -> Json<PluginLabStatusResponse> {
    Json(PluginLabStatusResponse {
        ok: true,
        connected_clients: state.hub.extension_client_count(),
        supported_actions: plugin_lab::supported_actions(),
    })
}

#[derive(Serialize)]
pub struct PluginLabActionResponse {
    pub ok: bool,
    pub action: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub message: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub data: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

pub async fn run_action(
    State(state): State<AppState>,
    Path(action_id): Path<String>,
    Json(payload): Json<Value>,
) -> Result<Json<PluginLabActionResponse>, (StatusCode, Json<PluginLabActionResponse>)> {
    let bridge_action = plugin_lab::bridge_action_for(&action_id).ok_or_else(|| {
        (
            StatusCode::NOT_FOUND,
            Json(PluginLabActionResponse {
                ok: false,
                action: action_id.clone(),
                message: None,
                data: None,
                error: Some(format!("unsupported plugin-lab action: {action_id}")),
            }),
        )
    })?;

    if state.hub.extension_client_count() == 0 {
        return Err((
            StatusCode::SERVICE_UNAVAILABLE,
            Json(PluginLabActionResponse {
                ok: false,
                action: action_id.clone(),
                message: None,
                data: None,
                error: Some("no extension connected — load extension/dist and ensure badge shows OK".into()),
            }),
        ));
    }

    let normalized = plugin_lab::normalize_payload(&action_id, payload);
    match state
        .hub
        .request_command(
            bridge_action,
            normalized,
            action_timeout(&action_id),
        )
        .await
    {
        Ok(data) => {
            let message = data
                .get("message")
                .and_then(|v| v.as_str())
                .map(str::to_string);
            Ok(Json(PluginLabActionResponse {
                ok: true,
                action: action_id,
                message,
                data: Some(data),
                error: None,
            }))
        }
        Err(err) => Err((
            StatusCode::BAD_GATEWAY,
            Json(PluginLabActionResponse {
                ok: false,
                action: action_id,
                message: None,
                data: None,
                error: Some(err),
            }),
        )),
    }
}

pub async fn readiness(
    State(state): State<AppState>,
    Path(action_id): Path<String>,
) -> Result<Json<PluginLabActionResponse>, (StatusCode, Json<PluginLabActionResponse>)> {
    let bridge_action = plugin_lab::bridge_action_for(&action_id).ok_or_else(|| {
        (
            StatusCode::NOT_FOUND,
            Json(PluginLabActionResponse {
                ok: false,
                action: action_id.clone(),
                message: None,
                data: None,
                error: Some(format!("unsupported plugin-lab action: {action_id}")),
            }),
        )
    })?;

    if state.hub.extension_client_count() == 0 {
        return Err((
            StatusCode::SERVICE_UNAVAILABLE,
            Json(PluginLabActionResponse {
                ok: false,
                action: action_id.clone(),
                message: None,
                data: None,
                error: Some("no extension connected — load extension/dist and ensure badge shows OK".into()),
            }),
        ));
    }

    match state
        .hub
        .request_command(
            "plugin_lab.preflight",
            serde_json::json!({ "target_action": bridge_action }),
            Duration::from_secs(8),
        )
        .await
    {
        Ok(data) => {
            let can_execute = data
                .get("can_execute")
                .and_then(|v| v.as_bool())
                .unwrap_or(false);
            let message = data
                .get("message")
                .and_then(|v| v.as_str())
                .map(str::to_string);
            let error_msg = if can_execute {
                None
            } else {
                Some(
                    message
                        .clone()
                        .unwrap_or_else(|| "当前界面无法执行".into()),
                )
            };
            Ok(Json(PluginLabActionResponse {
                ok: can_execute,
                action: action_id,
                message,
                data: Some(data),
                error: error_msg,
            }))
        }
        Err(err) => Err((
            StatusCode::BAD_GATEWAY,
            Json(PluginLabActionResponse {
                ok: false,
                action: action_id,
                message: None,
                data: None,
                error: Some(err),
            }),
        )),
    }
}

pub async fn snapshot(
    State(state): State<AppState>,
) -> Result<Json<PluginLabActionResponse>, (StatusCode, Json<PluginLabActionResponse>)> {
    if state.hub.extension_client_count() == 0 {
        return Err((
            StatusCode::SERVICE_UNAVAILABLE,
            Json(PluginLabActionResponse {
                ok: false,
                action: "page_snapshot".into(),
                message: None,
                data: None,
                error: Some("no extension connected".into()),
            }),
        ));
    }

    match state
        .hub
        .request_command("plugin_lab.page_snapshot", serde_json::json!({}), Duration::from_secs(8))
        .await
    {
        Ok(data) => Ok(Json(PluginLabActionResponse {
            ok: true,
            action: "page_snapshot".into(),
            message: None,
            data: Some(data),
            error: None,
        })),
        Err(err) => Err((
            StatusCode::BAD_GATEWAY,
            Json(PluginLabActionResponse {
                ok: false,
                action: "page_snapshot".into(),
                message: None,
                data: None,
                error: Some(err),
            }),
        )),
    }
}

fn action_timeout(action_id: &str) -> Duration {
    match action_id {
        "input_search_text" | "scroll_and_collect_comments" | "click_search_btn" => {
            Duration::from_secs(120)
        }
        "reply_comment" | "input_dm_text" => Duration::from_secs(60),
        _ => Duration::from_secs(45),
    }
}
