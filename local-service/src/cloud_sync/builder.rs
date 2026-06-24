use std::collections::HashMap;

use chrono::{TimeZone, Utc};
use serde_json::{json, Value};

use crate::db::{CapturedComment, CollectJob, Database, InteractionRecord, JobStatus};

pub const SYNC_SCHEMA: &str = "huoke.agent_job_sync.v1";

pub fn build_payload(db: &Database, job: &CollectJob, cloud_task_id: &str) -> Result<Value, String> {
    let comments = db.list_comments_for_job(&job.id, None, 500)?;
    let videos = db.list_videos_for_job(&job.id)?;
    let video_map: HashMap<String, (String, String)> = videos
        .into_iter()
        .map(|video| (video.aweme_id.clone(), (video.title, video.video_url)))
        .collect();
    let mut keyword = job.keyword.trim().to_string();
    if keyword.is_empty() {
        keyword = job
            .config
            .as_ref()
            .and_then(|cfg| cfg.get("keyword"))
            .and_then(|value| value.as_str())
            .unwrap_or("")
            .trim()
            .to_string();
    }
    let leads: Vec<Value> = comments
        .iter()
        .map(|comment| comment_to_lead(comment, video_map.get(&comment.aweme_id), &keyword))
        .collect();
    let interactions = db.list_interactions_for_job(&job.id, 200)?;
    let outreach_events: Vec<Value> = interactions
        .iter()
        .map(interaction_to_outreach_event)
        .collect();
    let precise_count = comments.iter().filter(|row| row.is_precise).count() as i64;
    let target_leads = job
        .config
        .as_ref()
        .and_then(|cfg| cfg.get("target_count"))
        .and_then(|value| value.as_i64())
        .unwrap_or(job.limit_videos);
    let emitted_at = Utc
        .timestamp_millis_opt(job.updated_at)
        .single()
        .map(|dt| dt.to_rfc3339())
        .unwrap_or_else(|| Utc::now().to_rfc3339());

    Ok(json!({
        "schema": SYNC_SCHEMA,
        "event": "job.delta",
        "emitted_at": emitted_at,
        "correlation": {
            "external_system": "huoke_desktop",
            "external_task_id": cloud_task_id,
        },
        "job": {
            "job_id": job.id,
            "platform": job.platform,
            "status": map_job_status(&job.status),
            "task_type": map_task_type(job),
            "name": job.name,
            "message": job.name,
            "updated_at": emitted_at,
        },
        "progress": {
            "target_leads": target_leads,
            "leads_collected": comments.len() as i64,
            "leads_qualified": precise_count,
            "comments_captured": comments.len() as i64,
            "comments_evaluated": comments.iter().filter(|row| row.evaluated_at.is_some()).count() as i64,
        },
        "stats": {
            "leads_total": comments.len() as i64,
            "outreach_total": outreach_events.len() as i64,
        },
        "leads": leads,
        "outreach_events": outreach_events,
    }))
}

fn map_job_status(status: &JobStatus) -> &'static str {
    match status {
        JobStatus::Pending => "queued",
        JobStatus::Running => "running",
        JobStatus::Paused => "pending",
        JobStatus::Completed => "completed",
        JobStatus::Failed => "failed",
    }
}

fn map_task_type(job: &CollectJob) -> &'static str {
    if job.job_type == "manual" {
        let intent = job
            .config
            .as_ref()
            .and_then(|cfg| cfg.get("intent"))
            .and_then(|value| value.as_str())
            .unwrap_or("account_home");
        if intent == "single_video" {
            return "video_manual";
        }
        return "home_manual";
    }
    "home_auto"
}

fn ms_to_iso(value: Option<i64>) -> Option<String> {
    value.and_then(|ms| {
        Utc.timestamp_millis_opt(ms)
            .single()
            .map(|dt| dt.to_rfc3339())
    })
}

fn sanitize_comment_id(raw: &str) -> String {
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        return String::new();
    }
    if trimmed.len() <= 64 {
        return trimmed.to_string();
    }
    trimmed.chars().take(64).collect()
}

fn comment_to_lead(
    comment: &CapturedComment,
    video: Option<&(String, String)>,
    keyword: &str,
) -> Value {
    let (mut video_title, video_url) = video
        .map(|(title, url)| (title.clone(), url.clone()))
        .unwrap_or_default();
    if video_title.trim().is_empty() && !keyword.trim().is_empty() {
        video_title = keyword.trim().to_string();
    }
    let evaluation = if comment.evaluated_at.is_some() {
        json!({
            "is_lead": comment.is_precise,
            "score": comment.evaluation_score,
            "reason": comment.evaluation_reason,
        })
    } else {
        Value::Null
    };
    json!({
        "comment_id": sanitize_comment_id(&comment.comment_id),
        "comment_text": comment.content,
        "nickname": comment.username,
        "target_user_id": comment.user_id,
        "sec_uid": comment.sec_uid,
        "avatar_url": comment.avatar_url,
        "content_id": comment.aweme_id,
        "video_url": video_url,
        "content_title": video_title,
        "keyword": keyword,
        "created_at": ms_to_iso(comment.create_time.or(Some(comment.created_at))),
        "evaluation": evaluation,
    })
}

fn interaction_to_outreach_event(record: &InteractionRecord) -> Value {
    json!({
        "id": record.id,
        "action": record.action,
        "comment_id": record.comment_id,
        "target_user_id": record.user_id,
        "status": "ok",
        "created_at": ms_to_iso(Some(record.created_at)),
    })
}
