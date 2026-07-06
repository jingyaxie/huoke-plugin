use std::sync::Arc;
use std::time::Duration;

use rand::Rng;
use tracing::{error, info, warn};

use crate::lab_commands::LabCommands;

use crate::db::{Database, OutreachItem, OutreachTaskStatus};
use crate::ws::BridgeHub;

#[derive(Clone)]
pub struct OutreachService {
    db: Database,
    hub: BridgeHub,
    default_daily_quota: i64,
}

impl OutreachService {
    pub fn new(db: Database, hub: BridgeHub, default_daily_quota: i64) -> Self {
        Self {
            db,
            hub,
            default_daily_quota: default_daily_quota.clamp(1, 500),
        }
    }

    pub fn spawn_task(self: Arc<Self>, task_id: String) {
        tokio::spawn(async move {
            if let Err(err) = self.run_task(&task_id).await {
                error!("outreach task {task_id} failed: {err}");
                let _ = self.db.update_outreach_task_status(
                    &task_id,
                    OutreachTaskStatus::Failed,
                    Some(&err),
                );
            }
        });
    }

    async fn run_task(&self, task_id: &str) -> Result<(), String> {
        if self.hub.client_count() == 0 {
            return Err("no extension connected".into());
        }

        let task = self.db.get_outreach_task(task_id)?;
        self.db.update_outreach_task_status(task_id, OutreachTaskStatus::Running, None)?;
        info!("starting outreach task {task_id} name={}", task.name);

        loop {
            let current = self.db.get_outreach_task(task_id)?;
            if current.status == OutreachTaskStatus::Paused {
                info!("outreach task {task_id} paused");
                return Ok(());
            }

            let quota = self.db.get_quota_status(current.daily_quota)?;
            if quota.remaining <= 0 {
                let msg = format!("daily quota reached ({}/{})", quota.reply_count, quota.daily_limit);
                self.db
                    .update_outreach_task_status(task_id, OutreachTaskStatus::Paused, Some(&msg))?;
                return Err(msg);
            }

            let Some(item) = self.db.next_pending_outreach_item(task_id)? else {
                self.db
                    .update_outreach_task_status(task_id, OutreachTaskStatus::Completed, None)?;
                info!("outreach task {task_id} completed");
                return Ok(());
            };

            self.db.mark_outreach_item_running(&item.id)?;

            let result = self.execute_item(&item).await;

            match result {
                Ok(data) => {
                    let ok = data.get("ok").and_then(|v| v.as_bool()).unwrap_or(false);
                    if ok {
                        let _ = self.db.consume_reply_quota(current.daily_quota)?;
                        let result_json = serde_json::to_string(&data).unwrap_or_else(|_| "{}".into());
                        self.db.mark_outreach_item_completed(&item.id, &result_json)?;
                        self.record_item_interactions(&item)?;
                        info!("outreach item {} completed", item.id);
                    } else {
                        let err = data
                            .get("error")
                            .or_else(|| data.get("message"))
                            .and_then(|v| v.as_str())
                            .unwrap_or("reply failed");
                        let retryable = err == "navigating_to_video" || err.contains("not loaded");
                        self.db
                            .mark_outreach_item_failed(&item.id, err, retryable)?;
                        warn!("outreach item {} failed: {err}", item.id);
                    }
                }
                Err(err) => {
                    let retryable = err.contains("timeout") || err.contains("navigating");
                    self.db
                        .mark_outreach_item_failed(&item.id, &err, retryable)?;
                    warn!("outreach item {} command error: {err}", item.id);
                }
            }

            let delay_ms = jitter_delay(current.interval_ms);
            tokio::time::sleep(Duration::from_millis(delay_ms)).await;
        }
    }

    async fn execute_item(&self, item: &OutreachItem) -> Result<serde_json::Value, String> {
        let lab = LabCommands::new(&self.hub, &item.platform);
        match item.action_type.as_str() {
            "reply" => {
                lab.reply_to_comment(
                    &item.aweme_id,
                    &item.comment_id,
                    &item.comment_text,
                    &item.reply_text,
                    12,
                    false,
                )
                .await
            }
            "follow" => self.follow_profile(&lab, item).await,
            "dm" => self.dm_profile(&lab, item).await,
            "follow_then_dm" => {
                let followed = self.follow_profile(&lab, item).await?;
                if !followed.get("ok").and_then(|v| v.as_bool()).unwrap_or(false) {
                    return Ok(followed);
                }
                tokio::time::sleep(Duration::from_millis(1200)).await;
                self.dm_profile(&lab, item).await
            }
            other => Err(format!("unsupported outreach action_type: {other}")),
        }
    }

    async fn open_profile(&self, lab: &LabCommands<'_>, item: &OutreachItem) -> Result<(), String> {
        if !item.profile_url.trim().is_empty() {
            let data = lab.open_url(&item.profile_url).await?;
            if data.get("ok").and_then(|v| v.as_bool()).unwrap_or(true) {
                tokio::time::sleep(Duration::from_millis(1800)).await;
                return Ok(());
            }
        }
        let opened = lab
            .open_profile_from_comment(&item.aweme_id, &item.comment_id, &item.comment_text, 12)
            .await?;
        if opened.get("ok").and_then(|v| v.as_bool()).unwrap_or(false) {
            Ok(())
        } else {
            Err(opened
                .get("message")
                .or_else(|| opened.get("error"))
                .and_then(|v| v.as_str())
                .unwrap_or("failed to open profile")
                .to_string())
        }
    }

    async fn follow_profile(
        &self,
        lab: &LabCommands<'_>,
        item: &OutreachItem,
    ) -> Result<serde_json::Value, String> {
        self.open_profile(lab, item).await?;
        lab.click_follow_on_profile().await
    }

    async fn dm_profile(
        &self,
        lab: &LabCommands<'_>,
        item: &OutreachItem,
    ) -> Result<serde_json::Value, String> {
        self.open_profile(lab, item).await?;
        lab.send_dm_on_profile(&item.dm_text).await
    }

    fn record_item_interactions(&self, item: &OutreachItem) -> Result<(), String> {
        let Some(job_id) = item.source_job_id.as_deref().filter(|s| !s.is_empty()) else {
            return Ok(());
        };
        if item.action_type == "follow" || item.action_type == "follow_then_dm" {
            self.db.record_interaction(job_id, "follow", &item.comment_id, &item.user_id)?;
        }
        if item.action_type == "dm" || item.action_type == "follow_then_dm" {
            self.db.record_interaction(job_id, "dm", &item.comment_id, &item.user_id)?;
        }
        if item.action_type == "reply" {
            self.db.record_interaction(job_id, "reply", &item.comment_id, &item.user_id)?;
        }
        Ok(())
    }
}

fn jitter_delay(base_ms: i64) -> u64 {
    let base = base_ms.clamp(1000, 30000) as u64;
    let mut rng = rand::thread_rng();
    let jitter = rng.gen_range(0..=(base / 2));
    base + jitter
}
