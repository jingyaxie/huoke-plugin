use std::sync::Arc;
use std::time::Duration;

use rand::Rng;
use serde_json::json;
use tracing::{error, info, warn};

use crate::db::{Database, OutreachTaskStatus};
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

            let command_payload = json!({
                "video_url": item.video_url,
                "aweme_id": item.aweme_id,
                "comment_id": item.comment_id,
                "comment_text": item.comment_text,
                "reply_text": item.reply_text,
                "scroll_rounds": 12,
            });

            let result = self
                .hub
                .request_command("douyin.comment.reply", command_payload, Duration::from_secs(45))
                .await;

            match result {
                Ok(data) => {
                    let ok = data.get("ok").and_then(|v| v.as_bool()).unwrap_or(false);
                    if ok {
                        let _ = self.db.consume_reply_quota(current.daily_quota)?;
                        let result_json = serde_json::to_string(&data).unwrap_or_else(|_| "{}".into());
                        self.db.mark_outreach_item_completed(&item.id, &result_json)?;
                        info!("outreach item {} completed", item.id);
                    } else {
                        let err = data
                            .get("error")
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
}

fn jitter_delay(base_ms: i64) -> u64 {
    let base = base_ms.clamp(1000, 30000) as u64;
    let mut rng = rand::thread_rng();
    let jitter = rng.gen_range(0..=(base / 2));
    base + jitter
}
