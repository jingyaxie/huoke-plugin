use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    Json,
};
use serde::{Deserialize, Serialize};
use serde_json::json;

use crate::db::{OutreachItemDraft, OutreachTask, OutreachTaskStatus, QuotaStatus};
use crate::state::AppState;

#[derive(Deserialize)]
pub struct CreateOutreachTaskRequest {
    pub name: Option<String>,
    pub source_job_id: Option<String>,
    pub reply_text: String,
    #[serde(default = "default_max_items")]
    pub max_items: i64,
    #[serde(default = "default_max_retries")]
    pub max_retries: i64,
    #[serde(default = "default_interval_ms")]
    pub interval_ms: i64,
    #[serde(default = "default_daily_quota")]
    pub daily_quota: i64,
    #[serde(default)]
    pub min_digg_count: i64,
}

fn default_max_items() -> i64 {
    10
}

fn default_max_retries() -> i64 {
    2
}

fn default_interval_ms() -> i64 {
    4000
}

fn default_daily_quota() -> i64 {
    50
}

#[derive(Serialize)]
pub struct CreateOutreachTaskResponse {
    pub task: OutreachTask,
    pub inserted_items: usize,
}

#[derive(Deserialize)]
pub struct CreateReplyRequest {
    pub video_url: Option<String>,
    pub aweme_id: Option<String>,
    pub comment_id: Option<String>,
    pub comment_text: Option<String>,
    pub reply_text: String,
    #[serde(default)]
    pub dry_run: bool,
}

pub async fn get_quota(State(state): State<AppState>) -> Result<Json<QuotaStatus>, ApiError> {
    let quota = state
        .db
        .get_quota_status(state.default_daily_quota)
        .map_err(internal_error)?;
    Ok(Json(quota))
}

pub async fn create_outreach_task(
    State(state): State<AppState>,
    Json(body): Json<CreateOutreachTaskRequest>,
) -> Result<Json<CreateOutreachTaskResponse>, ApiError> {
    let reply_text = body.reply_text.trim();
    if reply_text.is_empty() {
        return Err(bad_request("reply_text is required"));
    }

    let source_job_id = body.source_job_id.as_deref().map(str::trim).filter(|s| !s.is_empty());
    if source_job_id.is_none() {
        return Err(bad_request("source_job_id is required"));
    }
    let source_job_id = source_job_id.unwrap();

    let _ = state.db.get_job(source_job_id).map_err(|_| not_found("collect job not found"))?;
    let comments = state
        .db
        .list_comments_for_job(source_job_id, None, body.max_items.clamp(1, 200))
        .map_err(internal_error)?;

    let videos = state
        .db
        .list_videos_for_job(source_job_id)
        .map_err(internal_error)?;
    let video_url_by_aweme: std::collections::HashMap<String, String> = videos
        .into_iter()
        .map(|v| (v.aweme_id.clone(), v.video_url))
        .collect();

    let drafts: Vec<OutreachItemDraft> = comments
        .into_iter()
        .filter(|c| c.digg_count >= body.min_digg_count)
        .filter(|c| c.parent_comment_id.is_none())
        .take(body.max_items.clamp(1, 200) as usize)
        .map(|comment| {
            let video_url = video_url_by_aweme
                .get(&comment.aweme_id)
                .cloned()
                .unwrap_or_else(|| format!("https://www.douyin.com/video/{}", comment.aweme_id));
            OutreachItemDraft {
                video_url,
                aweme_id: comment.aweme_id,
                comment_id: comment.comment_id,
                comment_text: comment.content,
                reply_text: reply_text.to_string(),
            }
        })
        .collect();

    if drafts.is_empty() {
        return Err(bad_request("no eligible comments found in source job"));
    }

    let name = body
        .name
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .unwrap_or("抖音评论触达")
        .to_string();

    let task = state
        .db
        .create_outreach_task(
            &name,
            Some(source_job_id),
            body.max_retries.clamp(0, 5),
            body.interval_ms.clamp(1000, 30000),
            body.daily_quota.clamp(1, 500),
        )
        .map_err(internal_error)?;

    let inserted = state
        .db
        .add_outreach_items(&task.id, &drafts)
        .map_err(internal_error)?;

    Ok(Json(CreateOutreachTaskResponse { task, inserted_items: inserted }))
}

pub async fn list_outreach_tasks(
    State(state): State<AppState>,
) -> Result<Json<Vec<OutreachTask>>, ApiError> {
    let tasks = state.db.list_outreach_tasks(50).map_err(internal_error)?;
    Ok(Json(tasks))
}

