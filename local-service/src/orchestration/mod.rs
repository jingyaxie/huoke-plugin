mod outreach;

use std::sync::Arc;
use std::time::Duration;

use crate::simulate;
use tracing::{info, warn};

use crate::db::{CapturedVideo, Database, JobStatus};
use crate::douyin::parser::{
    dom_poster_click_payload, dom_poster_index, is_dom_poster_aweme_id, merge_parsed_videos,
    parse_aweme_id_from_page_url, parse_dom_scroll_comments, resolve_aweme_id_for_video, ParsedVideo,
};
use crate::filters;
use crate::job_config::JobConfig;
use crate::job_run::JobRunRegistry;
use crate::platforms::parse_plugin_lab_search_results;
use crate::lab_commands::LabCommands;
use crate::orchestration::outreach::InlineOutreachRunner;
use crate::ws::BridgeHub;

const JOB_PAUSED: &str = "__job_paused__";

#[derive(Clone, Debug)]
enum DouyinFeedSource {
    KeywordSearch,
    ProfileHome { profile_url: String },
}

fn feed_aweme_from_response(resp: &serde_json::Value) -> Option<String> {
    resp.get("aweme_id")
        .and_then(|v| v.as_str())
        .map(str::trim)
        .filter(|s| !s.is_empty() && !is_dom_poster_aweme_id(s))
        .map(str::to_string)
        .or_else(|| {
            resp.get("url")
                .and_then(|v| v.as_str())
                .and_then(parse_aweme_id_from_page_url)
        })
}

/// 插件已打开可采评论的视频上下文：Feed 浮层 / 右侧独立窗 / 工作窗 /video/ 页
fn video_ready_for_collect(resp: &serde_json::Value) -> bool {
    if resp.get("ok").and_then(|v| v.as_bool()) != Some(true) {
        return false;
    }
    if resp.get("is_search_feed").and_then(|v| v.as_bool()) == Some(true) {
        return true;
    }
    if resp.get("detail_window").and_then(|v| v.as_bool()) == Some(true) {
        return true;
    }
    if resp.get("is_content_detail").and_then(|v| v.as_bool()) == Some(true) {
        return true;
    }
    if resp.get("is_standalone_video").and_then(|v| v.as_bool()) == Some(true) {
        return true;
    }
    if resp.get("feed_open").and_then(|v| v.as_bool()) == Some(true) {
        return true;
    }
    resp.get("url")
        .and_then(|v| v.as_str())
        .is_some_and(|u| u.contains("/video/") || u.contains("/short-video/"))
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum DouyinPlaybackMode {
    Feed,
    VideoDetail,
}

fn response_is_standalone_video(resp: &serde_json::Value) -> bool {
    if resp.get("is_standalone_video").and_then(|v| v.as_bool()) == Some(true) {
        return true;
    }
    resp.get("url")
        .and_then(|v| v.as_str())
        .is_some_and(|u| u.contains("/video/") || u.contains("/short-video/"))
}

fn playback_mode_from_response(resp: &serde_json::Value) -> Option<DouyinPlaybackMode> {
    if resp.get("is_search_feed").and_then(|v| v.as_bool()) == Some(true)
        || resp.get("feed_open").and_then(|v| v.as_bool()) == Some(true)
    {
        return Some(DouyinPlaybackMode::Feed);
    }
    if response_is_standalone_video(resp) {
        return Some(DouyinPlaybackMode::VideoDetail);
    }
    None
}

fn playback_navigation_ok(resp: &serde_json::Value, mode: DouyinPlaybackMode) -> bool {
    if !video_ready_for_collect(resp) {
        return false;
    }
    match mode {
        DouyinPlaybackMode::Feed => feed_navigation_ok(resp),
        DouyinPlaybackMode::VideoDetail => feed_aweme_from_response(resp).is_some(),
    }
}

fn feed_navigation_ok(resp: &serde_json::Value) -> bool {
    video_ready_for_collect(resp) && feed_aweme_from_response(resp).is_some()
}

fn playback_mode_label(mode: DouyinPlaybackMode) -> &'static str {
    match mode {
        DouyinPlaybackMode::Feed => "feed",
        DouyinPlaybackMode::VideoDetail => "video_detail",
    }
}

pub struct JobOrchestrator {
    pub db: Database,
    pub hub: BridgeHub,
    pub default_daily_quota: i64,
    pub job_runs: JobRunRegistry,
    pub generation: u64,
    pub data_dir: std::path::PathBuf,
}

impl JobOrchestrator {
    pub async fn run_job(&self, job_id: &str) -> Result<(), String> {
        if !self.job_runs.is_current(job_id, self.generation) {
            info!("job {job_id}: superseded before start (gen={})", self.generation);
            return Ok(());
        }
        if self.hub.client_count() == 0 {
            return Err("no extension connected".into());
        }

        let job = self.db.get_job(job_id)?;
        let cfg = JobConfig::from_job(&job);
        let platform = job.platform.clone();
        self.db
            .update_job_status(job_id, JobStatus::Running, None)?;

        let result = if job.job_type == "manual" {
            self.run_manual_job(job_id, &job, &cfg).await
        } else {
            self.run_keyword_job(job_id, &job, &cfg).await
        };

        if self.is_job_paused(job_id)? || !self.job_runs.is_current(job_id, self.generation) {
            info!("job {job_id} paused");
            return Ok(());
        }

        match result {
            Ok(()) => {
                if !self.job_runs.is_current(job_id, self.generation) {
                    info!("job {job_id}: superseded after run");
                    return Ok(());
                }
                if self.is_job_paused(job_id)? {
                    info!("job {job_id} paused");
                    return Ok(());
                }
                let job = self.db.get_job(job_id)?;
                if let Err(err) = crate::evaluation::evaluate_job_comments(
                    &self.db,
                    &self.data_dir,
                    job_id,
                    &job.keyword,
                    &cfg.evaluation,
                )
                .await
                {
                    warn!("job {job_id}: comment evaluation error: {err}");
                }
                if self.uses_precise_collect_target() && !cfg.collects_by_video_limit() {
                    let precise = self.db.count_precise_comments_for_job(job_id)?;
                    if precise < cfg.target_count {
                        let total = self.db.count_comments_for_job(job_id)?;
                        let msg = format!(
                            "仅识别到 {precise}/{} 条精准线索（共采集 {total} 条评论）",
                            cfg.target_count
                        );
                        self.db
                            .update_job_status(job_id, JobStatus::Failed, Some(&msg))?;
                        self.cleanup_job_workspace(&platform, job_id).await;
                        return Err(msg);
                    }
                }

                if cfg.collects_by_video_limit() {
                    let scanned = self.scanned_video_count(job_id)?;
                    self.db
                        .update_job_status(job_id, JobStatus::Completed, None)?;
                    info!(
                        "job {job_id}: scan completed ({scanned}/{} videos)",
                        job.limit_videos.max(1)
                    );
                } else {
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
                    self.cleanup_job_workspace(&platform, job_id).await;
                    return Ok(());
                }

                if self.is_job_paused(job_id)? {
                    info!("job {job_id} paused");
                    return Ok(());
                }
                if cfg.should_run_auto_outreach() {
                    info!("job {job_id}: post-scan outreach (status=completed)");
                    let runner = InlineOutreachRunner {
                        db: &self.db,
                        hub: &self.hub,
                        default_daily_quota: self.default_daily_quota,
                    };
                    if let Err(err) = runner.run(job_id, &cfg).await {
                        warn!("job {job_id} post-scan outreach partial failure: {err}");
                    }
                } else {
                    info!(
                        "job {job_id}: skipping post-scan outreach (auto_outreach={}, follow={}, dm={})",
                        cfg.auto_outreach,
                        cfg.interaction.follow_per_day,
                        cfg.interaction.dm_per_day,
                    );
                }
                self.cleanup_job_workspace(&platform, job_id).await;
                Ok(())
            }
            Err(err) if err == JOB_PAUSED => {
                info!("job {job_id} paused");
                Ok(())
            }
            Err(err) => {
                if self.is_job_paused(job_id)? {
                    info!("job {job_id} paused");
                    return Ok(());
                }
                self.db
                    .update_job_status(job_id, JobStatus::Failed, Some(&err))?;
                self.cleanup_job_workspace(&platform, job_id).await;
                Err(err)
            }
        }
    }

