use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    Json,
};
use serde::{Deserialize, Serialize};
use serde_json::json;

use crate::db::{CollectJob, JobStatus};
use crate::job_config::{build_config_json, InteractionSettings, JobConfig, PresetRef};
use crate::state::AppState;

#[derive(Deserialize)]
pub struct PresetInput {
    pub id: String,
    #[serde(default)]
    pub content: String,
}

#[derive(Deserialize)]
pub struct CreateJobRequest {
    #[serde(default)]
    pub keyword: String,
    #[serde(default)]
    pub name: Option<String>,
    #[serde(default = "default_job_type")]
    pub job_type: String,
    #[serde(default)]
    pub intent: Option<String>,
    #[serde(default)]
    pub input_url: Option<String>,
    #[serde(default = "default_platform")]
    pub platform: String,
    #[serde(default = "default_limit_videos")]
    pub limit_videos: i64,
    #[serde(default = "default_max_comments")]
    pub max_comments_per_video: i64,
    #[serde(default)]
    pub target_count: Option<i64>,
    #[serde(default)]
    pub region_code: Option<String>,
    #[serde(default)]
    pub region_name: Option<String>,
    #[serde(default)]
    pub publish_time_range: Option<String>,
    #[serde(default)]
    pub comment_days: Option<i64>,
    #[serde(default)]
    pub interaction: Option<serde_json::Value>,
    #[serde(default)]
    pub comment_preset_ids: Option<Vec<String>>,
    #[serde(default)]
    pub dm_preset_ids: Option<Vec<String>>,
    #[serde(default)]
    pub comment_presets: Option<Vec<PresetInput>>,
    #[serde(default)]
    pub dm_presets: Option<Vec<PresetInput>>,
    #[serde(default)]
    pub auto_start: Option<bool>,
    #[serde(default = "default_auto_outreach")]
    pub auto_outreach: bool,
    #[serde(default)]
    pub evaluation: Option<serde_json::Value>,
}

fn default_auto_outreach() -> bool {
    true
}

fn default_job_type() -> String {
    "keyword".to_string()
}

fn default_platform() -> String {
    "douyin".to_string()
}

fn default_limit_videos() -> i64 {
    5
}

fn default_max_comments() -> i64 {
    50
}

#[derive(Serialize)]
pub struct CreateJobResponse {
    pub job: CollectJob,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub started: Option<bool>,
}

#[derive(Deserialize)]
pub struct ListCommentsQuery {
    pub aweme_id: Option<String>,
    #[serde(default = "default_comment_limit")]
    pub limit: i64,
}

fn default_comment_limit() -> i64 {
    200
}

fn resolve_presets(
    explicit: Option<Vec<PresetInput>>,
    ids: Option<Vec<String>>,
) -> Vec<PresetRef> {
    if let Some(rows) = explicit {
        return rows
            .into_iter()
            .map(|row| PresetRef {
                id: row.id,
                content: row.content,
            })
            .collect();
    }
    ids.unwrap_or_default()
        .into_iter()
        .map(|id| PresetRef {
            id,
            content: String::new(),
        })
        .collect()
}

pub async fn get_interaction_stats(
    State(state): State<AppState>,
) -> Result<Json<serde_json::Value>, ApiError> {
    let reply = state.db.get_quota_status(state.default_daily_quota).map_err(internal_error)?;
    let dm_used = state.db.count_interactions_today("dm").unwrap_or(0);
    let follow_used = state.db.count_interactions_today("follow").unwrap_or(0);
    Ok(Json(json!({
        "reply": reply,
        "dm_used_today": dm_used,
        "follow_used_today": follow_used,
    })))
}

