mod outreach;

use std::sync::Arc;
use std::time::Duration;

use crate::simulate;
use tracing::{info, warn};

use crate::db::{CapturedVideo, Database, JobStatus};
use crate::douyin::parser::{
    dom_poster_index, is_dom_poster_aweme_id, parse_aweme_id_from_page_url,
    parse_dom_scroll_comments, parse_dom_search_results, resolve_aweme_id_for_video,
    ParsedVideo,
};
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

        if self.is_job_paused(job_id)? {
            info!("job {job_id} paused");
            return Ok(());
        }

        match result {
            Ok(()) => {
                if self.is_job_paused(job_id)? {
                    info!("job {job_id} paused");
                    return Ok(());
                }
                if cfg.should_run_auto_outreach() {
                    let runner = InlineOutreachRunner {
                        db: &self.db,
                        hub: &self.hub,
                        default_daily_quota: self.default_daily_quota,
                    };
                    if let Err(err) = runner.run(job_id, &cfg).await {
                        warn!("job {job_id} inline outreach partial failure: {err}");
                    }
                } else {
                    info!(
                        "job {job_id}: skipping outreach (auto_outreach={}, follow={}, dm={}, reply_presets={}, dm_presets={})",
                        cfg.auto_outreach,
                        cfg.interaction.follow_per_day,
                        cfg.interaction.dm_per_day,
                        cfg.comment_presets.len(),
                        cfg.dm_presets.len(),
                    );
                }
                if self.is_job_paused(job_id)? {
                    info!("job {job_id} paused");
                    return Ok(());
                }
                self.db
                    .update_job_status(job_id, JobStatus::Completed, None)?;
                info!("job {job_id} completed");
                Ok(())
            }
            Err(err) => {
                if self.is_job_paused(job_id)? {
                    info!("job {job_id} paused");
                    return Ok(());
                }
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
            let msg = search_result
                .get("message")
                .and_then(|v| v.as_str())
                .unwrap_or("keyword search failed");
            return Err(msg.to_string());
        }

        self.ensure_search_videos_captured(job_id, &lab, Some(&search_result))
            .await?;

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
        simulate::pause(Duration::from_secs(5)).await;
        lab.enable_network_hook().await?;

        if cfg.intent == "account_home" {
            let _ = lab.swipe_page_down(4).await;
            simulate::pause(Duration::from_secs(6)).await;
        } else {
            simulate::pause(Duration::from_secs(4)).await;
            let _ = lab.open_comment_sidebar().await;
            let _ = lab.scroll_comments(6, 80, cfg.comment_days).await;
            simulate::pause(Duration::from_secs(3)).await;
            if let Some(aweme_id) = parse_aweme_id_from_page_url(&input_url) {
                let video = ParsedVideo {
                    aweme_id,
                    video_url: input_url.clone(),
                    title: String::new(),
                    author: String::new(),
                    raw_json: None,
                };
                let _ = self.db.upsert_videos(job_id, &[video]);
            }
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

        let scroll_rounds =
            scroll_rounds_for_video(job.max_comments_per_video, cfg.comment_days);
        let mut pass = 0_u32;
        let mut opened_videos = 0_u32;

        let lab = LabCommands::new(&self.hub);
        let _ = lab.prepare_search_for_video().await;
        simulate::pause(Duration::from_millis(500)).await;

        while self.db.count_comments_for_job(job_id)? < cfg.target_count && pass < 3 {
            if self.is_job_paused(job_id)? {
                return Ok(());
            }
            pass += 1;
            for (index, video) in videos.iter().enumerate() {
                if self.is_job_paused(job_id)? {
                    return Ok(());
                }
                if self.db.count_comments_for_job(job_id)? >= cfg.target_count {
                    break;
                }
                info!(
                    "job {job_id}: video {}/{} aweme={}",
                    index + 1,
                    videos.len(),
                    video.aweme_id
                );
                match self
                    .open_and_scroll_video(job_id, video, scroll_rounds, cfg, job)
                    .await
                {
                    Ok(()) => {
                        opened_videos += 1;
                    }
                    Err(err) => {
                        warn!(
                            "job {job_id}: skip video {} ({}) — {}",
                            index + 1,
                            video.aweme_id,
                            err
                        );
                        let _ = lab.prepare_search_for_video().await;
                        simulate::pause(Duration::from_millis(600)).await;
                    }
                }
            }
            if self.db.count_comments_for_job(job_id)? >= cfg.target_count {
                break;
            }
            let lab = LabCommands::new(&self.hub);
            let _ = lab
                .scroll_comments(4, job.max_comments_per_video, cfg.comment_days)
                .await;
            simulate::pause(Duration::from_secs(3)).await;
        }

        let count = self.db.count_comments_for_job(job_id)?;
        if count == 0 {
            if opened_videos == 0 {
                return Err(
                    "failed to open any search result video — keep Douyin tab focused on search results"
                        .into(),
                );
            }
            return Err("no comments captured — check login state and filters".into());
        }
        info!("job {job_id}: captured {count} comments (target {})", cfg.target_count);
        Ok(())
    }

    async fn ensure_search_videos_captured(
        &self,
        job_id: &str,
        lab: &LabCommands<'_>,
        search_resp: Option<&serde_json::Value>,
    ) -> Result<(), String> {
        let mut videos = search_resp
            .map(parse_dom_search_results)
            .unwrap_or_default();
        let source = if videos.is_empty() {
            info!("job {job_id}: step 7 had no items, falling back to fetch_search_results (lab step 8)");
            let resp = lab.fetch_search_results(30).await?;
            videos = parse_dom_search_results(&resp);
            "step8"
        } else {
            "step7"
        };

        if videos.is_empty() {
            if !self.db.list_videos_for_job(job_id)?.is_empty() {
                warn!(
                    "job {job_id}: search returned no parsable videos, reusing cached list"
                );
                return Ok(());
            }
            return Err(
                "search produced no videos — run plugin lab step 7/8 on the Douyin tab to verify results"
                    .into(),
            );
        }

        let inserted = self.db.replace_videos_for_job(job_id, &videos)?;
        info!(
            "job {job_id}: stored {inserted} search videos from {source} (dom_poster={})",
            videos.iter().filter(|v| is_dom_poster_aweme_id(&v.aweme_id)).count()
        );
        Ok(())
    }

    fn load_videos_for_job(
        &self,
        job_id: &str,
        cfg: &JobConfig,
    ) -> Result<Vec<CapturedVideo>, String> {
        let mut videos = self.db.list_videos_for_job(job_id)?;
        let raw_count = videos.len();
        // 关键词任务已将 region 拼入搜索词；DOM 卡片 title 常不含地域，不再二次过滤视频。
        if cfg.intent != "keyword_auto" {
            videos = filters::filter_videos_by_region(videos, cfg.region_name.as_deref());
        }
        if videos.is_empty() {
            if raw_count > 0 {
                return Err(format!(
                    "search captured {raw_count} videos but none matched region {:?} — try clearing region or broadening keyword",
                    cfg.region_name
                ));
            }
            return Err(
                "search produced no videos — ensure Douyin is logged in, search results visible, and keep the tab active".into(),
            );
        }
        if videos.len() > cfg.target_count as usize {
            // still respect video batch limit from form
        }
        let job = self.db.get_job(job_id)?;
        if videos.len() > job.limit_videos as usize {
            videos.truncate(job.limit_videos as usize);
        }
        Ok(videos)
    }

    async fn open_and_scroll_video(
        &self,
        job_id: &str,
        video: &CapturedVideo,
        scroll_rounds: i64,
        cfg: &JobConfig,
        job: &crate::db::CollectJob,
    ) -> Result<(), String> {
        let lab = LabCommands::new(&self.hub);
        if is_dom_poster_aweme_id(&video.aweme_id) {
            let index = dom_poster_index(&video.aweme_id).unwrap_or(1);
            let aweme_hint = parse_aweme_id_from_page_url(&video.video_url);
            let clicked = lab.click_search_video(index, None, aweme_hint.as_deref()).await?;
            let ok = clicked.get("ok").and_then(|v| v.as_bool()).unwrap_or(false);
            let feed_open = clicked
                .get("is_search_feed")
                .and_then(|v| v.as_bool())
                .or_else(|| clicked.get("feed_open").and_then(|v| v.as_bool()))
                .unwrap_or(false);
            if !ok || !feed_open {
                let msg = clicked
                    .get("message")
                    .and_then(|v| v.as_str())
                    .unwrap_or("video feed did not open after click");
                return Err(msg.to_string());
            }
            info!(
                "job {job_id}: opened search video #{index} mode={:?} attempt={:?}",
                clicked.get("mode").and_then(|v| v.as_str()),
                clicked.get("attempt").and_then(|v| v.as_u64())
            );
        } else {
            lab.open_video(
                &video.aweme_id,
                (!video.video_url.is_empty()).then_some(video.video_url.as_str()),
            )
            .await?;
        }
        simulate::human_pause_ms(5500, 8500).await;

        let mut sidebar_ok = false;
        for attempt in 1..=3 {
            let sidebar = lab.open_comment_sidebar().await?;
            sidebar_ok = sidebar.get("ok").and_then(|v| v.as_bool()).unwrap_or(false)
                || (sidebar
                    .get("comment_item_count")
                    .and_then(|v| v.as_i64())
                    .unwrap_or(0)
                    > 0);
            if sidebar_ok {
                break;
            }
            let msg = sidebar
                .get("message")
                .and_then(|v| v.as_str())
                .unwrap_or("failed to open comment sidebar");
            warn!("job {job_id}: comment sidebar attempt {attempt}/3 — {msg}");
            simulate::human_pause_ms(1200, 2200).await;
        }
        if !sidebar_ok {
            return Err("failed to open comment sidebar after 3 attempts".into());
        }
        simulate::human_pause_ms(1500, 2800).await;

        let scroll_resp = lab
            .scroll_comments(
                scroll_rounds,
                job.max_comments_per_video,
                cfg.comment_days,
            )
            .await?;
        let page_url = scroll_resp
            .get("url")
            .and_then(|v| v.as_str());
        let aweme_id = resolve_aweme_id_for_video(
            &video.aweme_id,
            &video.video_url,
            page_url,
        );
        let dom_comments = parse_dom_scroll_comments(&scroll_resp);
        let api_cached = scroll_resp
            .get("api_count")
            .and_then(|v| v.as_i64())
            .unwrap_or(0);
        let existing_for_aweme = self.db.count_comments_for_aweme(job_id, &aweme_id).unwrap_or(0);
        let persistable: Vec<_> = dom_comments
            .into_iter()
            .filter(|c| !c.comment_id.starts_with("dom_"))
            .collect();

        if existing_for_aweme > 0 && persistable.is_empty() {
            info!(
                "job {job_id}: skip DOM upsert for aweme {aweme_id} — {existing_for_aweme} API comments already stored (scroll api_count={api_cached})"
            );
        } else if !persistable.is_empty() {
            let inserted = self.db.upsert_comments(job_id, &aweme_id, &persistable)?;
            info!(
                "job {job_id}: stored {inserted} scroll comments for aweme {aweme_id} (stopped={:?})",
                scroll_resp.get("stopped_reason").and_then(|v| v.as_str())
            );
        } else if existing_for_aweme == 0 && api_cached == 0 {
            warn!(
                "job {job_id}: scroll returned 0 persistable comments for aweme {} — {:?}",
                aweme_id,
                scroll_resp.get("message").and_then(|v| v.as_str())
            );
        }

        simulate::human_pause_ms(2500, 4500).await;
        if is_dom_poster_aweme_id(&video.aweme_id) {
            let closed = lab.close_video_detail().await?;
            if !closed.get("ok").and_then(|v| v.as_bool()).unwrap_or(true) {
                warn!(
                    "job {job_id}: close_video_detail may have failed — {:?}",
                    closed.get("message").and_then(|v| v.as_str())
                );
            }
            let _ = lab.prepare_search_for_video().await;
            simulate::human_pause_ms(1200, 2200).await;
        }
        Ok(())
    }

    fn is_job_paused(&self, job_id: &str) -> Result<bool, String> {
        Ok(self.db.get_job(job_id)?.status == JobStatus::Paused)
    }
}

fn scroll_rounds_for_video(max_per_video: i64, comment_days: i64) -> i64 {
    let per = max_per_video.clamp(10, 300);
    let load_rounds = (per / 8).clamp(4, 40);
    let days_rounds = if comment_days > 0 {
        (comment_days * 2).clamp(6, 60)
    } else {
        20
    };
    load_rounds.max(days_rounds).clamp(4, 60)
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
