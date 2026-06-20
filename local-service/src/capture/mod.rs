use std::sync::Arc;

use serde_json::json;
use tokio::sync::broadcast;
use tracing::{info, warn};

use crate::db::Database;
use crate::douyin::parser::{
    extract_aweme_id_from_url, is_comment_api, is_profile_post_api, is_search_api, parse_comment_list,
    parse_search_videos,
};
use crate::orchestration;
use crate::protocol::{BridgeMessage, MessageType};
use crate::ws::BridgeHub;

#[derive(Clone)]
pub struct CaptureService {
    db: Database,
    hub: BridgeHub,
    default_daily_quota: i64,
}

impl CaptureService {
    pub fn new(db: Database, hub: BridgeHub, default_daily_quota: i64) -> Self {
        Self {
            db,
            hub,
            default_daily_quota,
        }
    }

    pub fn spawn_event_listener(&self) {
        let this = self.clone();
        let mut rx = this.hub.subscribe_events();
        tokio::spawn(async move {
            loop {
                match rx.recv().await {
                    Ok(message) => {
                        if let Err(err) = this.handle_event(message).await {
                            warn!("capture event handler error: {err}");
                        }
                    }
                    Err(broadcast::error::RecvError::Lagged(skipped)) => {
                        warn!("capture listener lagged, skipped {skipped} events");
                    }
                    Err(broadcast::error::RecvError::Closed) => break,
                }
            }
        });
    }

    async fn handle_event(&self, message: BridgeMessage) -> Result<(), String> {
        if message.msg_type != MessageType::Event || message.action != "network.captured" {
            return Ok(());
        }

        let url = message
            .payload
            .get("url")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let body = message.payload.get("body").cloned().unwrap_or(json!({}));

        let running_jobs = self.db.list_running_job_ids()?;
        if running_jobs.is_empty() {
            return Ok(());
        }

        if is_search_api(url) || is_profile_post_api(url) {
            let videos = parse_search_videos(&body);
            if videos.is_empty() {
                return Ok(());
            }
            for job_id in &running_jobs {
                let inserted = self.db.upsert_videos(job_id, &videos)?;
                info!("job {job_id}: stored {inserted} search videos from {url}");
            }
            return Ok(());
        }

        if is_comment_api(url) {
            let fallback_aweme_id = extract_aweme_id_from_url(url);
            let (aweme_id, comments) = parse_comment_list(&body, fallback_aweme_id.as_deref());
            if comments.is_empty() {
                return Ok(());
            }
            let aweme_id = if aweme_id.is_empty() {
                fallback_aweme_id.unwrap_or_default()
            } else {
                aweme_id
            };
            if aweme_id.is_empty() {
                return Ok(());
            }
            for job_id in &running_jobs {
                let inserted = self.db.upsert_comments(job_id, &aweme_id, &comments)?;
                info!("job {job_id}: stored {inserted} comments for aweme {aweme_id}");
            }
        }

        Ok(())
    }

    pub fn spawn_job(self: Arc<Self>, job_id: String) {
        orchestration::spawn_job(
            self.db.clone(),
            self.hub.clone(),
            self.default_daily_quota,
            job_id,
        );
    }
}