pub async fn get_outreach_task(
    State(state): State<AppState>,
    Path(task_id): Path<String>,
) -> Result<Json<OutreachTask>, ApiError> {
    let task = state.db.get_outreach_task(&task_id).map_err(|_| not_found("task not found"))?;
    Ok(Json(task))
}

pub async fn list_outreach_items(
    State(state): State<AppState>,
    Path(task_id): Path<String>,
    Query(query): Query<ListItemsQuery>,
) -> Result<Json<serde_json::Value>, ApiError> {
    let _ = state.db.get_outreach_task(&task_id).map_err(|_| not_found("task not found"))?;
    let items = state
        .db
        .list_outreach_items(&task_id, query.limit.clamp(1, 2000))
        .map_err(internal_error)?;
    Ok(Json(json!({ "task_id": task_id, "items": items })))
}

#[derive(Deserialize)]
pub struct ListItemsQuery {
    #[serde(default = "default_items_limit")]
    pub limit: i64,
}

fn default_items_limit() -> i64 {
    200
}

pub async fn start_outreach_task(
    State(state): State<AppState>,
    Path(task_id): Path<String>,
) -> Result<Json<serde_json::Value>, ApiError> {
    let task = state.db.get_outreach_task(&task_id).map_err(|_| not_found("task not found"))?;
    if task.status == OutreachTaskStatus::Running {
        return Ok(Json(json!({
            "task_id": task_id,
            "status": "running",
            "message": "already running"
        })));
    }
    if task.pending_count == 0 && task.status == OutreachTaskStatus::Completed {
        return Ok(Json(json!({
            "task_id": task_id,
            "status": "completed",
            "message": "already completed"
        })));
    }

    state.outreach.clone().spawn_task(task_id.clone());
    Ok(Json(json!({
        "task_id": task_id,
        "status": "running",
        "message": "outreach task started — keep Douyin tab active in Chrome"
    })))
}

pub async fn pause_outreach_task(
    State(state): State<AppState>,
    Path(task_id): Path<String>,
) -> Result<Json<serde_json::Value>, ApiError> {
    let _ = state.db.get_outreach_task(&task_id).map_err(|_| not_found("task not found"))?;
    state
        .db
        .update_outreach_task_status(&task_id, OutreachTaskStatus::Paused, None)
        .map_err(internal_error)?;
    Ok(Json(json!({ "task_id": task_id, "status": "paused" })))
}

pub async fn reply_once(
    State(state): State<AppState>,
    Json(body): Json<CreateReplyRequest>,
) -> Result<Json<serde_json::Value>, ApiError> {
    let reply_text = body.reply_text.trim();
    if reply_text.is_empty() {
        return Err(bad_request("reply_text is required"));
    }

    let quota = state
        .db
        .get_quota_status(state.default_daily_quota)
        .map_err(internal_error)?;
    if quota.remaining <= 0 && !body.dry_run {
        return Err((
            StatusCode::TOO_MANY_REQUESTS,
            Json(json!({ "error": "daily quota reached", "quota": quota })),
        ));
    }

    let payload = json!({
        "video_url": body.video_url,
        "aweme_id": body.aweme_id,
        "comment_id": body.comment_id,
        "comment_text": body.comment_text,
        "reply_text": reply_text,
        "dry_run": body.dry_run,
        "scroll_rounds": 12,
    });

    let result = state
        .hub
        .request_command(
            "douyin.comment.reply",
            payload,
            std::time::Duration::from_secs(45),
        )
        .await
        .map_err(|err| internal_error(err))?;

    let ok = result.get("ok").and_then(|v| v.as_bool()).unwrap_or(false);
    if ok && !body.dry_run {
        let _ = state
            .db
            .consume_reply_quota(state.default_daily_quota)
            .map_err(internal_error)?;
    }

    Ok(Json(json!({ "ok": ok, "result": result, "quota": state.db.get_quota_status(state.default_daily_quota).ok() })))
}

type ApiError = (StatusCode, Json<serde_json::Value>);

fn internal_error(err: String) -> ApiError {
    (
        StatusCode::INTERNAL_SERVER_ERROR,
        Json(json!({ "error": err })),
    )
}

fn bad_request(message: &str) -> ApiError {
    (StatusCode::BAD_REQUEST, Json(json!({ "error": message })))
}

fn not_found(message: &str) -> ApiError {
    (StatusCode::NOT_FOUND, Json(json!({ "error": message })))
}
