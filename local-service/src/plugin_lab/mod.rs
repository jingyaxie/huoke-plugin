use serde_json::{json, Value};

/// Map plugin-lab UI action id → bridge command action.
pub fn bridge_action_for(action_id: &str) -> Option<&'static str> {
    match action_id {
        "open_browser" => Some("plugin_lab.open_browser"),
        "swipe_page" => Some("plugin_lab.swipe_page"),
        "find_search_box" => Some("plugin_lab.find_search_box"),
        "input_search_text" => Some("plugin_lab.input_search_text"),
        "click_filter_btn" => Some("plugin_lab.click_filter_btn"),
        "click_filter_overlay" => Some("plugin_lab.click_filter_overlay"),
        "click_search_btn" => Some("plugin_lab.click_search_btn"),
        "ensure_search_multi_column" => Some("plugin_lab.ensure_search_multi_column"),
        "fetch_search_results" => Some("plugin_lab.fetch_search_results"),
        "click_search_video" => Some("plugin_lab.click_search_video"),
        "click_profile_video" => Some("plugin_lab.click_profile_video"),
        "prepare_search_for_video" => Some("plugin_lab.prepare_search_video"),
        "swipe_search_feed_next" => Some("plugin_lab.swipe_search_feed_next"),
        "prepare_feed_for_swipe" => Some("plugin_lab.prepare_feed_for_swipe"),
        "recover_search_feed" => Some("plugin_lab.recover_search_feed"),
        "probe_douyin_feed" => Some("plugin_lab.probe_douyin_feed"),
        "search_video_probe" => Some("plugin_lab.search_video_probe"),
        "prepare_profile_for_video" => Some("plugin_lab.prepare_profile_video"),
        "fetch_profile_videos" => Some("plugin_lab.fetch_profile_videos"),
        "back_to_profile" => Some("plugin_lab.back_to_profile"),
        "click_comment_btn" => Some("plugin_lab.click_comment_btn"),
        "scroll_and_collect_comments" => Some("plugin_lab.scroll_and_collect_comments"),
        "reply_comment" => Some("plugin_lab.reply_comment"),
        "send_comment" => Some("plugin_lab.send_comment"),
        "click_comment_avatar" => Some("plugin_lab.click_comment_avatar"),
        "click_follow_btn" => Some("plugin_lab.click_follow_btn"),
        "click_dm_btn" => Some("plugin_lab.click_dm_btn"),
        "input_dm_text" => Some("plugin_lab.input_dm_text"),
        "send_dm" => Some("plugin_lab.send_dm"),
        "close_video_detail" => Some("plugin_lab.close_video_detail"),
        "search_context_probe" => Some("plugin_lab.search_context_probe"),
        _ => None,
    }
}

pub fn normalize_payload(action_id: &str, payload: Value) -> Value {
    match action_id {
        "open_browser" => normalize_open_browser_payload(payload),
        "swipe_page" => normalize_swipe_page_payload(payload),
        "find_search_box" => normalize_find_search_box_payload(payload),
        "input_search_text" => normalize_input_search_text_payload(payload),
        "click_filter_overlay" => normalize_click_filter_overlay_payload(payload),
        "fetch_search_results" => normalize_fetch_search_results_payload(payload),
        "click_search_video" => normalize_click_search_video_payload(payload),
        "click_profile_video" => normalize_click_search_video_payload(payload),
        "fetch_profile_videos" => normalize_fetch_search_results_payload(payload),
        "scroll_and_collect_comments" => normalize_scroll_collect_comments_payload(payload),
        "reply_comment" => normalize_reply_comment_payload(payload),
        "click_comment_avatar" => normalize_click_comment_avatar_payload(payload),
        "input_dm_text" => normalize_input_dm_text_payload(payload),
        _ => payload,
    }
}

