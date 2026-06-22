use std::time::Duration;

use rand::Rng;
use crate::simulate;
use tokio::time::sleep;
use tracing::{info, warn};

use crate::db::{CapturedComment, Database, JobStatus};
use crate::job_config::JobConfig;
use crate::lab_commands::LabCommands;
use crate::ws::BridgeHub;

pub struct InlineOutreachRunner<'a> {
    pub db: &'a Database,
    pub hub: &'a BridgeHub,
    pub default_daily_quota: i64,
}

impl<'a> InlineOutreachRunner<'a> {
    pub async fn run(&self, job_id: &str, cfg: &JobConfig) -> Result<OutreachStats, String> {
        let precise_only = self.db.job_has_evaluated_comments(job_id)?;
        let eligible = self.db.list_eligible_comments_for_outreach(
            job_id,
            cfg.comment_days,
            0,
            cfg.target_count.max(10) * 3,
            precise_only,
        )?;
        if eligible.is_empty() {
            return Ok(OutreachStats::default());
        }

        let reply_templates = cfg.reply_templates();
        let dm_templates = cfg.dm_templates();
        let pct = cfg.interaction.comment_dm_percentage.clamp(0, 100);
        let total_budget = eligible.len() as i64;
        let mut reply_budget = if reply_templates.is_empty() {
            0
        } else {
            ((total_budget as f64) * pct as f64 / 100.0).ceil() as i64
        };
        let mut dm_budget = if dm_templates.is_empty() {
            0
        } else {
            total_budget - reply_budget
        };
        if reply_templates.is_empty() && !dm_templates.is_empty() {
            dm_budget = total_budget;
        }
        if !reply_templates.is_empty() && dm_templates.is_empty() {
            reply_budget = total_budget.min(
                self.default_daily_quota
                    .max(cfg.interaction.follow_per_day)
                    .clamp(1, 500),
            );
        }

        let follow_budget = if cfg.interaction.follow_per_day > 0 {
            cfg.interaction.follow_per_day
        } else {
            0
        };

        info!(
            "job {job_id}: outreach budgets reply={reply_budget} dm={dm_budget} follow={follow_budget} eligible={}",
            eligible.len()
        );

        let (interval_min, interval_max) = cfg.interaction.interval_ms_range();
        let mut stats = OutreachStats::default();
        let mut reply_idx = 0_usize;
        let mut dm_idx = 0_usize;
        let mut cursor = 0_usize;

        while cursor < eligible.len()
            && (stats.replies < reply_budget || stats.dms < dm_budget || stats.follows < follow_budget)
        {
            if self.db.get_job(job_id)?.status == JobStatus::Paused {
                info!("job {job_id}: outreach paused");
                return Ok(stats);
            }
            let comment = &eligible[cursor];
            cursor += 1;

            if stats.replies < reply_budget && !reply_templates.is_empty() {
                if self.reply_quota_remaining(cfg)? <= 0 {
                    reply_budget = stats.replies;
                } else {
                    let text = reply_templates[reply_idx % reply_templates.len()].clone();
                    reply_idx += 1;
                    if self
                        .send_reply(job_id, comment, &text)
                        .await
                        .unwrap_or(false)
                    {
                        stats.replies += 1;
                        self.sleep_interval(interval_min, interval_max).await;
                        continue;
                    }
                }
            }

            if stats.dms < dm_budget && !dm_templates.is_empty() {
                if self.dm_quota_remaining(cfg)? <= 0 {
                    dm_budget = stats.dms;
                } else {
                    let text = dm_templates[dm_idx % dm_templates.len()].clone();
                    dm_idx += 1;
                    if self.send_dm(job_id, comment, &text).await.unwrap_or(false) {
                        stats.dms += 1;
                        self.sleep_interval(interval_min, interval_max).await;
                        continue;
                    }
                }
            }

            if stats.follows < follow_budget && self.follow_quota_remaining(cfg)? > 0 {
                if self.send_follow(job_id, comment).await.unwrap_or(false) {
                    stats.follows += 1;
                    self.sleep_interval(interval_min, interval_max).await;
                }
            }
        }

        info!(
            "job {job_id}: outreach done replies={} dms={} follows={}",
            stats.replies, stats.dms, stats.follows
        );
        Ok(stats)
    }

