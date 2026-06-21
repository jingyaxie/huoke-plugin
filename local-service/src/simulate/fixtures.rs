use serde_json::{json, Value};

pub const SIM_VIDEO_IDS: [&str; 3] = [
    "7123456789012345678",
    "7123456789012345679",
    "7123456789012345680",
];

fn recent_ts(offset_secs: i64) -> i64 {
    chrono::Utc::now().timestamp() - offset_secs
}

pub fn sim_video_url(aweme_id: &str) -> String {
    format!("https://www.douyin.com/video/{aweme_id}")
}

pub fn search_capture_body() -> Value {
    let data: Vec<Value> = SIM_VIDEO_IDS
        .iter()
        .enumerate()
        .map(|(i, id)| {
            json!({
                "aweme_info": {
                    "aweme_id": id,
                    "desc": format!("北京 模拟搜索视频 {}", i + 1),
                    "author": { "nickname": format!("北京作者{}", i + 1) }
                }
            })
        })
        .collect();
    json!({ "data": data })
}

pub fn comment_capture_body(aweme_id: &str, batch: u64) -> Value {
    let comments: Vec<Value> = (0..5)
        .map(|i| {
            let cid = format!("sim_{aweme_id}_{batch}_{i}");
            json!({
                "cid": cid,
                "text": format!("模拟评论 {batch}-{i} 北京装修咨询"),
                "digg_count": 10 + i,
                "create_time": recent_ts(i * 3600),
                "user": {
                    "uid": format!("user_{batch}_{i}"),
                    "nickname": format!("用户{batch}_{i}"),
                    "sec_uid": format!("sec_{batch}_{i}")
                }
            })
        })
        .collect();
    json!({
        "aweme_id": aweme_id,
        "comments": comments
    })
}

pub fn extract_aweme_from_payload(payload: &Value) -> Option<String> {
    if let Some(url) = payload.get("url").and_then(|v| v.as_str()) {
        if let Some(id) = aweme_from_url(url) {
            return Some(id);
        }
    }
    payload
        .get("aweme_id")
        .and_then(|v| v.as_str())
        .map(str::to_string)
        .filter(|s| !s.is_empty())
}

pub fn aweme_from_url(url: &str) -> Option<String> {
    let marker = "/video/";
    let pos = url.find(marker)?;
    let rest = &url[pos + marker.len()..];
    let id: String = rest.chars().take_while(|c| c.is_ascii_digit()).collect();
    if id.len() >= 8 {
        Some(id)
    } else {
        None
    }
}
