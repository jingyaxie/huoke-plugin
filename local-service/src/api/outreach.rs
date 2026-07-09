use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    Json,
};
use serde::{Deserialize, Serialize};
use serde_json::json;

use crate::db::{
    OutreachCandidate, OutreachItemDraft, OutreachTask, OutreachTaskStatus, QuotaStatus,
};
use crate::state::AppState;

#[derive(Deserialize)]
pub struct CreateOutreachTaskRequest {
    pub name: Option<String>,
    pub source_job_id: Option<String>,
    #[serde(default = "default_platform")]
    pub platform: String,
    pub action_type: Option<String>,
    #[serde(default)]
    pub reply_text: String,
    #[serde(default)]
    pub dm_text: String,
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
    #[serde(default)]
    pub include_contacted: bool,
    #[serde(default)]
    pub recurring: bool,
    #[serde(default = "default_idle_sleep_ms")]
    pub idle_sleep_ms: i64,
    #[serde(default = "default_refill_batch_size")]
    pub refill_batch_size: i64,
}

fn default_platform() -> String {
    "douyin".into()
}

fn default_max_items() -> i64 {
    10
}

fn default_max_retries() -> i64 {
    2
}

fn default_interval_ms() -> i64 {
    20_000
}

fn default_daily_quota() -> i64 {
    50
}

fn default_idle_sleep_ms() -> i64 {
    10 * 60 * 1000
}

fn default_refill_batch_size() -> i64 {
    50
}

#[derive(Serialize)]
pub struct CreateOutreachTaskResponse {
    pub task: OutreachTask,
    pub inserted_items: usize,
}

#[derive(Serialize)]
pub struct OutreachCandidateResponse {
    pub candidates: Vec<OutreachCandidate>,
    pub total: usize,
}

#[derive(Deserialize)]
pub struct CandidateQuery {
    pub platform: Option<String>,
    pub source_job_id: Option<String>,
    #[serde(default = "default_candidate_limit")]
    pub limit: i64,
    #[serde(default)]
    pub include_contacted: bool,
}

fn default_candidate_limit() -> i64 {
    50
}

pub(crate) fn candidates_to_drafts(
    candidates: Vec<OutreachCandidate>,
    action_type: &str,
    reply_text: &str,
    dm_text: &str,
    min_digg_count: i64,
    max_items: i64,
) -> Vec<OutreachItemDraft> {
    candidates
        .into_iter()
        .filter(|c| c.digg_count >= min_digg_count)
        .take(max_items.clamp(1, 500) as usize)
        .map(|candidate| OutreachItemDraft {
            platform: candidate.platform,
            action_type: action_type.to_string(),
            source_job_id: Some(candidate.job_id),
            video_url: candidate.video_url,
            aweme_id: candidate.aweme_id,
            comment_id: candidate.comment_id,
            comment_text: candidate.comment_text,
            username: candidate.username,
            user_id: candidate.user_id,
            sec_uid: candidate.sec_uid,
            profile_url: candidate.profile_url,
            reply_text: reply_text.to_string(),
            dm_text: dm_text.to_string(),
        })
        .collect()
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
    let platform = crate::platforms::normalize_platform(&body.platform).to_string();
    let action_type = normalize_action_type(body.action_type.as_deref(), body.reply_text.trim())?;
    if platform == "xiaohongshu" && action_type.contains("dm") {
        return Err(bad_request("小红书 PC 网页版不支持私信任务"));
    }
    let dm_text = body.dm_text.trim();
    if action_type.contains("dm") && dm_text.is_empty() {
        return Err(bad_request("dm_text is required for dm outreach"));
    }

    let source_job_id = body
        .source_job_id
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty());
    let candidates = state
        .db
        .list_outreach_candidates(
            Some(&platform),
            source_job_id,
            body.max_items.clamp(1, 500),
            body.include_contacted,
        )
        .map_err(internal_error)?;

    let drafts = candidates_to_drafts(
        candidates,
        &action_type,
        body.reply_text.trim(),
        dm_text,
        body.min_digg_count,
        body.max_items.clamp(1, 500),
    );

    if drafts.is_empty() && !body.recurring {
        return Err(bad_request("no eligible precise comments found"));
    }

    let name = body
        .name
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .unwrap_or_else(|| default_outreach_name(&platform, &action_type))
        .to_string();

    let task = state
        .db
        .create_outreach_task(
            &name,
            source_job_id,
            &platform,
            &action_type,
            body.reply_text.trim(),
            dm_text,
            body.min_digg_count,
            body.include_contacted,
            body.max_retries.clamp(0, 5),
            body.interval_ms.clamp(5_000, 300_000),
            body.daily_quota.clamp(1, 500),
            body.recurring,
            body.idle_sleep_ms.clamp(60_000, 86_400_000),
            body.refill_batch_size.clamp(1, 500),
        )
        .map_err(internal_error)?;

    let inserted = state
        .db
        .add_outreach_items(&task.id, &drafts)
        .map_err(internal_error)?;

    Ok(Json(CreateOutreachTaskResponse {
        task,
        inserted_items: inserted,
    }))
}

