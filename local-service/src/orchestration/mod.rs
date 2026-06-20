mod outreach;

use std::sync::Arc;
use std::time::Duration;

use tokio::time::sleep;
use tracing::{info, warn};

use crate::db::{CapturedVideo, Database, JobStatus};
use crate::filters;
use crate::job_config::JobConfig;
use crate::lab_commands::LabCommands;
use crate::orchestration::outreach::InlineOutreachRunner;
use crate::ws::BridgeHub;

pub struct JobOrchestrator {
    pub db: Database,
    pub hub: BridgeHub,
    pub default_daily_quota: i64,
}

impl JobOrchestrator {
    pub async fn run_job(&self, job_id: &str) -> Result<(), String> {
        if self.hub.client_count() == 0 {
            return Err("no extension connected".into());
        }

        let job = self.db.get_job(job_id)?;
        let cfg = JobConfig::from_job(&job);
        self.db
            .update_job_status(job_id, JobStatus::Running, None)?;

        let result = if job.job_type == "manual" {
            self.run_manual_job(job_id, &job, &cfg).await
        } else {
            self.run_keyword_job(job_id, &job, &cfg).await
        };

        match result {
            Ok(()) => {
                if cfg.should_run_auto_outreach() {
                    let runner = InlineOutreachRunner {
                        db: &self.db,
                        hub: &self.hub,
                        default_daily_quota: self.default_daily_quota,
                    };
                    if let Err(err) = runner.run(job_id, &cfg).await {
                        warn!("job {job_id} inline outreach partial failure: {err}");
                    }
                }
                self.db
                    .update_job_status(job_id, JobStatus::Completed, None)?;
                info!("job {job_id} completed");
                Ok(())
            }
            Err(err) => {
                self.db
                    .update_job_status(job_id, JobStatus::Failed, Some(&err))?;
                Err(err)
            }
        }
    }

    async fn run_keyword_job(
        &self,
        job_id: &str,
        job: &crate::db::CollectJob,
        cfg: &JobConfig,
    ) -> Result<(), String> {
        let search_kw = cfg.search_keyword(&job.keyword);
        info!(
            "keyword job {job_id}: search={search_kw} target={} videos={} comment_days={}",
            cfg.target_count, job.limit_videos, cfg.comment_days
        );

        let lab = LabCommands::new(&self.hub);
        let search_result = lab
            .run_keyword_search(&search_kw, cfg.filter_publish_days_for_ui())
            .await?;
        let ok = search_result.get("ok").and_then(|v| v.as_bool()).unwrap_or(true);
        if !ok {
            warn!("plugin_lab keyword search returned ok=false: {search_result:?}");
        }

        lab.enable_network_hook().await?;
        let _ = lab.swipe_search_results(3).await;
        sleep(Duration::from_secs(6)).await;

        self.collect_until_target(job_id, job, cfg).await
    }

    async fn run_manual_job(
        &self,
        job_id: &str,
        job: &crate::db::CollectJob,
        cfg: &JobConfig,
    ) -> Result<(), String> {
        let input_url = cfg
            .input_url
            .clone()
            .or_else(|| job.input_url.clone())
            .unwrap_or_default();
        if input_url.trim().is_empty() {
            return Err("manual job missing input_url".into());
        }

        info!(
            "manual job {job_id}: intent={} url={}",
            cfg.intent, input_url
        );

        let lab = LabCommands::new(&self.hub);
        lab.open_url(&input_url).await?;
        sleep(Duration::from_secs(5)).await;
        lab.enable_network_hook().await?;

        if cfg.intent == "account_home" {
            let _ = lab.swipe_page_down(4).await;
            sleep(Duration::from_secs(6)).await;
        } else {
            sleep(Duration::from_secs(4)).await;
            let _ = lab.open_comment_sidebar().await;
            let _ = lab.scroll_comments(6).await;
            sleep(Duration::from_secs(3)).await;
        }

        self.collect_until_target(job_id, job, cfg).await
    }

    async fn collect_until_target(
        &self,
        job_id: &str,
        job: &crate::db::CollectJob,
        cfg: &JobConfig,
    ) -> Result<(), String> {
        let videos = self.load_videos_for_job(job_id, cfg)?;
        if videos.is_empty() {
            return Err(
                "search produced no videos — ensure Douyin tab is active and logged in".into(),
            );
        }

        let scroll_rounds = scroll_rounds_for_target(cfg.target_count, job.max_comments_per_video);
        let mut pass = 0_u32;

        while self.db.count_comments_for_job(job_id)? < cfg.target_count && pass < 3 {
            pass += 1;
            for (index, video) in videos.iter().enumerate() {
                if self.db.count_comments_for_job(job_id)? >= cfg.target_count {
                    break;
                }
                info!(
                    "job {job_id}: video {}/{} aweme={}",
                    index + 1,
                    videos.len(),
                    video.aweme_id
                );
                self.open_and_scroll_video(&video.aweme_id, scroll_rounds)
                    .await?;
            }
            if self.db.count_comments_for_job(job_id)? >= cfg.target_count {
                break;
            }
            let lab = LabCommands::new(&self.hub);
            let _ = lab.scroll_comments(2).await;
            sleep(Duration::from_secs(3)).await;
        }

        let count = self.db.count_comments_for_job(job_id)?;
        if count == 0 {
            return Err("no comments captured — check login state and filters".into());
        }
        info!("job {job_id}: captured {count} comments (target {})", cfg.target_count);
        Ok(())
    }

    fn load_videos_for_job(
        &self,
        job_id: &str,
        cfg: &JobConfig,
    ) -> Result<Vec<CapturedVideo>, String> {
        let mut videos = self.db.list_videos_for_job(job_id)?;
        videos = filters::filter_videos_by_region(videos, cfg.region_name.as_deref());
        if videos.len() > cfg.target_count as usize {
            // still respect video batch limit from form
        }
        let job = self.db.get_job(job_id)?;
        if videos.len() > job.limit_videos as usize {
            videos.truncate(job.limit_videos as usize);
        }
        Ok(videos)
    }

    async fn open_and_scroll_video(&self, aweme_id: &str, scroll_rounds: i64) -> Result<(), String> {
        let lab = LabCommands::new(&self.hub);
        lab.open_video(aweme_id, None).await?;
        sleep(Duration::from_secs(5)).await;
        let _ = lab.open_comment_sidebar().await;
        let _ = lab.scroll_comments(scroll_rounds).await;
        sleep(Duration::from_secs(4)).await;
        Ok(())
    }
}

fn scroll_rounds_for_target(target_count: i64, max_per_video: i64) -> i64 {
    let per = max_per_video.clamp(5, 30);
    let need = (target_count / per.max(1)).clamp(1, 8);
    need
}

pub fn spawn_job(db: Database, hub: BridgeHub, default_daily_quota: i64, job_id: String) {
    let orchestrator = Arc::new(JobOrchestrator {
        db,
        hub,
        default_daily_quota,
    });
    tokio::spawn(async move {
        if let Err(err) = orchestrator.run_job(&job_id).await {
            tracing::error!("job {job_id} failed: {err}");
        }
    });
}
