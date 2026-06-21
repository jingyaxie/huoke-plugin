use std::time::Duration;

use serde_json::{json, Value};

use crate::plugin_lab;
use crate::simulate;
use crate::ws::BridgeHub;

/// 任务编排统一走插件实验室已验证步骤（`plugin_lab.*`），不再调用 legacy `douyin.*` UI 命令。
pub struct LabCommands<'a> {
    hub: &'a BridgeHub,
}

impl<'a> LabCommands<'a> {
    pub fn new(hub: &'a BridgeHub) -> Self {
        Self { hub }
    }

    pub async fn enable_network_hook(&self) -> Result<(), String> {
        self.hub
            .request_command(
                "network.hook.enable",
                json!({ "patterns": ["/aweme/", "/comment/", "/search/"] }),
                Duration::from_secs(10),
            )
            .await?;
        Ok(())
    }

    pub async fn run_keyword_search(&self, keyword: &str, publish_days: i64) -> Result<Value, String> {
        // 与插件实验室单步流程一致：1 打开 → 3~7 搜索 →（可选）4~5 筛选
        self.action("open_browser", json!({ "platform": "douyin", "reuse_existing": true }))
            .await?;
        simulate::pause(Duration::from_secs(2)).await;

        self.action("find_search_box", json!({ "platform": "douyin" }))
            .await?;

        self.action(
            "input_search_text",
            json!({ "platform": "douyin", "search_text": keyword }),
        )
        .await?;

        simulate::pause(Duration::from_millis(400)).await;

        // hook 必须在点击搜索之前开启，否则首屏 search API 抓不到
        self.enable_network_hook().await?;

        let submit = self.action("click_search_btn", json!({})).await?;
        if !Self::lab_ok(&submit) {
            return Ok(submit);
        }

        // 等待进入 jingxuan/search 结果页（与实验室手动操作间隔一致）
        simulate::pause(Duration::from_secs(5)).await;

        // 导航后 hook 状态会重置，再 enable 一次
        self.enable_network_hook().await?;

        if publish_days > 0 {
            let _ = self.action("click_filter_btn", json!({})).await;
            simulate::pause(Duration::from_millis(500)).await;
            let _ = self
                .action(
                    "click_filter_overlay",
                    json!({ "days": publish_days, "open_if_closed": true }),
                )
                .await;
            simulate::pause(Duration::from_secs(2)).await;
        }

        Ok(submit)
    }

    pub async fn close_video_detail(&self) -> Result<Value, String> {
        self.action("close_video_detail", json!({})).await
    }

    pub async fn prepare_search_for_video(&self) -> Result<Value, String> {
        self.action("prepare_search_for_video", json!({})).await
    }

    pub async fn click_search_video(
        &self,
        video_index: i64,
        rect: Option<Value>,
        aweme_id: Option<&str>,
    ) -> Result<Value, String> {
        let mut payload = json!({ "video_index": video_index.max(1) });
        if let Some(rect) = rect {
            payload["rect"] = rect;
        }
        if let Some(id) = aweme_id.filter(|s| !s.trim().is_empty()) {
            payload["aweme_id"] = json!(id);
        }
        self.action("click_search_video", payload).await
    }

    pub async fn fetch_search_results(&self, limit: i64) -> Result<Value, String> {
        self.action(
            "fetch_search_results",
            json!({ "limit": limit.clamp(1, 50) }),
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

    pub async fn open_url(&self, url: &str) -> Result<Value, String> {
        self.action(
            "open_browser",
            json!({ "platform": "douyin", "url": url, "reuse_existing": true }),
        )
        .await
    }

    pub async fn open_video(&self, aweme_id: &str, video_url: Option<&str>) -> Result<Value, String> {
        let url = video_url
            .filter(|s| !s.trim().is_empty())
            .map(str::to_string)
            .unwrap_or_else(|| format!("https://www.douyin.com/video/{aweme_id}"));
        self.open_url(&url).await
    }

    pub async fn open_comment_sidebar(&self) -> Result<Value, String> {
        self.action("click_comment_btn", json!({})).await
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

        let video_url = format!("https://www.douyin.com/video/{aweme_id}");
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
        let video_url = format!("https://www.douyin.com/video/{aweme_id}");
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

    async fn action(&self, action_id: &str, payload: Value) -> Result<Value, String> {
        let bridge_action = plugin_lab::bridge_action_for(action_id).ok_or_else(|| {
            format!("unsupported plugin-lab action: {action_id}")
        })?;
        let normalized = plugin_lab::normalize_payload(action_id, payload);
        self.hub
            .request_command(bridge_action, normalized, action_timeout(action_id))
            .await
    }

    fn lab_ok(data: &Value) -> bool {
        data.get("ok").and_then(|v| v.as_bool()).unwrap_or(true)
    }
}

fn action_timeout(action_id: &str) -> Duration {
    match action_id {
        "input_search_text" | "scroll_and_collect_comments" | "click_search_btn" => {
            Duration::from_secs(120)
        }
        "click_search_video" => Duration::from_secs(90),
        "reply_comment" | "input_dm_text" => Duration::from_secs(60),
        "open_browser" => Duration::from_secs(45),
        _ => Duration::from_secs(45),
    }
}
