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
        .unwrap_or(false);
    let wait_load = payload.get("wait_load").and_then(|v| v.as_bool()).unwrap_or(true);

    json!({
        "platform": platform,
        "url": url,
        "reuse_existing": reuse_existing,
        "wait_load": wait_load,
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

    json!({
        "platform": platform,
        "search_text": search_text,
        "focus_first": true,
    })
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
