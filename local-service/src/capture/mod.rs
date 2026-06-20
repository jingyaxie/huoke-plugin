use std::sync::Arc;
use std::time::Duration;

use serde_json::json;
use tokio::sync::broadcast;
use tracing::{error, info, warn};

use crate::db::{Database, JobStatus};
use crate::douyin::parser::{extract_aweme_id_from_url, is_comment_api, is_profile_post_api, is_search_api, parse_comment_list, parse_search_videos};
use crate::protocol::{BridgeMessage, MessageType};
use crate::ws::BridgeHub;

#[derive(Clone)]
pub struct CaptureService {
    db: Database,
    hub: BridgeHub,
}

impl CaptureService {
    pub fn new(db: Database, hub: BridgeHub) -> Self {
        Self { db, hub }
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
        tokio::spawn(async move {
            if let Err(err) = self.run_job(&job_id).await {
                error!("job {job_id} failed: {err}");
                let _ = self
                    .db
                    .update_job_status(&job_id, JobStatus::Failed, Some(&err));
            }
        });
    }

    async fn run_job(&self, job_id: &str) -> Result<(), String> {
        if self.hub.client_count() == 0 {
            return Err("no extension connected".into());
        }

        let job = self.db.get_job(job_id)?;
        self.db
            .update_job_status(job_id, JobStatus::Running, None)?;

        if job.job_type == "manual" {
            return self.run_manual_job(job_id, &job).await;
        }

        self.run_keyword_job(job_id, &job).await
    }

    async fn run_keyword_job(&self, job_id: &str, job: &crate::db::CollectJob) -> Result<(), String> {
        info!(
            "starting douyin keyword collect job {} keyword={}",
            job_id, job.keyword
        );

        self.hub
            .request_command(
                "douyin.search.navigate",
                json!({ "keyword": job.keyword }),
                Duration::from_secs(30),
            )
            .await?;

        tokio::time::sleep(Duration::from_secs(5)).await;
        self.enable_network_hook().await?;
        tokio::time::sleep(Duration::from_secs(8)).await;

        let mut videos = self.db.list_videos_for_job(job_id)?;
        if videos.len() > job.limit_videos as usize {
            videos.truncate(job.limit_videos as usize);
        }

        if videos.is_empty() {
            return Err("search produced no videos — ensure Douyin tab is active and logged in".into());
        }

        self.collect_videos(job_id, &videos).await?;
        self.db
            .update_job_status(job_id, JobStatus::Completed, None)?;
        info!("job {job_id} completed");
        Ok(())
    }

    async fn run_manual_job(&self, job_id: &str, job: &crate::db::CollectJob) -> Result<(), String> {
        let input_url = job
            .input_url
            .as_deref()
            .or_else(|| {
                job.config
                    .as_ref()
                    .and_then(|c| c.get("input_url"))
                    .and_then(|v| v.as_str())
            })
            .unwrap_or("")
            .trim()
            .to_string();
        if input_url.is_empty() {
            return Err("manual job missing input_url".into());
        }

        let intent = job
            .config
            .as_ref()
            .and_then(|c| c.get("intent"))
            .and_then(|v| v.as_str())
            .unwrap_or("single_video");

        info!(
            "starting douyin manual collect job {} intent={} url={}",
            job_id, intent, input_url
        );

        self.hub
            .request_command(
                "douyin.url.navigate",
                json!({ "url": input_url }),
                Duration::from_secs(30),
            )
            .await?;

        tokio::time::sleep(Duration::from_secs(5)).await;
        self.enable_network_hook().await?;

        if intent == "account_home" {
            let _ = self
                .hub
                .request_command(
                    "douyin.profile.scroll",
                    json!({ "rounds": 4 }),
                    Duration::from_secs(25),
                )
                .await;
            tokio::time::sleep(Duration::from_secs(6)).await;

            let mut videos = self.db.list_videos_for_job(job_id)?;
            if videos.len() > job.limit_videos as usize {
                videos.truncate(job.limit_videos as usize);
            }
            if videos.is_empty() {
                return Err("profile produced no videos — ensure profile page is loaded".into());
            }
            self.collect_videos(job_id, &videos).await?;
        } else {
            tokio::time::sleep(Duration::from_secs(4)).await;
            let _ = self
                .hub
                .request_command(
                    "douyin.comments.scroll",
                    json!({ "rounds": 6 }),
                    Duration::from_secs(25),
                )
                .await;
            tokio::time::sleep(Duration::from_secs(3)).await;
        }

        self.db
            .update_job_status(job_id, JobStatus::Completed, None)?;
        info!("manual job {job_id} completed");
        Ok(())
    }

    async fn enable_network_hook(&self) -> Result<(), String> {
        self.hub
            .request_command(
                "network.hook.enable",
                json!({ "patterns": ["/aweme/", "/comment/", "/search/"] }),
                Duration::from_secs(10),
            )
            .await?;
        Ok(())
    }

    async fn collect_videos(
        &self,
        job_id: &str,
        videos: &[crate::db::CapturedVideo],
    ) -> Result<(), String> {
        for (index, video) in videos.iter().enumerate() {
            info!(
                "job {job_id}: open video {}/{} aweme_id={}",
                index + 1,
                videos.len(),
                video.aweme_id
            );

            self.hub
                .request_command(
                    "douyin.video.navigate",
                    json!({ "aweme_id": video.aweme_id }),
                    Duration::from_secs(30),
                )
                .await?;

            tokio::time::sleep(Duration::from_secs(5)).await;

            let _ = self
                .hub
                .request_command(
                    "douyin.comments.scroll",
                    json!({ "rounds": 4 }),
                    Duration::from_secs(20),
                )
                .await;

            tokio::time::sleep(Duration::from_secs(4)).await;
        }
        Ok(())
    }
}