pub async fn create_job(
    State(state): State<AppState>,
    Json(body): Json<CreateJobRequest>,
) -> Result<Json<CreateJobResponse>, (StatusCode, Json<serde_json::Value>)> {
    let keyword = body.keyword.trim();
    let job_type = body.job_type.trim();
    let input_url = body.input_url.as_deref().map(str::trim).filter(|s| !s.is_empty());
    let intent = body.intent.as_deref().unwrap_or("account_home");

    if job_type == "manual" {
        if input_url.is_none() {
            return Err((
                StatusCode::BAD_REQUEST,
                Json(json!({ "error": "input_url is required for manual jobs" })),
            ));
        }
    } else if keyword.is_empty() {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({ "error": "keyword is required" })),
        ));
    }

    let platform = body.platform.trim();
    if let Err(message) = crate::platforms::assert_collect_supported(platform) {
        return Err((StatusCode::BAD_REQUEST, Json(json!({ "error": message }))));
    }

    let limit_videos = if job_type == "manual" && intent == "single_video" {
        1
    } else {
        body.limit_videos.clamp(1, 20)
    };
    let max_comments_per_video = body.max_comments_per_video.clamp(1, 500);
    let comment_presets = resolve_presets(body.comment_presets, body.comment_preset_ids);
    let dm_presets = resolve_presets(body.dm_presets, body.dm_preset_ids);
    let interaction = body
        .interaction
        .unwrap_or_else(|| serde_json::to_value(InteractionSettings::default()).unwrap_or(json!({})));

    let base_config = json!({
        "job_type": job_type,
        "intent": if job_type == "manual" { intent } else { "keyword_auto" },
        "input_url": input_url,
        "target_count": body.target_count.unwrap_or(max_comments_per_video * limit_videos),
        "region_code": body.region_code,
        "region_name": body.region_name,
        "publish_time_range": body.publish_time_range.unwrap_or_else(|| "unlimited".to_string()),
        "comment_days": body.comment_days.unwrap_or(3),
        "interaction": interaction,
        "auto_start": body.auto_start.unwrap_or(false),
        "auto_outreach": body.auto_outreach,
    });
    let mut obj = base_config
        .as_object()
        .cloned()
        .unwrap_or_default();
    if let Some(eval) = body.evaluation {
        if !eval.is_null() {
            obj.insert("evaluation".into(), eval);
        }
    }
    let base_config = serde_json::Value::Object(obj);
    let config_json = build_config_json(&base_config, &comment_presets, &dm_presets);

    let stored_keyword = if job_type == "manual" {
        input_url.unwrap_or("").to_string()
    } else {
        keyword.to_string()
    };

    let job = state
        .db
        .create_job(
            platform,
            &stored_keyword,
            body.name.as_deref().unwrap_or(""),
            job_type,
            input_url,
            limit_videos,
            max_comments_per_video,
            Some(&config_json),
        )
        .map_err(internal_error)?;

    let mut started = None;
    if body.auto_start.unwrap_or(false) {
        let _ = state.db.supersede_other_running_jobs(&job.id);
        let generation = state.job_runs.begin(&job.id);
        state
            .db
            .update_job_status(&job.id, JobStatus::Running, None)
            .map_err(internal_error)?;
        state.capture.clone().spawn_job(job.id.clone(), generation);
        started = Some(true);
    }

    Ok(Json(CreateJobResponse { job, started }))
}

pub async fn list_jobs(State(state): State<AppState>) -> Result<Json<Vec<CollectJob>>, ApiError> {
    let jobs = state.db.list_jobs(50).map_err(internal_error)?;
    Ok(Json(jobs))
}

pub async fn get_job(
    State(state): State<AppState>,
    Path(job_id): Path<String>,
) -> Result<Json<CollectJob>, ApiError> {
    let job = state.db.get_job(&job_id).map_err(|_| not_found())?;
    Ok(Json(job))
}

pub async fn list_job_videos(
    State(state): State<AppState>,
    Path(job_id): Path<String>,
) -> Result<Json<serde_json::Value>, ApiError> {
    let _ = state.db.get_job(&job_id).map_err(|_| not_found())?;
    let videos = state
        .db
        .list_videos_for_job(&job_id)
        .map_err(internal_error)?;
    Ok(Json(json!({ "job_id": job_id, "videos": videos })))
}

pub async fn list_job_comments(
    State(state): State<AppState>,
    Path(job_id): Path<String>,
    Query(query): Query<ListCommentsQuery>,
) -> Result<Json<serde_json::Value>, ApiError> {
    let _ = state.db.get_job(&job_id).map_err(|_| not_found())?;
    let comments = state
        .db
        .list_comments_for_job(&job_id, query.aweme_id.as_deref(), query.limit.clamp(1, 2000))
        .map_err(internal_error)?;
    Ok(Json(json!({ "job_id": job_id, "comments": comments })))
}