fn normalize_open_browser_payload(payload: Value) -> Value {
    let platform = payload
        .get("platform")
        .and_then(|v| v.as_str())
        .unwrap_or("douyin");
    let url = payload.get("url").and_then(|v| v.as_str()).unwrap_or("");
    let reuse_existing = payload
        .get("reuse_existing")
        .and_then(|v| v.as_bool())
        .or_else(|| {
            payload
                .get("new_tab")
                .and_then(|v| v.as_bool())
                .map(|new_tab| !new_tab)
        })
        .unwrap_or(true);
    let wait_load = payload.get("wait_load").and_then(|v| v.as_bool()).unwrap_or(false);
    let reset_to_start = payload
        .get("reset_to_start")
        .and_then(|v| v.as_bool())
        .unwrap_or(false);

    json!({
        "platform": platform,
        "url": url,
        "reuse_existing": reuse_existing,
        "wait_load": wait_load,
        "reset_to_start": reset_to_start,
    })
}

pub fn supported_actions() -> &'static [&'static str] {
    &[
        "open_browser",
        "swipe_page",
        "find_search_box",
        "input_search_text",
        "click_filter_btn",
        "click_filter_overlay",
        "click_search_btn",
        "ensure_search_multi_column",
        "fetch_search_results",
        "click_search_video",
        "click_profile_video",
        "prepare_search_for_video",
        "swipe_search_feed_next",
        "prepare_feed_for_swipe",
        "recover_search_feed",
        "probe_douyin_feed",
        "search_video_probe",
        "prepare_profile_for_video",
        "fetch_profile_videos",
        "back_to_profile",
        "click_comment_btn",
        "scroll_and_collect_comments",
        "reply_comment",
        "send_comment",
        "click_comment_avatar",
        "click_follow_btn",
        "click_dm_btn",
        "input_dm_text",
        "send_dm",
        "close_video_detail",
        "search_context_probe",
    ]
}

fn normalize_find_search_box_payload(payload: Value) -> Value {
    let platform = payload
        .get("platform")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    json!({ "platform": platform })
}

fn normalize_input_search_text_payload(payload: Value) -> Value {
    let platform = payload
        .get("platform")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let search_text = payload
        .get("search_text")
        .and_then(|v| v.as_str())
        .or_else(|| payload.get("keyword").and_then(|v| v.as_str()))
        .unwrap_or("");

    let mut out = json!({
        "platform": platform,
        "search_text": search_text,
        "focus_first": true,
    });
    if let Some(delay) = payload.get("char_delay_ms") {
        out["char_delay_ms"] = delay.clone();
    }
    out
}

fn normalize_swipe_page_payload(payload: Value) -> Value {
    let direction = payload
        .get("direction")
        .and_then(|v| v.as_str())
        .unwrap_or("down");
    let selector = payload.get("selector").and_then(|v| v.as_str()).unwrap_or("");

    let mut out = json!({
        "direction": direction,
        "selector": selector,
    });

    if let Some(distance) = payload.get("distance").and_then(|v| v.as_i64()) {
        out["distance"] = json!(distance);
    }
    if let Some(segments) = payload.get("segments").and_then(|v| v.as_i64()) {
        out["segments"] = json!(segments);
    }

    out
}

fn normalize_click_filter_overlay_payload(payload: Value) -> Value {
    let mut labels: Vec<String> = payload
        .get("option_labels")
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str().map(str::trim).filter(|s| !s.is_empty()).map(str::to_string))
                .collect()
        })
        .unwrap_or_default();

    if labels.is_empty() {
        if let Some(text) = payload
            .get("option_label")
            .and_then(|v| v.as_str())
            .or_else(|| payload.get("filter_label").and_then(|v| v.as_str()))
        {
            labels = text
                .split(',')
                .map(str::trim)
                .filter(|s| !s.is_empty())
                .map(str::to_string)
                .collect();
        }
    }

    let mut out = json!({
        "open_if_closed": payload.get("open_if_closed").and_then(|v| v.as_bool()).unwrap_or(true),
    });

    if !labels.is_empty() {
        out["option_labels"] = json!(labels);
    }

    if let Some(days) = payload.get("days").and_then(|v| v.as_i64()) {
        out["days"] = json!(days);
    }

    out
}