    fn reply_quota_remaining(&self, cfg: &JobConfig) -> Result<i64, String> {
        let limit = self
            .default_daily_quota
            .max(cfg.interaction.follow_per_day)
            .clamp(1, 500);
        Ok(self.db.get_quota_status(limit)?.remaining)
    }

    fn dm_quota_remaining(&self, cfg: &JobConfig) -> Result<i64, String> {
        let limit = cfg.interaction.dm_per_day.clamp(1, 500);
        let used = self.db.count_interactions_today("dm")?;
        Ok((limit - used).max(0))
    }

    fn follow_quota_remaining(&self, cfg: &JobConfig) -> Result<i64, String> {
        let limit = cfg.interaction.follow_per_day.clamp(0, 500);
        if limit <= 0 {
            return Ok(0);
        }
        let used = self.db.count_interactions_today("follow")?;
        Ok((limit - used).max(0))
    }

    async fn send_reply(&self, job_id: &str, comment: &CapturedComment, text: &str) -> Result<bool, String> {
        let job = self.db.get_job(job_id)?;
        let lab = LabCommands::new(self.hub, &job.platform);
        let data = lab
            .reply_to_comment(
                &comment.aweme_id,
                &comment.comment_id,
                &comment.content,
                text,
                12,
                false,
            )
            .await?;
        let ok = data.get("ok").and_then(|v| v.as_bool()).unwrap_or(false);
        if ok {
            let limit = self.default_daily_quota.clamp(1, 500);
            let _ = self.db.consume_reply_quota(limit)?;
            let _ = self.db.record_interaction(job_id, "reply", &comment.comment_id, &comment.user_id);
        } else {
            warn!("reply failed {:?} for {}", data.get("message"), comment.comment_id);
        }
        Ok(ok)
    }

    async fn send_dm(&self, job_id: &str, comment: &CapturedComment, text: &str) -> Result<bool, String> {
        let job = self.db.get_job(job_id)?;
        let lab = LabCommands::new(self.hub, &job.platform);

        let opened = lab
            .open_profile_from_comment(
                &comment.aweme_id,
                &comment.comment_id,
                &comment.content,
                12,
            )
            .await?;
        if !opened.get("ok").and_then(|v| v.as_bool()).unwrap_or(false) {
            warn!(
                "open profile failed for dm: {:?}",
                opened.get("message").or(opened.get("error"))
            );
            return Ok(false);
        }

        simulate::pause(Duration::from_secs(2)).await;

        let sent = lab.send_dm_on_profile(text).await?;
        let ok = sent.get("ok").and_then(|v| v.as_bool()).unwrap_or(false);
        if ok {
            let _ = self.db.record_interaction(job_id, "dm", &comment.comment_id, &comment.user_id);
        }
        Ok(ok)
    }

    async fn send_follow(&self, job_id: &str, comment: &CapturedComment) -> Result<bool, String> {
        let job = self.db.get_job(job_id)?;
        let lab = LabCommands::new(self.hub, &job.platform);
        let result = lab
            .follow_from_comment(
                &comment.aweme_id,
                &comment.comment_id,
                &comment.content,
                12,
            )
            .await?;
        let ok = result.get("ok").and_then(|v| v.as_bool()).unwrap_or(false);
        if ok {
            let _ = self.db.record_interaction(job_id, "follow", &comment.comment_id, &comment.user_id);
        }
        Ok(ok)
    }

    async fn sleep_interval(&self, min_ms: i64, max_ms: i64) {
        if simulate::enabled() {
            simulate::pause(Duration::from_millis(5)).await;
        } else {
            sleep(Duration::from_millis(jitter_ms(min_ms, max_ms))).await;
        }
    }
}

#[derive(Debug, Default, Clone)]
pub struct OutreachStats {
    pub replies: i64,
    pub dms: i64,
    pub follows: i64,
}

fn jitter_ms(min_ms: i64, max_ms: i64) -> u64 {
    let mut rng = rand::thread_rng();
    if max_ms <= min_ms {
        return min_ms.max(0) as u64;
    }
    rng.gen_range(min_ms..=max_ms) as u64
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn outreach_stats_default() {
        let stats = OutreachStats::default();
        assert_eq!(stats.replies, 0);
    }
}