pub async fn list_outreach_candidates(
    State(state): State<AppState>,
    Query(query): Query<CandidateQuery>,
) -> Result<Json<OutreachCandidateResponse>, ApiError> {
    let platform = query
        .platform
        .as_deref()
        .map(crate::platforms::normalize_platform)
        .map(str::to_string);
    let candidates = state
        .db
        .list_outreach_candidates(
            platform.as_deref(),
            query.source_job_id.as_deref(),
            query.limit.clamp(1, 1000),
            query.include_contacted,
        )
        .map_err(internal_error)?;
    Ok(Json(OutreachCandidateResponse {
        total: candidates.len(),
        candidates,
    }))
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
    let task = state
        .db
        .get_outreach_task(&task_id)
        .map_err(|_| not_found("task not found"))?;
    Ok(Json(task))
}

pub async fn list_outreach_items(
    State(state): State<AppState>,
    Path(task_id): Path<String>,
    Query(query): Query<ListItemsQuery>,
) -> Result<Json<serde_json::Value>, ApiError> {
    let _ = state
        .db
        .get_outreach_task(&task_id)
        .map_err(|_| not_found("task not found"))?;
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
    let task = state
        .db
        .get_outreach_task(&task_id)
        .map_err(|_| not_found("task not found"))?;
    if task.status == OutreachTaskStatus::Running {
        return Ok(Json(json!({
            "task_id": task_id,
            "status": "running",
            "message": "already running"
        })));
    }
    if task.pending_count == 0 && task.status == OutreachTaskStatus::Completed && !task.recurring {
        return Ok(Json(json!({
            "task_id": task_id,
            "status": "completed",
            "message": "already completed"
        })));
    }

    state
        .db
        .update_outreach_task_status(&task_id, OutreachTaskStatus::Running, None)
        .map_err(internal_error)?;
    state.outreach.clone().spawn_task(task_id.clone());
    Ok(Json(json!({
        "task_id": task_id,
        "status": "running",
        "message": "outreach task started — keep the platform tab active in Chrome"
    })))
}

pub async fn pause_outreach_task(
    State(state): State<AppState>,
    Path(task_id): Path<String>,
) -> Result<Json<serde_json::Value>, ApiError> {
    let _ = state
        .db
        .get_outreach_task(&task_id)
        .map_err(|_| not_found("task not found"))?;
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

    let aweme_id = body
        .aweme_id
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_string)
        .or_else(|| {
            body.video_url
                .as_deref()
                .and_then(|url| crate::douyin::parser::extract_aweme_id_from_url(url))
        })
        .ok_or_else(|| bad_request("aweme_id or video_url is required"))?;

    let comment_id = body.comment_id.as_deref().unwrap_or("").trim();
    let comment_text = body.comment_text.as_deref().unwrap_or("").trim();
    if comment_id.is_empty() && comment_text.is_empty() {
        return Err(bad_request("comment_id or comment_text is required"));
    }

    let lab = crate::lab_commands::LabCommands::new(&state.hub, "douyin");
    let result = lab
        .reply_to_comment(
            &aweme_id,
            comment_id,
            comment_text,
            reply_text,
            12,
            body.dry_run,
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

    Ok(Json(
        json!({ "ok": ok, "result": result, "quota": state.db.get_quota_status(state.default_daily_quota).ok() }),
    ))
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

fn normalize_action_type(raw: Option<&str>, reply_text: &str) -> Result<String, ApiError> {
    let value = raw
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .unwrap_or_else(|| {
            if reply_text.trim().is_empty() {
                "follow"
            } else {
                "reply"
            }
        });
    match value {
        "follow" => Ok("follow".into()),
        "dm" => Ok("dm".into()),
        "follow_then_dm" => Ok("follow_then_dm".into()),
        "reply" => Ok("reply".into()),
        _ => Err(bad_request("unsupported action_type")),
    }
}

fn default_outreach_name(platform: &str, action_type: &str) -> &'static str {
    match (platform, action_type) {
        ("xiaohongshu", "follow") => "小红书精准线索关注",
        ("douyin", "dm") => "抖音精准线索私信",
        ("douyin", "follow_then_dm") => "抖音精准线索关注私信",
        ("douyin", "follow") => "抖音精准线索关注",
        _ => "精准线索触达",
    }
}