fn normalize_fetch_search_results_payload(payload: Value) -> Value {
    let mut out = json!({
        "limit": payload.get("limit").and_then(|v| v.as_i64()).unwrap_or(20),
    });
    if let Some(ms) = payload.get("api_timeout_ms").and_then(|v| v.as_i64()) {
        out["api_timeout_ms"] = json!(ms);
    }
    if payload
        .get("preserve_scroll_position")
        .and_then(|v| v.as_bool())
        .unwrap_or(false)
    {
        out["preserve_scroll_position"] = json!(true);
    }
    if let Some(n) = payload.get("baseline_count").and_then(|v| v.as_i64()) {
        out["baseline_count"] = json!(n);
    }
    if let Some(platform) = payload.get("platform").and_then(|v| v.as_str()) {
        if !platform.trim().is_empty() {
            out["platform"] = json!(platform);
        }
    }
    out
}

fn normalize_click_search_video_payload(payload: Value) -> Value {
    let mut out = json!({
        "video_index": payload
            .get("video_index")
            .and_then(|v| v.as_i64())
            .or_else(|| payload.get("index").and_then(|v| v.as_i64()))
            .unwrap_or(1),
        "use_detail_window": payload
            .get("use_detail_window")
            .and_then(|v| v.as_bool())
            .unwrap_or(true),
        "open_strategy": payload
            .get("open_strategy")
            .and_then(|v| v.as_str())
            .filter(|s| !s.trim().is_empty())
            .unwrap_or("auto"),
    });
    if let Some(url) = payload.get("video_url").and_then(|v| v.as_str()) {
        if !url.trim().is_empty() {
            out["video_url"] = Value::from(url);
        }
    }
    if let Some(rect) = payload.get("rect") {
        out["rect"] = rect.clone();
    }
    if let Some(id) = payload.get("aweme_id").and_then(|v| v.as_str()) {
        if !id.trim().is_empty() {
            out["aweme_id"] = Value::from(id);
        }
    }
    if payload
        .get("fresh_search")
        .and_then(|v| v.as_bool())
        .unwrap_or(false)
    {
        out["fresh_search"] = json!(true);
    }
    if let Some(platform) = payload.get("platform").and_then(|v| v.as_str()) {
        if !platform.trim().is_empty() {
            out["platform"] = json!(platform);
        }
    }
    out
}

fn normalize_scroll_collect_comments_payload(payload: Value) -> Value {
    json!({
        "scroll_rounds": payload.get("scroll_rounds").and_then(|v| v.as_i64()).unwrap_or(12),
        "max_comments": payload.get("max_comments").and_then(|v| v.as_i64()).unwrap_or(80),
        "comment_days": payload.get("comment_days").and_then(|v| v.as_i64()).unwrap_or(0),
    })
}

fn normalize_reply_comment_payload(payload: Value) -> Value {
    let mut out = json!({
        "reply_text": payload.get("reply_text").and_then(|v| v.as_str()).unwrap_or(""),
        "comment_index": payload
            .get("comment_index")
            .and_then(|v| v.as_i64())
            .or_else(|| payload.get("index").and_then(|v| v.as_i64()))
            .unwrap_or(1),
    });
    merge_comment_target_fields(&mut out, &payload);
    out
}

fn normalize_click_comment_avatar_payload(payload: Value) -> Value {
    let mut out = json!({
        "comment_index": payload
            .get("comment_index")
            .and_then(|v| v.as_i64())
            .or_else(|| payload.get("index").and_then(|v| v.as_i64()))
            .unwrap_or(1),
    });
    merge_comment_target_fields(&mut out, &payload);
    out
}

fn merge_comment_target_fields(out: &mut Value, payload: &Value) {
    if let Some(id) = payload
        .get("comment_id")
        .and_then(|v| v.as_str())
        .map(str::trim)
        .filter(|s| !s.is_empty())
    {
        out["comment_id"] = json!(id);
    }
    if let Some(text) = payload
        .get("comment_text")
        .and_then(|v| v.as_str())
        .map(str::trim)
        .filter(|s| !s.is_empty())
    {
        out["comment_text"] = json!(text);
    }
    if let Some(rounds) = payload.get("scroll_rounds").and_then(|v| v.as_i64()) {
        out["scroll_rounds"] = json!(rounds);
    }
}

fn normalize_input_dm_text_payload(payload: Value) -> Value {
    json!({
        "dm_text": payload
            .get("dm_text")
            .and_then(|v| v.as_str())
            .or_else(|| payload.get("text").and_then(|v| v.as_str()))
            .unwrap_or(""),
    })
}