pub async fn list_job_interactions(
    State(state): State<AppState>,
    Path(job_id): Path<String>,
    Query(query): Query<ListCommentsQuery>,
) -> Result<Json<serde_json::Value>, ApiError> {
    let _ = state.db.get_job(&job_id).map_err(|_| not_found())?;
    let interactions = state
        .db
        .list_interactions_for_job(&job_id, query.limit.clamp(1, 5000))
        .map_err(internal_error)?;
    Ok(Json(json!({ "job_id": job_id, "interactions": interactions })))
}

pub async fn evaluate_job(
    State(state): State<AppState>,
    Path(job_id): Path<String>,
) -> Result<Json<serde_json::Value>, ApiError> {
    let job = state.db.get_job(&job_id).map_err(|_| not_found())?;
    let cfg = JobConfig::from_job(&job);
    let stats = crate::evaluation::evaluate_job_comments(
        &state.db,
        &state.data_dir,
        &job_id,
        &job.keyword,
        &cfg.evaluation,
    )
    .await
    .map_err(internal_error)?;
    let precise_count = state
        .db
        .count_precise_comments_for_job(&job_id)
        .map_err(internal_error)?;
    Ok(Json(json!({
        "job_id": job_id,
        "evaluated": stats.evaluated,
        "precise": stats.precise,
        "precise_count": precise_count,
    })))
}

pub async fn start_job(
    State(state): State<AppState>,
    Path(job_id): Path<String>,
) -> Result<Json<serde_json::Value>, ApiError> {
    let job = state.db.get_job(&job_id).map_err(|_| not_found())?;
    if job.status == JobStatus::Completed {
        let cfg = JobConfig::from_job(&job);
        let uses_precise = crate::llm_client::LlmClient::from_data_dir(&state.data_dir).is_some();
        let progress = if uses_precise {
            state
                .db
                .count_precise_comments_for_job(&job_id)
                .map_err(internal_error)?
        } else {
            state
                .db
                .count_comments_for_job(&job_id)
                .map_err(internal_error)?
        };
        if progress >= cfg.target_count {
            return Ok(Json(json!({ "job_id": job_id, "status": "completed", "message": "already completed" })));
        }
    }

    if job.status == JobStatus::Running {
        state.job_runs.invalidate(&job_id);
    }

    state
        .db
        .supersede_other_running_jobs(&job_id)
        .map_err(internal_error)?;

    let generation = state.job_runs.begin(&job_id);
    state
        .db
        .update_job_status(&job_id, JobStatus::Running, None)
        .map_err(internal_error)?;

    state.capture.clone().spawn_job(job_id.clone(), generation);
    Ok(Json(json!({
        "job_id": job_id,
        "status": "running",
        "message": "collect job started — keep Douyin tab active in Chrome"
    })))
}

pub async fn pause_job(
    State(state): State<AppState>,
    Path(job_id): Path<String>,
) -> Result<Json<serde_json::Value>, ApiError> {
    let job = state.db.get_job(&job_id).map_err(|_| not_found())?;
    if job.status != JobStatus::Running && job.status != JobStatus::Pending {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({ "error": format!("任务当前为 {}，仅运行中或待执行的任务可暂停", job.status.as_str()) })),
        ));
    }
    state.job_runs.invalidate(&job_id);
    state
        .db
        .update_job_status(&job_id, JobStatus::Paused, None)
        .map_err(internal_error)?;
    Ok(Json(json!({ "job_id": job_id, "status": "paused" })))
}

pub async fn delete_job(
    State(state): State<AppState>,
    Path(job_id): Path<String>,
) -> Result<Json<serde_json::Value>, ApiError> {
    match state.db.delete_collect_job(&job_id) {
        Ok(true) => Ok(Json(json!({ "ok": true, "job_id": job_id, "deleted": true }))),
        Ok(false) => Err(not_found()),
        Err(err) if err == "job not found" => Err(not_found()),
        Err(err) if err.contains("cannot delete running") => Err((
            StatusCode::CONFLICT,
            Json(json!({ "error": "运行中的任务无法删除，请等待结束或重启服务后重试" })),
        )),
        Err(err) => Err(internal_error(err)),
    }
}

type ApiError = (StatusCode, Json<serde_json::Value>);

fn internal_error(err: String) -> ApiError {
    (
        StatusCode::INTERNAL_SERVER_ERROR,
        Json(json!({ "error": err })),
    )
}

fn not_found() -> ApiError {
    (StatusCode::NOT_FOUND, Json(json!({ "error": "job not found" })))
}
