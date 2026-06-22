use std::time::Duration;

use serde_json::{json, Value};

use tracing::warn;

use crate::platforms::PlatformCollectAdapter;
use crate::plugin_lab;
use crate::simulate;
use crate::ws::BridgeHub;

/// 任务编排统一走插件实验室已验证步骤（`plugin_lab.*`），不再调用 legacy `douyin.*` UI 命令。
pub struct LabCommands<'a> {
    hub: &'a BridgeHub,
    platform: String,
}

impl<'a> LabCommands<'a> {
    pub fn new(hub: &'a BridgeHub, platform: &str) -> Self {
        Self {
            hub,
            platform: crate::platforms::normalize_platform(platform).to_string(),
        }
    }

    fn adapter(&self) -> &'static dyn PlatformCollectAdapter {
        crate::platforms::get_platform_adapter(&self.platform)
    }

    pub async fn enable_network_hook(&self) -> Result<(), String> {
        const MAX_ATTEMPTS: u32 = 3;
        let patterns: Vec<&str> = self.adapter().network_hook_patterns().to_vec();
        let mut last_err = String::new();
        for attempt in 1..=MAX_ATTEMPTS {
            match self
                .hub
                .request_command(
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

    pub async fn run_keyword_search(&self, keyword: &str, publish_days: i64) -> Result<Value, String> {
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
        simulate::pause(Duration::from_secs(3)).await;

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
            simulate::pause(Duration::from_millis(800)).await;
        }

        // 等待进入搜索结果页
        simulate::pause(Duration::from_secs(5)).await;

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
            simulate::pause(Duration::from_secs(2)).await;
        }

        // 导航/筛选后 hook 会重置；抓数放在最后一步，确保拿到当前列表
        self.enable_network_hook().await?;
        simulate::pause(Duration::from_secs(1)).await;

        if platform == "douyin" {
            let _ = self.action("ensure_search_multi_column", json!({})).await;
            simulate::pause(Duration::from_millis(600)).await;
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

    pub async fn click_search_video(
        &self,
        video_index: i64,
        rect: Option<Value>,
        aweme_id: Option<&str>,
        video_url: Option<&str>,
    ) -> Result<Value, String> {
        let mut payload = json!({
            "video_index": video_index.max(1),
            "use_detail_window": false,
            "open_strategy": "auto",
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
        self.action(
            "fetch_search_results",
            json!({
                "limit": limit.clamp(1, 50),
                "api_timeout_ms": 25_000,
            }),
        )
        .await
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

    pub async fn open_video(&self, aweme_id: &str, video_url: Option<&str>) -> Result<Value, String> {
        let url = video_url
            .filter(|s| !s.trim().is_empty())
            .map(str::to_string)
            .unwrap_or_else(|| self.adapter().content_url(aweme_id));
        self.open_url(&url).await
    }

    pub async fn open_comment_sidebar(&self) -> Result<Value, String> {
        self.action("click_comment_btn", json!({ "platform": self.platform })).await
    }

    pub async fn scroll_comments(
        &self,
        rounds: i64,
        max_comments: i64,
        comment_days: i64,
    ) -> Result<Value, String> {
        self.action(
            "scroll_and_collect_comments",
            json!({
                "scroll_rounds": rounds.clamp(1, 60),
                "max_comments": max_comments.clamp(10, 300),
                "comment_days": comment_days.max(0),
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
        let normalized = plugin_lab::normalize_payload(action_id, payload);
        self.hub
            .request_command(bridge_action, normalized, action_timeout(action_id))
            .await
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
        "swipe_page" => Duration::from_secs(20),
        _ => Duration::from_secs(45),
    }
}
