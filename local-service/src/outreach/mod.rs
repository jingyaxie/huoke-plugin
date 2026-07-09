use std::sync::Arc;
use std::time::Duration;

use rand::Rng;
use tracing::{error, info, warn};

use crate::lab_commands::LabCommands;

use crate::api::outreach::candidates_to_drafts;
use crate::db::{Database, OutreachItem, OutreachTask, OutreachTaskStatus};
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
        if task.platform == "xiaohongshu" {
            let msg = "小红书 PC 网页版暂不支持自动关注或私信触达";
            self.db
                .update_outreach_task_status(task_id, OutreachTaskStatus::Paused, Some(msg))?;
            return Err(msg.into());
        }
        self.db
            .update_outreach_task_status(task_id, OutreachTaskStatus::Running, None)?;
        info!("starting outreach task {task_id} name={}", task.name);

        let mut consecutive_failures = 0_i64;
        loop {
            let current = self.db.get_outreach_task(task_id)?;
            if current.status == OutreachTaskStatus::Paused {
                info!("outreach task {task_id} paused");
                return Ok(());
            }

            let quota = self.db.get_quota_status(current.daily_quota)?;
            let action_count = action_count_for_task(&current.action_type);
            if quota.remaining < action_count {
                let msg = format!(
                    "daily quota reached ({}/{})",
                    quota.reply_count, quota.daily_limit
                );
                if current.recurring {
                    self.db.update_outreach_task_status(
                        task_id,
                        OutreachTaskStatus::Running,
                        Some(&msg),
                    )?;
                    self.sleep_idle(&current, &msg).await;
                    continue;
                }
                self.db.update_outreach_task_status(
                    task_id,
                    OutreachTaskStatus::Paused,
                    Some(&msg),
                )?;
                return Err(msg);
            }

            let Some(item) = self.db.next_pending_outreach_item(task_id)? else {
                if current.recurring {
                    let inserted = self.refill_task_items(&current)?;
                    if inserted > 0 {
                        info!("outreach task {task_id}: refilled {inserted} new item(s)");
                        continue;
                    }
                    let msg = "no new outreach candidates; sleeping";
                    self.db.update_outreach_task_status(
                        task_id,
                        OutreachTaskStatus::Running,
                        Some(msg),
                    )?;
                    self.sleep_idle(&current, msg).await;
                    continue;
                }
                self.db.update_outreach_task_status(
                    task_id,
                    OutreachTaskStatus::Completed,
                    None,
                )?;
                info!("outreach task {task_id} completed");
                return Ok(());
            };

            self.db.mark_outreach_item_running(&item.id)?;

            let result = self.execute_item(&current, &item).await;

            match result {
                Ok(data) => {
                    let ok = data.get("ok").and_then(|v| v.as_bool()).unwrap_or(false);
                    if ok {
                        consecutive_failures = 0;
                        for _ in 0..action_count {
                            let _ = self.db.consume_reply_quota(current.daily_quota)?;
                        }
                        let result_json =
                            serde_json::to_string(&data).unwrap_or_else(|_| "{}".into());
                        self.db
                            .mark_outreach_item_completed(&item.id, &result_json)?;
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
                        consecutive_failures += 1;
                    }
                }
                Err(err) => {
                    let retryable = err.contains("timeout") || err.contains("navigating");
                    self.db
                        .mark_outreach_item_failed(&item.id, &err, retryable)?;
                    warn!("outreach item {} command error: {err}", item.id);
                    consecutive_failures += 1;
                }
            }

            if consecutive_failures >= 2 {
                let msg = "连续触达失败，任务已暂停，请检查平台页面状态后再继续";
                self.db
                    .update_outreach_task_status(task_id, OutreachTaskStatus::Paused, Some(msg))?;
                return Err(msg.into());
            }

            let delay_ms = jitter_delay(current.interval_ms);
            tokio::time::sleep(Duration::from_millis(delay_ms)).await;
        }
    }

    fn refill_task_items(&self, task: &OutreachTask) -> Result<usize, String> {
        let candidates = self.db.list_outreach_candidates(
            Some(&task.platform),
            task.source_job_id.as_deref(),
            task.refill_batch_size.clamp(1, 500),
            task.include_contacted,
        )?;
        let drafts = candidates_to_drafts(
            candidates,
            &task.action_type,
            &task.reply_text,
            &task.dm_text,
            task.min_digg_count,
            task.refill_batch_size,
        );
        self.db.add_outreach_items(&task.id, &drafts)
    }

    async fn sleep_idle(&self, task: &OutreachTask, reason: &str) {
        let sleep_ms = task.idle_sleep_ms.clamp(60_000, 86_400_000) as u64;
        info!(
            "outreach task {} idle: {reason}; sleep {}s",
            task.id,
            sleep_ms / 1000
        );
        tokio::time::sleep(Duration::from_millis(sleep_ms)).await;
    }

    async fn execute_item(
        &self,
        task: &OutreachTask,
        item: &OutreachItem,
    ) -> Result<serde_json::Value, String> {
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
                if !followed
                    .get("ok")
                    .and_then(|v| v.as_bool())
                    .unwrap_or(false)
                {
                    return Ok(followed);
                }
                let delay_ms = jitter_delay(task.interval_ms);
                tokio::time::sleep(Duration::from_millis(delay_ms)).await;
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
            self.db
                .record_interaction(job_id, "follow", &item.comment_id, &item.user_id)?;
        }
        if item.action_type == "dm" || item.action_type == "follow_then_dm" {
            self.db
                .record_interaction(job_id, "dm", &item.comment_id, &item.user_id)?;
        }
        if item.action_type == "reply" {
            self.db
                .record_interaction(job_id, "reply", &item.comment_id, &item.user_id)?;
        }
        Ok(())
    }
}

fn jitter_delay(base_ms: i64) -> u64 {
    let base = base_ms.clamp(5_000, 300_000) as u64;
    let mut rng = rand::thread_rng();
    let jitter = rng.gen_range(0..=(base / 2));
    base + jitter
}

fn action_count_for_task(action_type: &str) -> i64 {
    match action_type {
        "follow_then_dm" => 2,
        _ => 1,
    }
}
