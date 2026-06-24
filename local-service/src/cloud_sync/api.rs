use axum::{
    extract::{Path, State},
    http::StatusCode,
    Json,
};
use serde::Deserialize;
use serde_json::json;

use crate::state::AppState;

use super::CONFIG_KEY;

#[derive(Deserialize)]
pub struct LinkCloudTaskRequest {
    pub cloud_task_id: String,
}

pub async fn link_cloud_task(
    State(state): State<AppState>,
    Path(job_id): Path<String>,
    Json(body): Json<LinkCloudTaskRequest>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    let cloud_task_id = body.cloud_task_id.trim();
    if cloud_task_id.is_empty() {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({ "error": "cloud_task_id is required" })),
        ));
    }
    if state.db.get_job(&job_id).is_err() {
        return Err((StatusCode::NOT_FOUND, Json(json!({ "error": "job not found" }))));
    }
    state
        .db
        .cloud_sync_set_cloud_task_id(&job_id, cloud_task_id)
        .map_err(|err| {
            (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(json!({ "error": err })),
            )
        })?;
    Ok(Json(json!({
        "ok": true,
        "job_id": job_id,
        "cloud_task_id": cloud_task_id,
        "config_key": CONFIG_KEY,
    })))
}