    async fn cleanup_job_workspace(&self, platform: &str, job_id: &str) {
        info!("job {job_id}: closing task browser workspace");
        let lab = LabCommands::new(&self.hub, platform);
        match lab.close_browser().await {
            Ok(resp) => {
                let closed = resp.get("closed").and_then(|v| v.as_bool()).unwrap_or(false);
                info!("job {job_id}: close_browser closed={closed}");
            }
            Err(err) => warn!("job {job_id}: close_browser failed: {err}"),
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

        let lab = LabCommands::new(&self.hub, &job.platform);
        let existing_progress = self.collect_progress_count(job_id)?;
        let resume_collect = if cfg.collects_by_video_limit() {
            let videos_collected = self.db.count_distinct_comment_awemes_for_job(job_id)?;
            videos_collected > 0 && videos_collected < job.limit_videos.max(1)
        } else {
            existing_progress > 0 && existing_progress < cfg.target_count
        };
        let feed_collect = job.platform == "douyin" && cfg.intent == "keyword_auto";

        if resume_collect {
            info!(
                "job {job_id}: continue collect — {} {} stored (target {}), re-run keyword search ({search_kw})",
                existing_progress,
                self.collect_progress_label(),
                cfg.target_count
            );
        }

        if feed_collect {
            let remaining = self.videos_remaining_quota(job_id, job, cfg)?;
            if remaining == 0 {
                let collected = self.scanned_video_count(job_id)?;
                info!(
                    "job {job_id}: scan quota already met ({collected}/{} videos), skip playback collect",
                    job.limit_videos.max(1)
                );
                return Ok(());
            }
            lab.run_keyword_search(
                &search_kw,
                cfg.filter_publish_days_for_ui(),
                false,
            )
            .await?;
            return self
                .collect_douyin_via_playback_chain(job_id, job, cfg, DouyinFeedSource::KeywordSearch)
                .await;
        }

        let mut keyword_researched = false;
        let search_result = lab
            .run_keyword_search(
                &search_kw,
                cfg.filter_publish_days_for_ui(),
                true,
            )
            .await?;
        keyword_researched = true;
        let videos_preview = parse_plugin_lab_search_results(&job.platform, &search_result);
        let ok = search_result.get("ok").and_then(|v| v.as_bool()).unwrap_or(true);
        if !ok && videos_preview.is_empty() {
            let msg = search_result
                .get("message")
                .and_then(|v| v.as_str())
                .unwrap_or("keyword search failed");
            return Err(msg.to_string());
        }

        self.ensure_search_videos_captured(
            job_id,
            &job.platform,
            &lab,
            Some(&search_result),
            job.limit_videos,
        )
        .await?;

        self.collect_until_target(job_id, job, cfg, &mut keyword_researched)
            .await
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

        let lab = LabCommands::new(&self.hub, &job.platform);
        let adapter = crate::platforms::get_platform_adapter(&job.platform);
        let open_url = adapter.normalize_manual_open_url(&input_url, &cfg.intent);

        if cfg.intent == "single_video" && job.platform == "douyin" {
            return self
                .collect_douyin_single_video(job_id, job, cfg, &input_url, &open_url)
                .await;
        }

        // 复用平台工作窗（左侧半屏），与关键词任务一致；无工作窗时 open_browser 会新建
        lab.open_url(&open_url).await?;
        self.wait_if_not_paused(job_id, Duration::from_secs(3)).await?;
        lab.enable_network_hook().await?;
        self.wait_if_not_paused(job_id, Duration::from_secs(4)).await?;

        if cfg.intent == "account_home" && job.platform == "douyin" {
            let _ = lab.close_video_detail().await;
            self.wait_if_not_paused(job_id, Duration::from_millis(800)).await?;
            return self
                .collect_douyin_via_playback_chain(
                    job_id,
                    job,
                    cfg,
                    DouyinFeedSource::ProfileHome {
                        profile_url: open_url.clone(),
                    },
                )
                .await;
        }

        if cfg.intent == "account_home" {
            let _ = lab.close_video_detail().await;
            self.wait_if_not_paused(job_id, Duration::from_millis(800)).await?;
            self.ensure_profile_videos_captured(job_id, &job.platform, &lab, &open_url, job.limit_videos)
                .await?;
        } else {
            self.wait_if_not_paused(job_id, Duration::from_secs(4)).await?;
            let max_comments = if cfg.intent == "single_video" {
                job.max_comments_per_video.max(80)
            } else {
                80
            };
            let scroll_rounds = if cfg.intent == "single_video" { 12 } else { 6 };
            let _ = lab.open_comment_sidebar().await;
            let _ = lab
                .scroll_comments(scroll_rounds, max_comments, cfg.comment_days)
                .await;
            self.wait_if_not_paused(job_id, Duration::from_secs(3)).await?;
            if let Some(aweme_id) = adapter.extract_content_id_from_url(&input_url) {
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

        let mut keyword_researched = false;
        self.collect_until_target(job_id, job, cfg, &mut keyword_researched)
            .await
    }

    async fn ensure_profile_videos_captured(
        &self,
        job_id: &str,
        platform: &str,
        lab: &LabCommands<'_>,
        profile_url: &str,
        limit_videos: i64,
    ) -> Result<(), String> {
        // 短暂等待 local-service 侧 network.captured 入库（与 extension 内 API 缓存并行）
        for _ in 0..4 {
            self.bail_if_paused(job_id)?;
            if !self.db.list_videos_for_job(job_id)?.is_empty() {
                info!("job {job_id}: profile videos captured via network hook (server)");
                return Ok(());
            }
            self.wait_if_not_paused(job_id, Duration::from_millis(800)).await?;
        }

        info!("job {job_id}: fetching profile videos — API first, DOM fallback (no scroll)");
        let resp = lab
            .fetch_profile_videos(limit_videos.clamp(1, 50))
            .await?;
        let msg = resp
            .get("message")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let capture_method = resp
            .get("capture_method")
            .and_then(|v| v.as_str())
            .unwrap_or("unknown");
        let videos = parse_plugin_lab_search_results(platform, &resp);
        if videos.is_empty() {
            if !self.db.list_videos_for_job(job_id)?.is_empty() {
                return Ok(());
            }
            return Err(if msg.is_empty() {
                "profile produced no videos — ensure Douyin profile tab is active".into()
            } else {
                format!("profile produced no videos — {msg}")
            });
        }

        let inserted = self.db.replace_videos_for_job(job_id, &videos)?;
        info!(
            "job {job_id}: stored {inserted} profile videos via {capture_method} (url={})",
            &profile_url[..profile_url.len().min(64)]
        );
        Ok(())
    }

    /// 抖音播放链采集：搜索/主页打开第一个视频，在 Feed 或 /video/ 详情页内切视频采集评论。
    async fn collect_douyin_via_playback_chain(
        &self,
        job_id: &str,
        job: &crate::db::CollectJob,
        cfg: &JobConfig,
        feed_source: DouyinFeedSource,
    ) -> Result<(), String> {
        use std::collections::HashMap;

        let lab = LabCommands::new(&self.hub, &job.platform);
        let scroll_rounds =
            scroll_rounds_for_video(job.max_comments_per_video, cfg.comment_days);
        let remaining_quota = self.videos_remaining_quota(job_id, job, cfg)? as u32;
        let mut playback_open = false;
        let mut playback_mode: Option<DouyinPlaybackMode> = None;
        let mut collected_videos = 0_u32;
        let mut swipe_failures = 0_u32;
        let mut search_exhausted = false;
        let mut stale_hits: HashMap<String, u32> = HashMap::new();
        let mut last_aweme_id: Option<String> = None;
        const MAX_SWIPE_FAILURES: u32 = 8;
        const MAX_STALE_ON_SAME: u32 = 3;

        let (open_label, fail_hint) = match &feed_source {
            DouyinFeedSource::KeywordSearch => (
                "open first search result in playback",
                "failed to open search playback or collect any video — keep Douyin on search results",
            ),
            DouyinFeedSource::ProfileHome { .. } => (
                "open first profile video in feed",
                "failed to open profile feed or collect any video — keep Douyin on blogger profile page",
            ),
        };

        info!(
            "job {job_id}: playback chain start — remaining_quota={remaining_quota} scroll_rounds={scroll_rounds}"
        );

        loop {
            self.bail_if_paused(job_id)?;
            if self.is_job_paused(job_id)? {
                return Ok(());
            }
            if self.video_scan_quota_met(job_id, job, false)? {
                info!(
                    "job {job_id}: playback chain scan quota met ({}/{})",
                    self.scanned_video_count(job_id)?,
                    job.limit_videos.max(1)
                );
                break;
            }
            if remaining_quota == 0 || collected_videos >= remaining_quota {
                info!(
                    "job {job_id}: playback chain quota reached ({collected_videos}/{remaining_quota} new this run)"
                );
                break;
            }
            if swipe_failures >= MAX_SWIPE_FAILURES {
                search_exhausted = true;
                warn!(
                    "job {job_id}: playback swipe failed {swipe_failures} times, stop collect"
                );
                break;
            }

            let opening_first = !playback_open;
            let nav = if opening_first {
                info!("job {job_id}: {open_label}");
                self.open_or_adopt_playback(&lab, &feed_source).await
            } else {
                let mode = playback_mode.unwrap_or(DouyinPlaybackMode::Feed);
                match mode {
                    DouyinPlaybackMode::Feed => {
                        self.feed_swipe_next(&lab, last_aweme_id.as_deref()).await
                    }
                    DouyinPlaybackMode::VideoDetail => self.detail_swipe_next(&lab).await,
                }
            };

            let resp = match nav {
                Ok(r) => r,
                Err(err) => {
                    swipe_failures += 1;
                    warn!("job {job_id}: playback navigation error — {err}");
                    simulate::pause(Duration::from_millis(800)).await;
                    continue;
                }
            };

            if opening_first {
                if let Some(detected) = playback_mode_from_response(&resp) {
                    playback_mode = Some(detected);
                } else if video_ready_for_collect(&resp) {
                    playback_mode = Some(DouyinPlaybackMode::VideoDetail);
                }
            }

            let mode = playback_mode.unwrap_or(DouyinPlaybackMode::Feed);
            let nav_ok = if opening_first {
                video_ready_for_collect(&resp)
            } else {
                playback_navigation_ok(&resp, mode)
            };
            if !nav_ok {
                swipe_failures += 1;
                warn!(
                    "job {job_id}: playback navigation not ready ({}) — {:?}",
                    playback_mode_label(mode),
                    resp.get("message").and_then(|v| v.as_str())
                );
                simulate::pause(Duration::from_millis(800)).await;
                continue;
            }

            if opening_first {
                info!(
                    "job {job_id}: playback mode={} feed={} standalone={}",
                    playback_mode_label(mode),
                    resp.get("is_search_feed").and_then(|v| v.as_bool()).unwrap_or(false),
                    response_is_standalone_video(&resp),
                );
            }

            playback_open = true;

            let aweme_id = feed_aweme_from_response(&resp).unwrap_or_default();
            let aweme_id = if aweme_id.is_empty() {
                lab.probe_current_playback()
                    .await
                    .ok()
                    .and_then(|p| feed_aweme_from_response(&p))
                    .unwrap_or_default()
            } else {
                aweme_id
            };

            if aweme_id.is_empty() {
                swipe_failures += 1;
                warn!("job {job_id}: playback open but aweme_id unknown");
                continue;
            }
            last_aweme_id = Some(aweme_id.clone());

            if self.aweme_comments_already_collected(job_id, &aweme_id)? {
                info!(
                    "job {job_id}: skip aweme {aweme_id} — already collected, swipe next"
                );
                continue;
            }

            let stale = stale_hits.entry(aweme_id.clone()).or_insert(0);
            *stale += 1;
            if *stale > MAX_STALE_ON_SAME {
                swipe_failures += 1;
                warn!(
                    "job {job_id}: stuck on aweme {aweme_id} ({stale} times), treat as swipe failure"
                );
                continue;
            }

            info!(
                "job {job_id}: collect comments in {} aweme={aweme_id} ({}/{remaining_quota})",
                playback_mode_label(mode),
                collected_videos + 1
            );

            let collect_result = match mode {
                DouyinPlaybackMode::Feed => {
                    self.scroll_and_persist_feed_comments(
                        job_id,
                        job,
                        cfg,
                        &aweme_id,
                        scroll_rounds,
                    )
                    .await
                }
                DouyinPlaybackMode::VideoDetail => {
                    self.scroll_and_persist_video_detail_comments(
                        job_id,
                        job,
                        cfg,
                        &aweme_id,
                        scroll_rounds,
                    )
                    .await
                }
            };

            match collect_result {
                Ok(()) => {
                    collected_videos += 1;
                    swipe_failures = 0;
                    stale_hits.clear();
                    if self.uses_precise_collect_target() {
                        let _ = self
                            .evaluate_pending_comments(job_id, job, cfg)
                            .await;
                    }
                    if self.video_scan_quota_met(job_id, job, false)? {
                        info!(
                            "job {job_id}: scan quota met after video collect ({}/{})",
                            self.scanned_video_count(job_id)?,
                            job.limit_videos.max(1)
                        );
                        break;
                    }
                }
                Err(err) if err == JOB_PAUSED => return Ok(()),
                Err(err) => {
                    warn!(
                        "job {job_id}: {} collect failed for {aweme_id} — {err}",
                        playback_mode_label(mode)
                    );
                    simulate::pause(Duration::from_millis(600)).await;
                }
            }
        }

        if self.uses_precise_collect_target() {
            let _ = self.evaluate_pending_comments(job_id, job, cfg).await;
        }

        let total = self.db.count_comments_for_job(job_id)?;
        if cfg.collects_by_video_limit() {
            let scanned = self.scanned_video_count(job_id)?;
            if self.video_scan_quota_met(job_id, job, search_exhausted)? {
                info!(
                    "job {job_id}: video-limit collect done — {scanned}/{} videos scanned ({} comments, playback browsed {collected_videos} new, exhausted={search_exhausted})",
                    job.limit_videos, total
                );
                return Ok(());
            }
            if total == 0 && collected_videos == 0 {
                return Err(fail_hint.into());
            }
            if total > 0 {
                info!(
                    "job {job_id}: video-limit collect done — {scanned}/{} videos scanned ({} comments)",
                    job.limit_videos, total
                );
                return Ok(());
            }
            return Err(fail_hint.into());
        }
        if total == 0 && collected_videos == 0 {
            return Err(fail_hint.into());
        }
        let progress = self.collect_progress_count(job_id)?;
        if progress < cfg.target_count {
            let label = self.collect_progress_label();
            return Err(format!(
                "仅识别到 {progress}/{} 条{label}（共采集 {total} 条评论，播放页内已浏览 {collected_videos} 个新视频）",
                cfg.target_count
            ));
        }
        info!(
            "job {job_id}: {} {progress}/{} (total comments {total}, playback videos {collected_videos})",
            self.collect_progress_label(),
            cfg.target_count,
        );
        Ok(())
    }

    /// 抖音单视频：打开独立详情页（含 v.douyin.com 短链）→ 点评论 → 采集，不走 Feed。
    async fn collect_douyin_single_video(
        &self,
        job_id: &str,
        job: &crate::db::CollectJob,
        cfg: &JobConfig,
        input_url: &str,
        open_url: &str,
    ) -> Result<(), String> {
        let lab = LabCommands::new(&self.hub, &job.platform);
        let adapter = crate::platforms::get_platform_adapter(&job.platform);
        let scroll_rounds =
            scroll_rounds_for_video(job.max_comments_per_video, cfg.comment_days);

        info!("job {job_id}: open douyin video detail (single_video, not feed)");
        let open_resp = lab.open_douyin_video_detail(open_url).await?;
        self.wait_if_not_paused(job_id, Duration::from_secs(3)).await?;
        lab.enable_network_hook().await?;
        self.wait_if_not_paused(job_id, Duration::from_millis(1500)).await?;

        let resolved_url = open_resp
            .get("url")
            .and_then(|v| v.as_str())
            .filter(|s| !s.is_empty())
            .unwrap_or(open_url);
        let aweme_id = adapter
            .extract_content_id_from_url(resolved_url)
            .or_else(|| adapter.extract_content_id_from_url(input_url))
            .unwrap_or_default();

        if aweme_id.is_empty() {
            return Err(
                "failed to resolve video id — open Douyin video detail page (/video/) after short link redirect"
                    .into(),
            );
        }

        let canonical_url = if resolved_url.contains("/video/") {
            resolved_url.to_string()
        } else {
            adapter.content_url(&aweme_id)
        };
        let video = ParsedVideo {
            aweme_id: aweme_id.clone(),
            video_url: canonical_url,
            title: String::new(),
            author: String::new(),
            raw_json: None,
        };
        let _ = self.db.upsert_videos(job_id, &[video]);

        info!(
            "job {job_id}: collect comments on standalone video aweme={aweme_id}"
        );
        self.scroll_and_persist_video_detail_comments(
            job_id,
            job,
            cfg,
            &aweme_id,
            scroll_rounds,
        )
        .await?;

        if self.uses_precise_collect_target() {
            let _ = self.evaluate_pending_comments(job_id, job, cfg).await;
        }

        let total = self.db.count_comments_for_job(job_id)?;
        let progress = self.collect_progress_count(job_id)?;
        if total == 0 {
            return Err(
                "no comments collected on video detail page — click comment icon failed or video has no comments"
                    .into(),
            );
        }
        if progress < cfg.target_count {
            let label = self.collect_progress_label();
            return Err(format!(
                "仅识别到 {progress}/{} 条{label}（共采集 {total} 条评论）",
                cfg.target_count
            ));
        }
        info!(
            "job {job_id}: single video done — {} {progress}/{} (total comments {total})",
            self.collect_progress_label(),
            cfg.target_count,
        );
        Ok(())
    }

    fn aweme_comments_already_collected(&self, job_id: &str, aweme_id: &str) -> Result<bool, String> {
        Ok(self.db.count_comments_for_aweme(job_id, aweme_id)? > 0)
    }

    async fn scroll_and_persist_feed_comments(
        &self,
        job_id: &str,
        job: &crate::db::CollectJob,
        cfg: &JobConfig,
        aweme_hint: &str,
        scroll_rounds: i64,
    ) -> Result<(), String> {
        self.scroll_and_persist_comments(
            job_id,
            job,
            cfg,
            aweme_hint,
            scroll_rounds,
            "feed",
        )
        .await
    }

    async fn scroll_and_persist_video_detail_comments(
        &self,
        job_id: &str,
        job: &crate::db::CollectJob,
        cfg: &JobConfig,
        aweme_hint: &str,
        scroll_rounds: i64,
    ) -> Result<(), String> {
        self.scroll_and_persist_comments(
            job_id,
            job,
            cfg,
            aweme_hint,
            scroll_rounds,
            "video_detail",
        )
        .await
    }

    async fn scroll_and_persist_comments(
        &self,
        job_id: &str,
        job: &crate::db::CollectJob,
        cfg: &JobConfig,
        aweme_hint: &str,
        scroll_rounds: i64,
        playback_mode: &str,
    ) -> Result<(), String> {
        self.bail_if_paused(job_id)?;
        let lab = LabCommands::new(&self.hub, &job.platform);

        let placeholder = ParsedVideo {
            aweme_id: aweme_hint.to_string(),
            video_url: String::new(),
            title: String::new(),
            author: String::new(),
            raw_json: None,
        };
        let _ = self.db.upsert_videos(job_id, &[placeholder]);

        self.wait_human_if_not_paused(job_id, 5500, 8500).await?;

        let mut sidebar_ok = false;
        for attempt in 1..=3 {
            self.bail_if_paused(job_id)?;
            let sidebar = if playback_mode == "video_detail" {
                lab.open_video_detail_comment_sidebar().await?
            } else {
                lab.open_feed_comment_sidebar().await?
            };
            sidebar_ok = sidebar.get("ok").and_then(|v| v.as_bool()).unwrap_or(false)
                || sidebar
                    .get("comment_item_count")
                    .and_then(|v| v.as_i64())
                    .unwrap_or(0)
                    > 0;
            if sidebar_ok {
                break;
            }
            self.wait_human_if_not_paused(job_id, 1200, 2200).await?;
        }
        if !sidebar_ok {
            return Err("failed to open comment sidebar after 3 attempts".into());
        }
        self.wait_human_if_not_paused(job_id, 1500, 2800).await?;

        let scroll_resp = if playback_mode == "video_detail" {
            lab.scroll_video_detail_comments(
                scroll_rounds,
                job.max_comments_per_video,
                cfg.comment_days,
            )
            .await?
        } else {
            lab.scroll_feed_comments(
                scroll_rounds,
                job.max_comments_per_video,
                cfg.comment_days,
            )
            .await?
        };
        let page_url = scroll_resp.get("url").and_then(|v| v.as_str());
        let aweme_id = resolve_aweme_id_for_video(aweme_hint, "", page_url);
        let scroll_comments = parse_dom_scroll_comments(&scroll_resp);
        let capture_method = scroll_resp
            .get("capture_method")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let persistable: Vec<_> = scroll_comments
            .into_iter()
            .filter(|c| capture_method == "dom" || !c.comment_id.starts_with("dom_"))
            .collect();

        if !persistable.is_empty() {
            let inserted = self.db.upsert_comments(job_id, &aweme_id, &persistable)?;
            info!(
                "job {job_id}: stored {inserted} comments for aweme {aweme_id} via {capture_method}"
            );
            if inserted > 0 {
                if self.uses_precise_collect_target() {
                    let _ = crate::evaluation::evaluate_job_comments(
                        &self.db,
                        &self.data_dir,
                        job_id,
                        &job.keyword,
                        &cfg.evaluation,
                    )
                    .await;
                } else {
                    crate::evaluation::spawn_evaluate_job(
                        self.db.clone(),
                        self.data_dir.clone(),
                        job_id.to_string(),
                    );
                }
            }
        }

        let _ = self.db.patch_video_collect_url(
            job_id,
            aweme_hint,
            &aweme_id,
            page_url,
        );

        if playback_mode == "feed" {
            let _ = lab.prepare_feed_for_swipe().await;
            self.wait_human_if_not_paused(job_id, 800, 1500).await?;
        } else if playback_mode == "video_detail" {
            let _ = lab.prepare_video_detail_for_swipe().await;
            self.wait_human_if_not_paused(job_id, 800, 1500).await?;
        }
        Ok(())
    }

    async fn detail_swipe_next(&self, lab: &LabCommands<'_>) -> Result<serde_json::Value, String> {
        let _ = lab.prepare_video_detail_for_swipe().await;

        match lab.swipe_video_detail_next().await {
            Ok(resp) if playback_navigation_ok(&resp, DouyinPlaybackMode::VideoDetail) => Ok(resp),
            Ok(resp) => {
                warn!(
                    "detail swipe retry — {:?}",
                    resp.get("message").and_then(|v| v.as_str())
                );
                let _ = lab.prepare_video_detail_for_swipe().await;
                simulate::pause(Duration::from_millis(400)).await;
                lab.swipe_video_detail_next().await
            }
            Err(err) => Err(err),
        }
    }

    async fn feed_swipe_next(
        &self,
        lab: &LabCommands<'_>,
        last_aweme: Option<&str>,
    ) -> Result<serde_json::Value, String> {
        let _ = lab.prepare_feed_for_swipe().await;

        match lab.swipe_search_feed_next().await {
            Ok(resp) if feed_navigation_ok(&resp) => return Ok(resp),
            Ok(resp) if resp.get("is_search_feed").and_then(|v| v.as_bool()) == Some(true) => {
                warn!(
                    "feed swipe retry after prepare — {:?}",
                    resp.get("message").and_then(|v| v.as_str())
                );
                let _ = lab.prepare_feed_for_swipe().await;
                simulate::pause(Duration::from_millis(400)).await;
                match lab.swipe_search_feed_next().await {
                    Ok(retry) if feed_navigation_ok(&retry) => return Ok(retry),
                    Ok(retry) => Ok(retry),
                    Err(err) => Err(err),
                }
            }
            Ok(resp) => {
                if let Some(id) = last_aweme.filter(|s| !s.is_empty()) {
                    if let Ok(recovered) = lab.recover_search_feed(id).await {
                        if recovered.get("ok").and_then(|v| v.as_bool()) == Some(true) {
                            info!("feed recovered via modal_id for aweme {id}");
                            return lab.swipe_search_feed_next().await;
                        }
                    }
                }
                Ok(resp)
            }
            Err(err) => {
                if let Some(id) = last_aweme.filter(|s| !s.is_empty()) {
                    if let Ok(recovered) = lab.recover_search_feed(id).await {
                        if recovered.get("ok").and_then(|v| v.as_bool()) == Some(true) {
                            info!("feed recovered after swipe error for aweme {id}");
                            return lab.swipe_search_feed_next().await;
                        }
                    }
                }
                Err(err)
            }
        }
    }

    async fn collect_until_target(
        &self,
        job_id: &str,
        job: &crate::db::CollectJob,
        cfg: &JobConfig,
        keyword_researched: &mut bool,
    ) -> Result<(), String> {
        let mut videos = self.load_videos_for_job(job_id, cfg)?;
        if videos.is_empty() {
            return Err(
                "search produced no videos — ensure Douyin tab is active and logged in".into(),
            );
        }

        let scroll_rounds =
            scroll_rounds_for_video(job.max_comments_per_video, cfg.comment_days);
        let mut pass = 0_u32;
        let mut opened_videos = 0_u32;
        let mut search_feed_chain = false;
        let mut expand_attempts = 0_u32;
        const MAX_EXPAND_ATTEMPTS: u32 = 1;

        let lab = LabCommands::new(&self.hub, &job.platform);
        if cfg.intent == "account_home" {
            let _ = lab.prepare_profile_for_video().await;
            simulate::pause(Duration::from_millis(500)).await;
        }

        while !self.collect_target_reached(job_id, job, cfg)? && pass < 3 {
            self.bail_if_paused(job_id)?;
            if self.is_job_paused(job_id)? {
                return Ok(());
            }
            pass += 1;
            opened_videos = 0;
            for (index, video) in videos.iter().enumerate() {
                self.bail_if_paused(job_id)?;
                if self.collect_target_reached(job_id, job, cfg)? {
                    break;
                }
                if self.video_comments_already_collected(job_id, video)? {
                    info!(
                        "job {job_id}: skip video {}/{} aweme={} — comments already collected",
                        index + 1,
                        videos.len(),
                        video.aweme_id
                    );
                    continue;
                }
                info!(
                    "job {job_id}: video {}/{} aweme={}",
                    index + 1,
                    videos.len(),
                    video.aweme_id
                );
                let is_last = index + 1 >= videos.len();
                match self
                    .open_and_scroll_video(
                        job_id,
                        video,
                        scroll_rounds,
                        cfg,
                        job,
                        index as i64 + 1,
                        &mut search_feed_chain,
                        is_last,
                    )
                    .await
                {
                    Ok(()) => {
                        opened_videos += 1;
                        if self.uses_precise_collect_target() {
                            let _ = self
                                .evaluate_pending_comments(job_id, job, cfg)
                                .await;
                        }
                    }
                    Err(err) if err == JOB_PAUSED => return Ok(()),
                    Err(err) => {
                        search_feed_chain = false;
                        warn!(
                            "job {job_id}: skip video {} ({}) — {}",
                            index + 1,
                            video.aweme_id,
                            err
                        );
                        if cfg.intent == "account_home" {
                            let profile_url = cfg
                                .input_url
                                .clone()
                                .or_else(|| job.input_url.clone());
                            let _ = lab.back_to_profile(profile_url.as_deref()).await;
                        } else {
                            let _ = lab.prepare_search_for_video().await;
                        }
                        simulate::pause(Duration::from_millis(600)).await;
                    }
                }
            }
            if self.collect_target_reached(job_id, job, cfg)? {
                break;
            }
            if opened_videos > 0 {
                let lab = LabCommands::new(&self.hub, &job.platform);
                let _ = lab
                    .scroll_comments(4, job.max_comments_per_video, cfg.comment_days)
                    .await;
                simulate::pause(Duration::from_secs(3)).await;
            } else if cfg.intent == "keyword_auto" && expand_attempts < MAX_EXPAND_ATTEMPTS {
                expand_attempts += 1;
                if self
                    .try_expand_search_videos(
                        job_id,
                        job,
                        cfg,
                        &lab,
                        &mut videos,
                        keyword_researched,
                    )
                    .await?
                {
                    pass = 0;
                    search_feed_chain = false;
                    continue;
                }
            }
        }

        if self.uses_precise_collect_target() {
            let _ = self.evaluate_pending_comments(job_id, job, cfg).await;
        }

        let total = self.db.count_comments_for_job(job_id)?;
        if total == 0 {
            if opened_videos == 0 {
                return Err(if cfg.intent == "account_home" {
                    "failed to open any profile video — keep Douyin tab focused on profile page"
                        .into()
                } else {
                    "failed to open any search result video — keep Douyin tab focused on search results"
                        .into()
                });
            }
            return Err("no comments captured — check login state and filters".into());
        }
        if cfg.collects_by_video_limit() {
            let videos_collected = self.scanned_video_count(job_id)?;
            let pending = videos
                .iter()
                .filter(|v| !self.video_comments_already_collected(job_id, v).unwrap_or(false))
                .count();
            let search_exhausted = pending == 0;
            if self.video_scan_quota_met(job_id, job, search_exhausted)? {
                info!(
                    "job {job_id}: video-limit collect done — {videos_collected}/{} videos ({} comments, exhausted={search_exhausted})",
                    job.limit_videos, total
                );
                return Ok(());
            }
            info!(
                "job {job_id}: video-limit collect done — {videos_collected}/{} videos ({} comments)",
                job.limit_videos, total
            );
            return Ok(());
        }
        let progress = self.collect_progress_count(job_id)?;
        if progress < cfg.target_count {
            let pending = videos
                .iter()
                .filter(|v| !self.video_comments_already_collected(job_id, v).unwrap_or(false))
                .count();
            let label = self.collect_progress_label();
            let detail = if opened_videos == 0 && pending > 0 {
                "未能打开待采集视频，请确认抖音在搜索结果页后点击继续采集".to_string()
            } else if pending == 0 {
                format!(
                    "当前视频列表已全部采集，共 {total} 条评论，仍缺 {} 条{label}",
                    cfg.target_count - progress
                )
            } else {
                "部分视频采集失败，可点击继续采集重试".to_string()
            };
            return Err(format!(
                "仅识别到 {progress}/{} 条{label}（共采集 {total} 条评论） — {detail}",
                cfg.target_count
            ));
        }
        info!(
            "job {job_id}: {} {progress}/{} (total comments {total})",
            self.collect_progress_label(),
            cfg.target_count,
        );
        Ok(())
    }

    fn uses_precise_collect_target(&self) -> bool {
        crate::llm_client::LlmClient::from_data_dir(&self.data_dir).is_some()
    }

    fn collect_progress_label(&self) -> &'static str {
        if self.uses_precise_collect_target() {
            "精准线索"
        } else {
            "评论"
        }
    }

    fn collect_progress_count(&self, job_id: &str) -> Result<i64, String> {
        if self.uses_precise_collect_target() {
            self.db.count_precise_comments_for_job(job_id)
        } else {
            self.db.count_comments_for_job(job_id)
        }
    }

    fn scanned_video_count(&self, job_id: &str) -> Result<i64, String> {
        let video_count = self.db.list_videos_for_job(job_id)?.len() as i64;
        let with_comments = self.db.count_distinct_comment_awemes_for_job(job_id)?;
        Ok(video_count.max(with_comments))
    }

    /// 关键词视频上限任务：已扫够上限，或当前可见视频已全部扫完。
    fn video_scan_quota_met(
        &self,
        job_id: &str,
        job: &crate::db::CollectJob,
        search_exhausted: bool,
    ) -> Result<bool, String> {
        let scanned = self.scanned_video_count(job_id)?;
        let limit = job.limit_videos.max(1);
        if scanned >= limit {
            return Ok(true);
        }
        Ok(search_exhausted && scanned > 0)
    }

    fn collect_target_reached(
        &self,
        job_id: &str,
        job: &crate::db::CollectJob,
        cfg: &JobConfig,
    ) -> Result<bool, String> {
        Ok(self.videos_remaining_quota(job_id, job, cfg)? == 0)
    }

    fn videos_remaining_quota(
        &self,
        job_id: &str,
        job: &crate::db::CollectJob,
        cfg: &JobConfig,
    ) -> Result<u32, String> {
        if cfg.collects_by_video_limit() {
            let collected = self.scanned_video_count(job_id)?;
            let limit = job.limit_videos.max(1) as u32;
            return Ok(limit.saturating_sub(collected as u32));
        }
        let progress = self.collect_progress_count(job_id)?;
        let target = cfg.target_count.max(1) as u32;
        Ok(target.saturating_sub(progress as u32))
    }

    async fn open_or_adopt_playback(
        &self,
        lab: &LabCommands<'_>,
        feed_source: &DouyinFeedSource,
    ) -> Result<serde_json::Value, String> {
        if let Ok(probe) = lab.probe_current_playback().await {
            if video_ready_for_collect(&probe) {
                let aweme = feed_aweme_from_response(&probe).unwrap_or_default();
                info!(
                    "adopt current playback page — aweme={aweme} standalone={} feed={}",
                    response_is_standalone_video(&probe),
                    probe.get("is_search_feed").and_then(|v| v.as_bool()).unwrap_or(false)
                );
                return Ok(probe);
            }
        }

        match feed_source {
            DouyinFeedSource::KeywordSearch => lab.click_search_video_fresh(1).await,
            DouyinFeedSource::ProfileHome { profile_url } => {
                let _ = lab.open_url(profile_url).await;
                simulate::pause(Duration::from_millis(800)).await;
                lab.click_profile_video_fresh(1).await
            }
        }
    }

    async fn evaluate_pending_comments(
        &self,
        job_id: &str,
        job: &crate::db::CollectJob,
        cfg: &JobConfig,
    ) -> Result<(), String> {
        if !self.uses_precise_collect_target() {
            return Ok(());
        }
        let _ = crate::evaluation::evaluate_job_comments(
            &self.db,
            &self.data_dir,
            job_id,
            &job.keyword,
            &cfg.evaluation,
        )
        .await;
        Ok(())
    }

    async fn ensure_search_videos_captured(
        &self,
        job_id: &str,
        platform: &str,
        lab: &LabCommands<'_>,
        search_resp: Option<&serde_json::Value>,
        limit_videos: i64,
    ) -> Result<(), String> {
        let target = limit_videos.clamp(1, 20) as usize;
        let fetch_limit = (limit_videos + 5).clamp(1, 50);
        let cached = self.parsed_videos_from_db(job_id)?;

        let mut videos = search_resp
            .map(|resp| parse_plugin_lab_search_results(platform, resp))
            .unwrap_or_default();
        let mut source = if !videos.is_empty() {
            "step7"
        } else if !cached.is_empty() && search_resp.is_none() {
            info!(
                "job {job_id}: resume with {} cached search videos, refresh list from page",
                cached.len()
            );
            videos = cached.clone();
            "cached+refresh"
        } else {
            "step8"
        };

        if videos.is_empty() || search_resp.is_none() {
            if videos.is_empty() {
                info!("job {job_id}: step 7 had no items, falling back to fetch_search_results (lab step 8)");
            }
            let mut last_resp = serde_json::Value::Null;
            for attempt in 1..=2u32 {
                self.bail_if_paused(job_id)?;
                let resp = lab.fetch_search_results(fetch_limit).await?;
                last_resp = resp.clone();
                let fetched = parse_plugin_lab_search_results(platform, &resp);
                videos = merge_parsed_videos(videos, fetched);
                if !videos.is_empty() {
                    if attempt > 1 {
                        warn!("job {job_id}: fetch_search_results succeeded on attempt {attempt}");
                    }
                    break;
                }
                if attempt < 2 {
                    warn!("job {job_id}: fetch_search_results empty, scroll once and retry");
                    let _ = lab.swipe_search_results(1).await;
                    self.wait_if_not_paused(job_id, Duration::from_millis(1200))
                        .await?;
                    let resp = lab
                        .fetch_search_results_after_scroll(fetch_limit, videos.len())
                        .await?;
                    last_resp = resp.clone();
                    let fetched = parse_plugin_lab_search_results(platform, &resp);
                    videos = merge_parsed_videos(videos, fetched);
                    if !videos.is_empty() {
                        warn!("job {job_id}: fetch_search_results succeeded on attempt {attempt}");
                        break;
                    }
                    continue;
                }
            }
            if videos.is_empty() && !last_resp.is_null() {
                if let Some(msg) = last_resp.get("message").and_then(|v| v.as_str()) {
                    warn!("job {job_id}: fetch_search_results message: {msg}");
                }
            }
            if source == "step7" {
                source = "step7+step8";
            } else if source != "cached+refresh" {
                source = "step8";
            }
        }

        if videos.is_empty() {
            if !cached.is_empty() {
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

        if videos.len() < target {
            let added = self
                .paginate_search_videos(job_id, platform, lab, &mut videos, target, fetch_limit)
                .await?;
            if added > 0 {
                source = "step7+scroll";
            }
        }

        let inserted = self.db.replace_videos_for_job(job_id, &videos)?;
        info!(
            "job {job_id}: stored {inserted} search videos from {source} (dom_poster={}, target={target})",
            videos.iter().filter(|v| is_dom_poster_aweme_id(&v.aweme_id)).count()
        );
        Ok(())
    }

    fn parsed_videos_from_db(&self, job_id: &str) -> Result<Vec<ParsedVideo>, String> {
        Ok(self
            .db
            .list_videos_for_job(job_id)?
            .into_iter()
            .map(|video| ParsedVideo {
                aweme_id: video.aweme_id,
                video_url: video.video_url,
                title: video.title,
                author: video.author,
                raw_json: video.raw_json,
            })
            .collect())
    }

    /// 搜索列表不足 limit_videos 时向下滚动加载更多，合并去重直到达标或无新条目。
    async fn paginate_search_videos(
        &self,
        job_id: &str,
        platform: &str,
        lab: &LabCommands<'_>,
        videos: &mut Vec<ParsedVideo>,
        target: usize,
        fetch_limit: i64,
    ) -> Result<usize, String> {
        const MAX_PAGES: u32 = 6;
        let initial = videos.len();
        let mut page = 0_u32;

        while videos.len() < target && page < MAX_PAGES {
            self.bail_if_paused(job_id)?;
            page += 1;
            let before = videos.len();
            info!(
                "job {job_id}: search list {before}/{target} videos — scrolling page {page}/{MAX_PAGES}"
            );

            if page == 1 {
                let _ = lab.scroll_search_list_to_top().await;
            }
            let _ = lab.swipe_search_results(3).await;
            self.wait_if_not_paused(job_id, Duration::from_millis(2200))
                .await?;
            let _ = lab.enable_network_hook().await;
            self.wait_if_not_paused(job_id, Duration::from_millis(800))
                .await?;

            let resp = lab
                .fetch_search_results_after_scroll(fetch_limit, before)
                .await?;
            let batch = parse_plugin_lab_search_results(platform, &resp);
            if batch.is_empty() {
                warn!("job {job_id}: search page {page} returned no parsable videos");
                break;
            }
            *videos = merge_parsed_videos(std::mem::take(videos), batch);
            if videos.len() == before {
                warn!("job {job_id}: search page {page} added no new videos, stop paginating");
                break;
            }
            info!(
                "job {job_id}: search list grew {before} → {} (target {target})",
                videos.len()
            );
        }

        if videos.len() > initial {
            let _ = lab.scroll_search_list_to_top().await;
        }

        Ok(videos.len().saturating_sub(initial))
    }

    /// 当前列表视频均已采集时，滚动搜索页加载更多条目。
    async fn try_expand_search_videos(
        &self,
        job_id: &str,
        job: &crate::db::CollectJob,
        cfg: &JobConfig,
        lab: &LabCommands<'_>,
        videos: &mut Vec<CapturedVideo>,
        keyword_researched: &mut bool,
    ) -> Result<bool, String> {
        let pending = videos
            .iter()
            .filter(|v| !self.video_comments_already_collected(job_id, v).unwrap_or(false))
            .count();
        if pending > 0 {
            return Ok(false);
        }

        let before = videos.len();
        info!(
            "job {job_id}: all {before} search videos already collected — scrolling for more"
        );
        let target = (before + 1).max(job.limit_videos.clamp(1, 20) as usize);
        let fetch_limit = (job.limit_videos + 5).clamp(1, 50);
        let mut parsed = self.parsed_videos_from_db(job_id)?;
        let added = self
            .paginate_search_videos(job_id, &job.platform, lab, &mut parsed, target, fetch_limit)
            .await?;
        if added == 0 {
            if *keyword_researched {
                info!(
                    "job {job_id}: scroll pagination added no videos and keyword search already ran this session — skip re-search"
                );
                return Ok(false);
            }
            let search_kw = cfg.search_keyword(&job.keyword);
            info!(
                "job {job_id}: scroll pagination added no videos, one-time keyword re-search ({search_kw})"
            );
            *keyword_researched = true;
            if let Ok(search_resp) = lab
                .run_keyword_search(&search_kw, cfg.filter_publish_days_for_ui(), true)
                .await
            {
                let fetched = parse_plugin_lab_search_results(&job.platform, &search_resp);
                let merged = merge_parsed_videos(parsed, fetched);
                if merged.len() > before {
                    self.db.replace_videos_for_job(job_id, &merged)?;
                    *videos = self.load_videos_for_job(job_id, cfg)?;
                    info!(
                        "job {job_id}: keyword re-search expanded list {before} → {} videos",
                        videos.len()
                    );
                    return Ok(true);
                }
                info!(
                    "job {job_id}: keyword re-search returned no new videos ({before} → {})",
                    merged.len()
                );
            }
            return Ok(false);
        }
        self.db.replace_videos_for_job(job_id, &parsed)?;
        *videos = self.load_videos_for_job(job_id, cfg)?;
        info!(
            "job {job_id}: expanded search list {before} → {} videos (+{added})",
            videos.len()
        );
        Ok(true)
    }

    fn count_pending_videos(&self, job_id: &str, cfg: &JobConfig) -> Result<usize, String> {
        let videos = self.load_videos_for_job(job_id, cfg)?;
        Ok(videos
            .iter()
            .filter(|v| !self.video_comments_already_collected(job_id, v).unwrap_or(false))
            .count())
    }

    fn load_videos_for_job(
        &self,
        job_id: &str,
        cfg: &JobConfig,
    ) -> Result<Vec<CapturedVideo>, String> {
        let mut videos = self.db.list_videos_for_job(job_id)?;
        let raw_count = videos.len();
        // 关键词任务已将 region 拼入搜索词；主页/单视频手动任务不按地域过滤视频标题。
        if cfg.intent != "keyword_auto" && cfg.intent != "account_home" && cfg.intent != "single_video" {
            videos = filters::filter_videos_by_region(videos, cfg.region_name.as_deref());
        }
        if videos.is_empty() {
            if raw_count > 0 {
                return Err(format!(
                    "captured {raw_count} videos but none matched region {:?} — try clearing region",
                    cfg.region_name
                ));
            }
            let hint = if cfg.intent == "account_home" {
                "profile produced no videos — ensure profile page is open and video grid is visible"
            } else if cfg.intent == "single_video" {
                "single video job has no video record — check input_url"
            } else {
                "search produced no videos — ensure Douyin is logged in and search results are visible"
            };
            return Err(hint.into());
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

    fn video_comments_already_collected(
        &self,
        job_id: &str,
        video: &CapturedVideo,
    ) -> Result<bool, String> {
        if self.db.count_comments_for_aweme(job_id, &video.aweme_id)? > 0 {
            return Ok(true);
        }
        let stored_url = self
            .db
            .get_video_url_for_job(job_id, &video.aweme_id)
            .unwrap_or_default();
        let video_url = if stored_url.trim().is_empty() {
            video.video_url.as_str()
        } else {
            stored_url.as_str()
        };
        if let Some(real_id) = parse_aweme_id_from_page_url(video_url) {
            if self.db.count_comments_for_aweme(job_id, &real_id)? > 0 {
                return Ok(true);
            }
        }
        if is_dom_poster_aweme_id(&video.aweme_id) {
            if let Some(idx) = dom_poster_index(&video.aweme_id) {
                let distinct = self.db.count_distinct_comment_awemes_for_job(job_id)?;
                if distinct >= idx as i64 {
                    return Ok(true);
                }
            }
        }
        Ok(false)
    }

    async fn try_jump_search_feed_video(
        &self,
        job_id: &str,
        lab: &LabCommands<'_>,
        video_index: i64,
        aweme_hint: Option<&str>,
    ) -> bool {
        let Some(aweme_id) = aweme_hint.filter(|id| !is_dom_poster_aweme_id(id)) else {
            return false;
        };
        match lab.jump_search_feed_video(video_index, aweme_id).await {
            Ok(clicked) if video_ready_for_collect(&clicked) => {
                info!(
                    "job {job_id}: feed modal jump to aweme={aweme_id} mode={:?}",
                    clicked.get("mode").and_then(|v| v.as_str())
                );
                true
            }
            Ok(clicked) => {
                warn!(
                    "job {job_id}: feed modal jump failed for {aweme_id} — {:?}",
                    clicked.get("message").and_then(|v| v.as_str())
                );
                false
            }
            Err(err) => {
                warn!("job {job_id}: feed modal jump error for {aweme_id} — {err}");
                false
            }
        }
    }

    async fn open_and_scroll_video(
        &self,
        job_id: &str,
        video: &CapturedVideo,
        scroll_rounds: i64,
        cfg: &JobConfig,
        job: &crate::db::CollectJob,
        video_index: i64,
        search_feed_chain: &mut bool,
        is_last: bool,
    ) -> Result<(), String> {
        self.bail_if_paused(job_id)?;
        let lab = LabCommands::new(&self.hub, &job.platform);
        if cfg.intent == "account_home" {
            let aweme_hint = if is_dom_poster_aweme_id(&video.aweme_id) {
                parse_aweme_id_from_page_url(&video.video_url)
            } else {
                Some(video.aweme_id.clone())
            };
            let clicked = lab
                .click_profile_video(
                    video_index,
                    aweme_hint
                        .as_deref()
                        .filter(|id| !is_dom_poster_aweme_id(id)),
                )
                .await?;
            let ok = clicked.get("ok").and_then(|v| v.as_bool()).unwrap_or(false);
            let feed_open = clicked
                .get("feed_open")
                .and_then(|v| v.as_bool())
                .unwrap_or(false);
            if !ok || !feed_open {
                let msg = clicked
                    .get("message")
                    .and_then(|v| v.as_str())
                    .unwrap_or("profile video feed did not open after click");
                return Err(msg.to_string());
            }
            info!(
                "job {job_id}: opened profile video #{video_index} mode={:?}",
                clicked.get("mode").and_then(|v| v.as_str())
            );
        } else if cfg.intent == "keyword_auto" || is_dom_poster_aweme_id(&video.aweme_id) {
            let index = if is_dom_poster_aweme_id(&video.aweme_id) {
                dom_poster_index(&video.aweme_id).unwrap_or(video_index)
            } else {
                video_index
            };
            let aweme_hint = if is_dom_poster_aweme_id(&video.aweme_id) {
                parse_aweme_id_from_page_url(&video.video_url)
            } else {
                Some(video.aweme_id.clone())
            };
            let video_url = (!video.video_url.is_empty()).then_some(video.video_url.as_str());
            let rect = if is_dom_poster_aweme_id(&video.aweme_id) {
                dom_poster_click_payload(video.raw_json.as_deref())
                    .get("rect")
                    .cloned()
            } else {
                None
            };

            let mut opened_via_feed_swipe = false;
            if *search_feed_chain && job.platform == "douyin" && cfg.intent == "keyword_auto" {
                match lab.swipe_search_feed_next().await {
                    Ok(resp) if resp.get("ok").and_then(|v| v.as_bool()) == Some(true) => {
                        opened_via_feed_swipe = true;
                        info!(
                            "job {job_id}: feed swipe to next video aweme={:?} method={:?}",
                            resp.get("aweme_id").and_then(|v| v.as_str()),
                            resp.get("method").and_then(|v| v.as_str())
                        );
                    }
                    Ok(resp) => {
                        warn!(
                            "job {job_id}: feed swipe failed — {:?}",
                            resp.get("message").and_then(|v| v.as_str())
                        );
                        opened_via_feed_swipe = self
                            .try_jump_search_feed_video(
                                job_id,
                                &lab,
                                index,
                                aweme_hint.as_deref(),
                            )
                            .await;
                        if !opened_via_feed_swipe {
                            *search_feed_chain = false;
                            let _ = lab.close_video_detail().await;
                            let _ = lab.prepare_search_for_video().await;
                        }
                    }
                    Err(err) => {
                        warn!("job {job_id}: feed swipe error — {err}");
                        opened_via_feed_swipe = self
                            .try_jump_search_feed_video(
                                job_id,
                                &lab,
                                index,
                                aweme_hint.as_deref(),
                            )
                            .await;
                        if !opened_via_feed_swipe {
                            *search_feed_chain = false;
                            let _ = lab.close_video_detail().await;
                            let _ = lab.prepare_search_for_video().await;
                        }
                    }
                }
            }

            if !opened_via_feed_swipe {
                let clicked = lab
                    .click_search_video(index, rect, aweme_hint.as_deref(), video_url)
                    .await?;
                let ready = video_ready_for_collect(&clicked);
                if !ready {
                    let msg = clicked
                        .get("message")
                        .and_then(|v| v.as_str())
                        .unwrap_or("failed to open video for comment collection");
                    *search_feed_chain = false;
                    return Err(msg.to_string());
                }
                *search_feed_chain = clicked
                    .get("is_search_feed")
                    .and_then(|v| v.as_bool())
                    .unwrap_or(false)
                    && job.platform == "douyin"
                    && cfg.intent == "keyword_auto";
                info!(
                    "job {job_id}: opened video #{index} mode={:?} feed={} detail_window={} feed_chain={}",
                    clicked.get("mode").and_then(|v| v.as_str()),
                    clicked.get("is_search_feed").and_then(|v| v.as_bool()).unwrap_or(false),
                    clicked.get("detail_window").and_then(|v| v.as_bool()).unwrap_or(false),
                    *search_feed_chain,
                );
            }
        } else {
            // 优先用 DB 中的 video_url 直达详情，避免依赖搜索结果页 DOM 索引
            lab.open_video(
                &video.aweme_id,
                (!video.video_url.is_empty()).then_some(video.video_url.as_str()),
            )
            .await?;
        }
        self.wait_human_if_not_paused(job_id, 5500, 8500).await?;

        info!("job {job_id}: opening comment sidebar for aweme={}", video.aweme_id);
        let mut sidebar_ok = false;
        for attempt in 1..=3 {
            self.bail_if_paused(job_id)?;
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
            self.wait_human_if_not_paused(job_id, 1200, 2200).await?;
        }
        if !sidebar_ok {
            return Err("failed to open comment sidebar after 3 attempts".into());
        }
        self.wait_human_if_not_paused(job_id, 1500, 2800).await?;

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
        let scroll_comments = parse_dom_scroll_comments(&scroll_resp);
        let capture_method = scroll_resp
            .get("capture_method")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let api_cached = scroll_resp
            .get("api_count")
            .and_then(|v| v.as_i64())
            .unwrap_or(0);
        let existing_for_aweme = self.db.count_comments_for_aweme(job_id, &aweme_id).unwrap_or(0);
        let persistable: Vec<_> = scroll_comments
            .into_iter()
            .filter(|c| capture_method == "dom" || !c.comment_id.starts_with("dom_"))
            .collect();

        if existing_for_aweme > 0 && persistable.is_empty() {
            info!(
                "job {job_id}: skip upsert for aweme {aweme_id} — {existing_for_aweme} comments already stored (capture={capture_method}, api_count={api_cached})"
            );
        } else if !persistable.is_empty() {
            let inserted = self.db.upsert_comments(job_id, &aweme_id, &persistable)?;
            info!(
                "job {job_id}: stored {inserted} comments for aweme {aweme_id} via {capture_method} (stopped={:?})",
                scroll_resp.get("stopped_reason").and_then(|v| v.as_str())
            );
            if inserted > 0 {
                if self.uses_precise_collect_target() {
                    let _ = crate::evaluation::evaluate_job_comments(
                        &self.db,
                        &self.data_dir,
                        job_id,
                        &job.keyword,
                        &cfg.evaluation,
                    )
                    .await;
                } else {
                    crate::evaluation::spawn_evaluate_job(
                        self.db.clone(),
                        self.data_dir.clone(),
                        job_id.to_string(),
                    );
                }
            }
        } else if existing_for_aweme == 0 && api_cached == 0 {
            warn!(
                "job {job_id}: scroll returned 0 persistable comments for aweme {} — {:?}",
                aweme_id,
                scroll_resp.get("message").and_then(|v| v.as_str())
            );
        }

        if existing_for_aweme > 0 || !persistable.is_empty() {
            let _ = self.db.patch_video_collect_url(
                job_id,
                &video.aweme_id,
                &aweme_id,
                page_url,
            );
        }

        self.wait_human_if_not_paused(job_id, 2500, 4500).await?;
        if cfg.intent == "account_home" {
            let closed = lab.close_video_detail().await?;
            if !closed.get("ok").and_then(|v| v.as_bool()).unwrap_or(true) {
                warn!(
                    "job {job_id}: close_video_detail may have failed — {:?}",
                    closed.get("message").and_then(|v| v.as_str())
                );
            }
            let profile_url = cfg
                .input_url
                .clone()
                .or_else(|| job.input_url.clone());
            let _ = lab.back_to_profile(profile_url.as_deref()).await;
            self.wait_human_if_not_paused(job_id, 1200, 2200).await?;
        } else if cfg.intent != "account_home" {
            if *search_feed_chain && !is_last {
                info!(
                    "job {job_id}: keep search feed open for next video (skip close/prepare)"
                );
            } else {
                let closed = lab.close_video_detail().await?;
                let detail_window_closed = closed
                    .get("detail_window_closed")
                    .and_then(|v| v.as_bool())
                    .unwrap_or(false);
                if !detail_window_closed {
                    let _ = lab.prepare_search_for_video().await;
                }
                *search_feed_chain = false;
            }
            self.wait_human_if_not_paused(job_id, 1200, 2200).await?;
        }
        Ok(())
    }

    fn bail_if_paused(&self, job_id: &str) -> Result<(), String> {
        if !self.job_runs.is_current(job_id, self.generation) {
            return Err(JOB_PAUSED.into());
        }
        if self.is_job_paused(job_id)? {
            return Err(JOB_PAUSED.into());
        }
        Ok(())
    }

    async fn wait_if_not_paused(&self, job_id: &str, duration: Duration) -> Result<(), String> {
        let step = Duration::from_millis(400);
        let mut remaining = duration;
        while remaining > Duration::ZERO {
            if !self.job_runs.is_current(job_id, self.generation) || self.is_job_paused(job_id)? {
                return Err(JOB_PAUSED.into());
            }
            let chunk = remaining.min(step);
            simulate::pause(chunk).await;
            remaining = remaining.saturating_sub(chunk);
        }
        Ok(())
    }

    async fn wait_human_if_not_paused(
        &self,
        job_id: &str,
        min_ms: u64,
        max_ms: u64,
    ) -> Result<(), String> {
        use rand::Rng;
        let ms = rand::thread_rng().gen_range(min_ms..=max_ms);
        self.wait_if_not_paused(job_id, Duration::from_millis(ms)).await
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


pub fn spawn_job(
    db: Database,
    hub: BridgeHub,
    default_daily_quota: i64,
    job_runs: JobRunRegistry,
    data_dir: std::path::PathBuf,
    job_id: String,
    generation: u64,
) {
    let orchestrator = Arc::new(JobOrchestrator {
        db,
        hub,
        default_daily_quota,
        job_runs,
        generation,
        data_dir,
    });
    tokio::spawn(async move {
        if let Err(err) = orchestrator.run_job(&job_id).await {
            if err != JOB_PAUSED {
                tracing::error!("job {job_id} failed: {err}");
            }
        }
    });
}
