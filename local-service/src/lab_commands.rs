use std::time::Duration;

use serde_json::{json, Value};

use tracing::{info, warn};

use crate::db::Database;
use crate::job_run_log::{log_bridge_command, log_lab_action};
use crate::platforms::PlatformCollectAdapter;
use crate::plugin_lab;
use crate::simulate;
use crate::ws::BridgeHub;

/// 任务编排统一走插件实验室已验证步骤（`plugin_lab.*`），不再调用 legacy `douyin.*` UI 命令。
pub struct LabCommands<'a> {
    hub: &'a BridgeHub,
    platform: String,
    run_log: Option<(Database, String, u64)>,
}

impl<'a> LabCommands<'a> {
    pub fn new(hub: &'a BridgeHub, platform: &str) -> Self {
        Self {
            hub,
            platform: crate::platforms::normalize_platform(platform).to_string(),
            run_log: None,
        }
    }

    pub fn with_run_log(mut self, db: Database, job_id: impl Into<String>, run_id: u64) -> Self {
        self.run_log = Some((db, job_id.into(), run_id));
        self
    }

    fn adapter(&self) -> &'static dyn PlatformCollectAdapter {
        crate::platforms::get_platform_adapter(&self.platform)
    }

    /// 打开浏览器后、开始采集前：reload 插件以确保 content script 就绪，并重新聚焦工作窗。
    pub async fn reload_extension_after_browser_open(&self) -> Result<(), String> {
        if self.hub.extension_client_count() == 0 {
            return Err(
                "no extension connected — load extension/dist before starting collect".into(),
            );
        }

        info!(
            "reload extension after browser open (platform={})",
            self.platform
        );

        match self
            .request_bridge(
                "huoke.extension.reload",
                json!({}),
                Duration::from_secs(10),
            )
            .await
        {
            Ok(_) => info!("extension reload acknowledged"),
            Err(err) => {
                warn!("extension reload command ended: {err} — waiting for reconnect…");
            }
        }

        self.hub
            .wait_for_extension_reconnect(Duration::from_secs(25))
            .await?;
        simulate::pause(Duration::from_secs(2)).await;

        let platform = self.platform.clone();
        match self
            .action(
                "open_browser",
                json!({
                    "platform": platform,
                    "reuse_existing": true,
                    "reset_to_start": false,
                    "wait_load": true,
                }),
            )
            .await
        {
            Ok(_) => {}
            Err(err) => warn!("refocus browser after reload failed: {err}"),
        }
        simulate::pause(Duration::from_millis(800)).await;
        Ok(())
    }

    pub async fn enable_network_hook(&self) -> Result<(), String> {
        const MAX_ATTEMPTS: u32 = 3;
        let patterns: Vec<&str> = self.adapter().network_hook_patterns().to_vec();
        let mut last_err = String::new();
        for attempt in 1..=MAX_ATTEMPTS {
            match self
                .request_bridge(
                    "network.hook.enable",
                    json!({ "patterns": patterns, "platform": self.platform }),
                    Duration::from_secs(45),
                )
                .await
            {
                Ok(_) => return Ok(()),
                Err(err) => {
                    last_err = err;
                    if attempt < MAX_ATTEMPTS {
                        warn!("network.hook.enable attempt {attempt} failed: {last_err}, retrying…");
                        simulate::pause(Duration::from_millis(2500)).await;
                    }
                }
            }
        }
        Err(last_err)
    }

    pub async fn run_keyword_search(
        &self,
        keyword: &str,
        publish_days: i64,
        fetch_results: bool,
    ) -> Result<Value, String> {
        let platform = self.platform.clone();
        // 清理上次任务遗留的独立窗 / Feed 浮层 / 工作窗 /video/ 页，避免无法输入搜索
        let _ = self.close_video_detail().await;
        simulate::pause(Duration::from_millis(600)).await;

        // 1 打开 → 3~7 搜索 →（可选）4~5 筛选 → 8 抓结果（有筛选时先筛后抓）
        const MAX_OPEN_ATTEMPTS: u32 = 3;
        let mut open_err = String::new();
        for attempt in 1..=MAX_OPEN_ATTEMPTS {
            match self
                .action(
                    "open_browser",
                    json!({
                        "platform": platform,
                        "reuse_existing": true,
                        "reset_to_start": true,
                    }),
                )
                .await
            {
                Ok(_) => {
                    open_err.clear();
                    break;
                }
                Err(err) => {
                    open_err = err;
                    if attempt < MAX_OPEN_ATTEMPTS {
                        warn!("open_browser attempt {attempt} failed: {open_err}, retrying…");
                        simulate::pause(Duration::from_secs(3)).await;
                    }
                }
            }
        }
        if !open_err.is_empty() {
            return Err(open_err);
        }
        self.reload_extension_after_browser_open().await?;

        const MAX_SEARCH_ATTEMPTS: u32 = 4;
        let mut last_err = String::new();
        let mut search_ready = false;
        for attempt in 1..=MAX_SEARCH_ATTEMPTS {
            match self
                .action("find_search_box", json!({ "platform": platform }))
                .await
            {
                Ok(result) if Self::search_box_ready(&result) => {
                    if attempt > 1 {
                        warn!("find_search_box succeeded on attempt {attempt}");
                    }
                    search_ready = true;
                    break;
                }
                Ok(result) => {
                    last_err = result
                        .get("message")
                        .and_then(|v| v.as_str())
                        .unwrap_or("search box not found")
                        .to_string();
                }
                Err(err) => {
                    last_err = err;
                }
            }
            if attempt < MAX_SEARCH_ATTEMPTS {
                warn!("find_search_box attempt {attempt} failed: {last_err}, retrying…");
                simulate::pause(Duration::from_secs(4)).await;
            }
        }
        if !search_ready {
            return Err(if last_err.is_empty() {
                "search box not found".into()
            } else {
                last_err
            });
        }

        self.action(
            "input_search_text",
            json!({
                "platform": platform,
                "search_text": keyword,
                "char_delay_ms": { "min": 60, "max": 140 },
            }),
        )
        .await?;

        simulate::pause(Duration::from_millis(400)).await;

        // hook 必须在点击搜索之前开启，否则首屏 search API 抓不到
        self.enable_network_hook().await?;

        let submit = self
            .action(
                "click_search_btn",
                json!({ "platform": platform, "search_text": keyword }),
            )
            .await?;
        if !Self::lab_ok(&submit) && Self::search_result_count(&submit) == 0 {
            return Ok(submit);
        }

        if platform == "douyin" {
            match self.action("ensure_search_multi_column", json!({})).await {
                Ok(resp) if resp.get("ok").and_then(|v| v.as_bool()) == Some(true) => {}
                Ok(resp) => {
                    warn!(
                        "ensure_search_multi_column: {:?}",
                        resp.get("message").and_then(|v| v.as_str())
                    );
                }
                Err(err) => warn!("ensure_search_multi_column failed: {err}"),
            }
            simulate::pause(Duration::from_millis(if fetch_results { 800 } else { 300 })).await;
        }

        // Feed 模式刚提交搜索，列表通常 1~2s 内就绪；列表模式仍多等一会
        simulate::pause(if fetch_results {
            Duration::from_secs(5)
        } else {
            Duration::from_millis(1200)
        })
        .await;

        if publish_days > 0 {
            if let Err(e) = self.action("click_filter_btn", json!({})).await {
                warn!("click_filter_btn failed: {e}");
            }
            simulate::pause(Duration::from_millis(500)).await;
            if let Err(e) = self
                .action(
                    "click_filter_overlay",
                    json!({ "days": publish_days, "open_if_closed": true }),
                )
                .await
            {
                warn!("click_filter_overlay failed: {e}");
            }
            simulate::pause(if fetch_results {
                Duration::from_secs(2)
            } else {
                Duration::from_millis(800)
            })
            .await;
        }

        // 列表抓取模式：筛选后需重新 hook；Feed 模式搜索前已 hook，直接进播放页
        if fetch_results {
            self.enable_network_hook().await?;
            simulate::pause(Duration::from_millis(800)).await;

            if platform == "douyin" {
                let _ = self.action("ensure_search_multi_column", json!({})).await;
                simulate::pause(Duration::from_millis(400)).await;
            }
        }

        if !fetch_results {
            return Ok(json!({
                "ok": true,
                "message": "search submitted, skip fetch (feed collect mode)",
            }));
        }

        let search_payload = match self
            .action(
                "fetch_search_results",
                json!({ "limit": 30, "api_timeout_ms": 12_000 }),
            )
            .await
        {
            Ok(fetch) if Self::search_result_count(&fetch) > 0 => fetch,
            Ok(_) | Err(_) => submit,
        };

        Ok(search_payload)
    }

    /// 探测当前是否在搜索 Feed 浮层，并读取 aweme_id
    pub async fn probe_search_feed(&self) -> Result<Value, String> {
        self.action(
            "search_video_probe",
            json!({ "platform": self.platform, "status_only": true }),
        )
        .await
    }

    /// 继续采集：关闭 Feed/详情，聚焦已有标签页并回到搜索结果，不重新输入关键词。
    pub async fn prepare_keyword_collect_resume(&self) -> Result<(), String> {
        let platform = self.platform.clone();
        let _ = self.close_video_detail().await;
        simulate::pause(Duration::from_millis(600)).await;

        self.action(
            "open_browser",
            json!({
                "platform": platform,
                "reuse_existing": true,
                "reset_to_start": false,
            }),
        )
        .await?;
        simulate::pause(Duration::from_secs(2)).await;

        self.enable_network_hook().await?;
        simulate::pause(Duration::from_millis(800)).await;

        let _ = self.scroll_search_list_to_top().await;
        simulate::pause(Duration::from_millis(800)).await;
        Ok(())
    }

    pub async fn close_video_detail(&self) -> Result<Value, String> {
        self.action("close_video_detail", json!({})).await
    }

    pub async fn close_browser(&self) -> Result<Value, String> {
        self.action(
            "close_browser",
            json!({ "platform": self.platform }),
        )
        .await
    }

    pub async fn prepare_search_for_video(&self) -> Result<Value, String> {
        self.action(
            "prepare_search_for_video",
            json!({ "platform": self.platform }),
        )
        .await
    }

    /// 仅在当前搜索结果页滚到列表顶部，不跳转、不重新输入关键词。
    pub async fn scroll_search_list_to_top(&self) -> Result<Value, String> {
        self.action(
            "prepare_search_for_video",
            json!({ "platform": self.platform, "skip_restore": true }),
        )
        .await
    }

    /// 搜索 Feed 浮层内切换到下一个视频（抖音关键词任务链式浏览）
    pub async fn swipe_search_feed_next(&self) -> Result<Value, String> {
        self.action(
            "swipe_search_feed_next",
            json!({ "platform": self.platform }),
        )
        .await
    }

    pub async fn swipe_video_detail_next(&self) -> Result<Value, String> {
        self.action(
            "swipe_video_detail_next",
            json!({ "platform": self.platform }),
        )
        .await
    }

    pub async fn prepare_feed_for_swipe(&self) -> Result<Value, String> {
        self.action(
            "prepare_feed_for_swipe",
            json!({ "platform": self.platform }),
        )
        .await
    }

    pub async fn prepare_video_detail_for_swipe(&self) -> Result<Value, String> {
        self.action(
            "prepare_video_detail_for_swipe",
            json!({ "platform": self.platform }),
        )
        .await
    }

    pub async fn recover_search_feed(&self, aweme_id: &str) -> Result<Value, String> {
        self.action(
            "recover_search_feed",
            json!({ "platform": self.platform, "aweme_id": aweme_id }),
        )
        .await
    }

    pub async fn click_search_video(
        &self,
        video_index: i64,
        rect: Option<Value>,
        aweme_id: Option<&str>,
        video_url: Option<&str>,
    ) -> Result<Value, String> {
        self.click_search_video_with_options(video_index, rect, aweme_id, video_url, false)
            .await
    }

    /// 搜索刚完成时打开第一个 Feed，跳过冗长列表等待
    pub async fn click_search_video_fresh(
        &self,
        video_index: i64,
    ) -> Result<Value, String> {
        self.click_search_video_with_options(video_index, None, None, None, true)
            .await
    }

    async fn click_search_video_with_options(
        &self,
        video_index: i64,
        rect: Option<Value>,
        aweme_id: Option<&str>,
        video_url: Option<&str>,
        fresh_search: bool,
    ) -> Result<Value, String> {
        let mut payload = json!({
            "video_index": video_index.max(1),
            "use_detail_window": false,
            "open_strategy": "feed",
            "fresh_search": fresh_search,
        });
        if let Some(rect) = rect {
            payload["rect"] = rect;
        }
        if let Some(id) = aweme_id.filter(|s| !s.trim().is_empty()) {
            payload["aweme_id"] = json!(id);
        }
        if let Some(url) = video_url.filter(|s| !s.trim().is_empty()) {
            payload["video_url"] = json!(url);
        }
        self.action("click_search_video", payload).await
    }

    /// Feed 浮层内通过 modal_id 切到指定视频（不返回搜索列表）
    pub async fn jump_search_feed_video(
        &self,
        video_index: i64,
        aweme_id: &str,
    ) -> Result<Value, String> {
        self.action(
            "click_search_video",
            json!({
                "video_index": video_index.max(1),
                "aweme_id": aweme_id,
                "open_strategy": "modal_only",
                "use_detail_window": false,
            }),
        )
        .await
    }

    pub async fn fetch_search_results(&self, limit: i64) -> Result<Value, String> {
        self.fetch_search_results_with_options(limit, None).await
    }

    pub async fn fetch_search_results_after_scroll(
        &self,
        limit: i64,
        baseline_count: usize,
    ) -> Result<Value, String> {
        self.fetch_search_results_with_options(limit, Some(baseline_count))
            .await
    }

    async fn fetch_search_results_with_options(
        &self,
        limit: i64,
        baseline_count: Option<usize>,
    ) -> Result<Value, String> {
        let mut payload = json!({
            "limit": limit.clamp(1, 50),
            "api_timeout_ms": 8_000,
        });
        if let Some(baseline) = baseline_count {
            payload["preserve_scroll_position"] = json!(true);
            payload["baseline_count"] = json!(baseline as i64);
        }
        self.action("fetch_search_results", payload).await
    }

    pub async fn swipe_search_results(&self, rounds: i64) -> Result<(), String> {
        for _ in 0..rounds.clamp(1, 6) {
            let _ = self
                .action(
                    "swipe_page",
                    json!({ "direction": "down", "distance": 900, "segments": 3 }),
                )
                .await;
            simulate::pause(Duration::from_millis(800)).await;
        }
        Ok(())
    }

    pub async fn click_profile_video(
        &self,
        video_index: i64,
        aweme_id: Option<&str>,
    ) -> Result<Value, String> {
        let mut payload = json!({ "video_index": video_index.max(1) });
        if let Some(id) = aweme_id.filter(|s| !s.trim().is_empty()) {
            payload["aweme_id"] = json!(id);
        }
        self.action("click_profile_video", payload).await
    }

    /// 主页刚打开时点击第一个视频进 Feed，跳过冗长列表等待
    pub async fn click_profile_video_fresh(
        &self,
        video_index: i64,
    ) -> Result<Value, String> {
        self.action(
            "click_profile_video",
            json!({
                "video_index": video_index.max(1),
                "fresh_profile": true,
            }),
        )
        .await
    }

    pub async fn probe_douyin_feed(&self) -> Result<Value, String> {
        self.action("probe_douyin_feed", json!({ "platform": self.platform })).await
    }

    pub async fn probe_video_detail(&self) -> Result<Value, String> {
        self.action("probe_video_detail", json!({ "platform": self.platform })).await
    }

    /// 探测当前标签页是否已在 Feed 或 /video/ 播放页（优先详情页）
    pub async fn probe_current_playback(&self) -> Result<Value, String> {
        if let Ok(detail) = self.probe_video_detail().await {
            if detail.get("is_standalone_video").and_then(|v| v.as_bool()) == Some(true) {
                return Ok(detail);
            }
        }
        if let Ok(feed) = self.probe_douyin_feed().await {
            if feed.get("is_search_feed").and_then(|v| v.as_bool()) == Some(true)
                || feed.get("ok").and_then(|v| v.as_bool()) == Some(true)
            {
                return Ok(feed);
            }
        }
        if let Ok(page) = self
            .hub
            .request_command("get_page_info", json!({}), Duration::from_secs(8))
            .await
        {
            let url = page.get("url").and_then(|v| v.as_str()).unwrap_or("");
            if url.contains("/video/") || url.contains("/short-video/") {
                let aweme_id = url
                    .split("/video/")
                    .nth(1)
                    .or_else(|| url.split("/short-video/").nth(1))
                    .map(|s| s.split(['?', '#', '/']).next().unwrap_or("").trim())
                    .filter(|s| !s.is_empty());
                if let Some(id) = aweme_id {
                    return Ok(json!({
                        "ok": true,
                        "is_standalone_video": true,
                        "is_search_feed": false,
                        "url": url,
                        "aweme_id": id,
                        "message": "detected /video/ playback from get_page_info",
                    }));
                }
            }
            if url.contains("modal_id=") {
                let aweme_id = url
                    .split("modal_id=")
                    .nth(1)
                    .map(|s| s.split(['&', '#']).next().unwrap_or("").trim())
                    .filter(|s| !s.is_empty());
                return Ok(json!({
                    "ok": true,
                    "is_search_feed": true,
                    "feed_open": true,
                    "url": url,
                    "aweme_id": aweme_id,
                    "message": "detected search feed from get_page_info",
                }));
            }
        }
        Ok(json!({
            "ok": false,
            "message": "not on feed or /video/ playback page",
        }))
    }

    pub async fn fetch_profile_videos(&self, limit: i64) -> Result<Value, String> {
        self.action(
            "fetch_profile_videos",
            json!({
                "limit": limit.clamp(1, 50),
                "api_timeout_ms": 15_000,
            }),
        )
        .await
    }

    pub async fn prepare_profile_for_video(&self) -> Result<Value, String> {
        self.action("prepare_profile_for_video", json!({})).await
    }

    pub async fn back_to_profile(&self, profile_url: Option<&str>) -> Result<Value, String> {
        let mut payload = json!({});
        if let Some(url) = profile_url.filter(|s| !s.trim().is_empty()) {
            payload["profile_url"] = json!(url);
        }
        self.action("back_to_profile", payload).await
    }

    pub async fn open_url(&self, url: &str) -> Result<Value, String> {
        self.open_browser_url(url, true).await
    }

    /// 手动获客：复用平台工作窗；仅当显式需要隔离时使用 force_new
    pub async fn open_url_in_new_window(&self, url: &str) -> Result<Value, String> {
        self.open_browser_url(url, true).await
    }

    async fn open_browser_url(&self, url: &str, reuse_existing: bool) -> Result<Value, String> {
        self.action(
            "open_browser",
            json!({
                "platform": self.platform,
                "url": url,
                "reuse_existing": reuse_existing,
            }),
        )
        .await
    }

    /// 打开抖音视频详情（含 v.douyin.com 短链），等待跳转到 /video/ 页
    pub async fn open_douyin_video_detail(&self, url: &str) -> Result<Value, String> {
        self.action(
            "open_browser",
            json!({
                "platform": self.platform,
                "url": url,
                "reuse_existing": true,
                "wait_video_detail": true,
            }),
        )
        .await
    }

    pub async fn open_video(&self, aweme_id: &str, video_url: Option<&str>) -> Result<Value, String> {
        let url = video_url
            .filter(|s| !s.trim().is_empty())
            .map(str::to_string)
            .unwrap_or_else(|| self.adapter().content_url(aweme_id));
        self.open_url(&url).await
    }

    pub async fn open_comment_sidebar(&self) -> Result<Value, String> {
        self.open_feed_comment_sidebar().await
    }

    pub async fn open_feed_comment_sidebar(&self) -> Result<Value, String> {
        self.action(
            "click_comment_btn",
            json!({ "platform": self.platform, "playback_mode": "feed" }),
        )
        .await
    }

    pub async fn open_video_detail_comment_sidebar(&self) -> Result<Value, String> {
        self.action(
            "click_comment_btn",
            json!({ "platform": self.platform, "playback_mode": "video_detail" }),
        )
        .await
    }

    pub async fn scroll_comments(
        &self,
        rounds: i64,
        max_comments: i64,
        comment_days: i64,
    ) -> Result<Value, String> {
        self.scroll_feed_comments(rounds, max_comments, comment_days).await
    }

    pub async fn scroll_feed_comments(
        &self,
        rounds: i64,
        max_comments: i64,
        comment_days: i64,
    ) -> Result<Value, String> {
        self.scroll_comments_with_mode(rounds, max_comments, comment_days, "feed")
            .await
    }

    pub async fn scroll_video_detail_comments(
        &self,
        rounds: i64,
        max_comments: i64,
        comment_days: i64,
    ) -> Result<Value, String> {
        self.scroll_comments_with_mode(rounds, max_comments, comment_days, "video_detail")
            .await
    }

    async fn scroll_comments_with_mode(
        &self,
        rounds: i64,
        max_comments: i64,
        comment_days: i64,
        playback_mode: &str,
    ) -> Result<Value, String> {
        self.action(
            "scroll_and_collect_comments",
            json!({
                "scroll_rounds": rounds.clamp(1, 60),
                "max_comments": max_comments.clamp(10, 300),
                "comment_days": comment_days.max(0),
                "playback_mode": playback_mode,
            }),
        )
        .await
    }

    pub async fn swipe_page_down(&self, rounds: i64) -> Result<(), String> {
        for _ in 0..rounds.clamp(1, 8) {
            let _ = self
                .action(
                    "swipe_page",
                    json!({ "direction": "down", "distance": 800, "segments": 2 }),
                )
                .await;
            simulate::pause(Duration::from_millis(700)).await;
        }
        Ok(())
    }

    pub async fn prepare_video_for_outreach(
        &self,
        aweme_id: &str,
        video_url: Option<&str>,
    ) -> Result<(), String> {
        for attempt in 0..2 {
            self.open_video(aweme_id, video_url).await?;
            simulate::pause(Duration::from_secs(4)).await;

            let sidebar = self.open_comment_sidebar().await?;
            if Self::lab_ok(&sidebar) {
                simulate::pause(Duration::from_secs(2)).await;
                return Ok(());
            }

            let err = sidebar
                .get("message")
                .or_else(|| sidebar.get("error"))
                .and_then(|v| v.as_str())
                .unwrap_or("");
            if attempt == 0 && (err.contains("navigat") || err.contains("load")) {
                simulate::pause(Duration::from_secs(4)).await;
                continue;
            }
            return Err(format!("failed to open comment sidebar: {err}"));
        }
        Err("failed to open comment sidebar".into())
    }

    pub async fn reply_to_comment(
        &self,
        aweme_id: &str,
        comment_id: &str,
        comment_text: &str,
        reply_text: &str,
        scroll_rounds: i64,
        dry_run: bool,
    ) -> Result<Value, String> {
        if dry_run {
            return Ok(json!({ "ok": true, "dry_run": true }));
        }

        let video_url = self.adapter().content_url(aweme_id);
        self.prepare_video_for_outreach(aweme_id, Some(&video_url))
            .await?;

        let reply_payload = json!({
            "reply_text": reply_text,
            "comment_id": comment_id,
            "comment_text": comment_text,
            "scroll_rounds": scroll_rounds,
        });

        let typed = self.action("reply_comment", reply_payload).await?;
        if !Self::lab_ok(&typed) {
            return Ok(typed);
        }

        simulate::pause(Duration::from_millis(500)).await;

        let sent = self.action("send_comment", json!({})).await?;
        Ok(sent)
    }

    pub async fn open_profile_from_comment(
        &self,
        aweme_id: &str,
        comment_id: &str,
        comment_text: &str,
        scroll_rounds: i64,
    ) -> Result<Value, String> {
        let video_url = self.adapter().content_url(aweme_id);
        self.prepare_video_for_outreach(aweme_id, Some(&video_url))
            .await?;

        self.action(
            "click_comment_avatar",
            json!({
                "comment_id": comment_id,
                "comment_text": comment_text,
                "scroll_rounds": scroll_rounds,
            }),
        )
        .await
    }

    pub async fn follow_from_comment(
        &self,
        aweme_id: &str,
        comment_id: &str,
        comment_text: &str,
        scroll_rounds: i64,
    ) -> Result<Value, String> {
        let opened = self
            .open_profile_from_comment(aweme_id, comment_id, comment_text, scroll_rounds)
            .await?;
        if !Self::lab_ok(&opened) {
            return Ok(opened);
        }

        simulate::pause(Duration::from_secs(2)).await;
        self.action("click_follow_btn", json!({})).await
    }

    pub async fn send_dm_on_profile(&self, text: &str) -> Result<Value, String> {
        let dm_open = self.action("click_dm_btn", json!({})).await?;
        if !Self::lab_ok(&dm_open) {
            return Ok(dm_open);
        }

        simulate::pause(Duration::from_millis(800)).await;

        let typed = self
            .action("input_dm_text", json!({ "dm_text": text }))
            .await?;
        if !Self::lab_ok(&typed) {
            return Ok(typed);
        }

        simulate::pause(Duration::from_millis(500)).await;
        self.action("send_dm", json!({ "dm_text": text })).await
    }

    async fn request_bridge(
        &self,
        bridge_action: &str,
        payload: Value,
        timeout: Duration,
    ) -> Result<Value, String> {
        let result = self
            .hub
            .request_command(bridge_action, payload.clone(), timeout)
            .await;
        if let Some((db, job_id, run_id)) = &self.run_log {
            match &result {
                Ok(v) => log_bridge_command(db, job_id, *run_id, bridge_action, &payload, Ok(v)),
                Err(e) => log_bridge_command(db, job_id, *run_id, bridge_action, &payload, Err(e)),
            }
        }
        result
    }

    async fn action(&self, action_id: &str, mut payload: Value) -> Result<Value, String> {
        let bridge_action = plugin_lab::bridge_action_for(action_id).ok_or_else(|| {
            format!("unsupported plugin-lab action: {action_id}")
        })?;
        if payload
            .get("platform")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .is_empty()
        {
            if let Some(obj) = payload.as_object_mut() {
                obj.insert("platform".to_string(), json!(self.platform));
            }
        }
        let normalized = plugin_lab::normalize_payload(action_id, payload.clone());
        let result = self
            .hub
            .request_command(bridge_action, normalized, action_timeout(action_id))
            .await;
        if let Some((db, job_id, run_id)) = &self.run_log {
            match &result {
                Ok(v) => log_lab_action(db, job_id, *run_id, action_id, &payload, Ok(v)),
                Err(e) => log_lab_action(db, job_id, *run_id, action_id, &payload, Err(e)),
            }
        }
        result
    }

    fn lab_ok(data: &Value) -> bool {
        data.get("ok").and_then(|v| v.as_bool()).unwrap_or(true)
    }

    fn search_box_ready(data: &Value) -> bool {
        if !Self::lab_ok(data) {
            return false;
        }
        data.get("found").and_then(|v| v.as_bool()).unwrap_or(false)
    }

    fn search_result_count(data: &Value) -> usize {
        data.get("count")
            .and_then(|v| v.as_u64())
            .or_else(|| {
                data.get("items")
                    .and_then(|v| v.as_array())
                    .map(|a| a.len() as u64)
            })
            .or_else(|| {
                data.get("results")
                    .and_then(|v| v.as_array())
                    .map(|a| a.len() as u64)
            })
            .unwrap_or(0) as usize
    }
}

fn action_timeout(action_id: &str) -> Duration {
    match action_id {
        "input_search_text" | "find_search_box" | "scroll_and_collect_comments" | "click_search_btn" => {
            Duration::from_secs(120)
        }
        "click_search_video" => Duration::from_secs(90),
        "click_profile_video" => Duration::from_secs(90),
        "click_comment_btn" => Duration::from_secs(90),
        "reply_comment" | "input_dm_text" => Duration::from_secs(60),
        "open_browser" => Duration::from_secs(120),
        "fetch_search_results" => Duration::from_secs(120),
        "swipe_search_feed_next" => Duration::from_secs(30),
        "swipe_video_detail_next" => Duration::from_secs(30),
        "swipe_page" => Duration::from_secs(20),
        _ => Duration::from_secs(45),
    }
}
