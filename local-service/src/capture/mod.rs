use std::sync::Arc;

use serde_json::json;
use tokio::sync::broadcast;
use tracing::{info, warn};

use crate::db::Database;
use crate::job_run::JobRunRegistry;
use crate::orchestration;
use crate::platforms::get_platform_adapter;
use crate::protocol::{BridgeMessage, MessageType};
use crate::ws::BridgeHub;

#[derive(Clone)]
pub struct CaptureService {
    db: Database,
    hub: BridgeHub,
    default_daily_quota: i64,
    job_runs: JobRunRegistry,
    data_dir: std::path::PathBuf,
}

impl CaptureService {
    pub fn new(
        db: Database,
        hub: BridgeHub,
        default_daily_quota: i64,
        job_runs: JobRunRegistry,
        data_dir: std::path::PathBuf,
    ) -> Self {
        Self {
            db,
            hub,
            default_daily_quota,
            job_runs,
            data_dir,
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

        for job_id in &running_jobs {
            let job = self.db.get_job(job_id)?;
            let adapter = get_platform_adapter(&job.platform);

            if adapter.is_search_api(url) || adapter.is_profile_post_api(url) {
                let videos = adapter.parse_search_videos(&body);
                if videos.is_empty() {
                    if adapter.is_profile_post_api(url) {
                        warn!(
                            "job {job_id} platform {} profile api captured but parsed 0 videos: {url}",
                            adapter.id()
                        );
                    } else {
                        tracing::debug!(
                            "job {job_id} platform {} search api captured but parsed 0 videos: {url}",
                            adapter.id()
                        );
                    }
                    continue;
                }
                let inserted = self.db.upsert_videos(job_id, &videos)?;
                let kind = if adapter.is_profile_post_api(url) {
                    "profile"
                } else {
                    "search"
                };
                info!(
                    "job {job_id}: stored {inserted} {kind} videos from {url} ({})",
                    adapter.id()
                );
                continue;
            }

            if adapter.is_comment_api(url) {
                let fallback_content_id = adapter.extract_content_id_from_url(url);
                let (content_id, comments) =
                    adapter.parse_comment_list(&body, fallback_content_id.as_deref());
                if comments.is_empty() {
                    continue;
                }
                let content_id = if content_id.is_empty() {
                    fallback_content_id.unwrap_or_default()
                } else {
                    content_id
                };
                if content_id.is_empty() {
                    continue;
                }
                let inserted = self.db.upsert_comments(job_id, &content_id, &comments)?;
                info!(
                    "job {job_id}: stored {inserted} comments for content {content_id} ({})",
                    adapter.id()
                );
                if inserted > 0 {
                    crate::evaluation::spawn_evaluate_job(
                        self.db.clone(),
                        self.data_dir.clone(),
                        job_id.clone(),
                    );
                }
            }
        }

        Ok(())
    }

    pub fn spawn_job(self: Arc<Self>, job_id: String, generation: u64, fresh_start: bool) {
        orchestration::spawn_job(
            self.db.clone(),
            self.hub.clone(),
            self.default_daily_quota,
            self.job_runs.clone(),
            self.data_dir.clone(),
            job_id,
            generation,
            fresh_start,
        );
    }
}
