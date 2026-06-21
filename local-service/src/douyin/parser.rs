use serde_json::Value;

pub const DOM_POSTER_AWEME_PREFIX: &str = "poster_";

#[derive(Debug, Clone)]
pub struct ParsedVideo {
    pub aweme_id: String,
    pub video_url: String,
    pub title: String,
    pub author: String,
    pub raw_json: Option<String>,
}

#[derive(Debug, Clone)]
pub struct ParsedComment {
    pub comment_id: String,
    pub parent_comment_id: Option<String>,
    pub content: String,
    pub username: String,
    pub user_id: String,
    pub sec_uid: String,
    pub digg_count: i64,
    pub create_time: Option<i64>,
    pub raw_json: Option<String>,
}

pub fn is_profile_post_api(url: &str) -> bool {
    let lower = url.to_lowercase();
    lower.contains("/aweme/v1/web/aweme/post") || lower.contains("aweme/post")
}

pub fn is_search_api(url: &str) -> bool {
    let lower = url.to_lowercase();
    (lower.contains("general/search/single")
        || lower.contains("search/item")
        || lower.contains("search/single"))
        && !lower.contains("search/sug")
        && !lower.contains("suggest_words")
}

pub fn is_comment_api(url: &str) -> bool {
    url.contains("/aweme/v1/web/comment/list")
}

pub fn extract_aweme_id_from_url(url: &str) -> Option<String> {
    if let Some(query) = url.split('?').nth(1) {
        for (key, value) in query.split('&').filter_map(|pair| pair.split_once('=')) {
            if key == "aweme_id" && !value.is_empty() {
                return Some(value.to_string());
            }
        }
    }
    parse_aweme_id_from_page_url(url)
}

/// 从抖音页面 URL 解析 aweme_id（`/video/{id}` 或 `modal_id=`）。
pub fn parse_aweme_id_from_page_url(url: &str) -> Option<String> {
    if let Some(pos) = url.find("modal_id=") {
        let rest = &url[pos + "modal_id=".len()..];
        let id: String = rest
            .chars()
            .take_while(|c| c.is_ascii_digit())
            .collect();
        if is_valid_aweme_id(&id) {
            return Some(id);
        }
    }
    for marker in ["/video/", "/note/"] {
        let pos = url.find(marker)?;
        let rest = &url[pos + marker.len()..];
        let id: String = rest.chars().take_while(|c| c.is_ascii_digit()).collect();
        if is_valid_aweme_id(&id) {
            return Some(id);
        }
    }
    None
}

pub fn parse_search_videos(body: &Value) -> Vec<ParsedVideo> {
    let mut items = Vec::new();
    let mut seen = std::collections::HashSet::new();
    walk_search_nodes(body, &mut items, &mut seen);
    items
}

pub fn is_valid_aweme_id(value: &str) -> bool {
    value.len() >= 8 && value.len() <= 22 && value.chars().all(|c| c.is_ascii_digit())
}

pub fn is_dom_poster_aweme_id(aweme_id: &str) -> bool {
    aweme_id.starts_with(DOM_POSTER_AWEME_PREFIX)
}

pub fn dom_poster_index(aweme_id: &str) -> Option<i64> {
    if !is_dom_poster_aweme_id(aweme_id) {
        return None;
    }
    aweme_id[DOM_POSTER_AWEME_PREFIX.len()..]
        .parse()
        .ok()
}

pub fn dom_poster_click_payload(raw_json: Option<&str>) -> Value {
    let mut payload = serde_json::json!({});
    let Some(raw) = raw_json else {
        return payload;
    };
    let Ok(value) = serde_json::from_str::<Value>(raw) else {
        return payload;
    };
    if let Some(index) = value.get("index").and_then(|v| v.as_i64()) {
        payload["video_index"] = json_i64(index);
    }
    if let Some(rect) = value.get("rect") {
        payload["rect"] = rect.clone();
    }
    payload
}

fn json_i64(n: i64) -> Value {
    Value::from(n)
}

fn synthetic_dom_poster_id(index: i64) -> String {
    format!("{DOM_POSTER_AWEME_PREFIX}{index:08}")
}

fn parse_dom_search_item(item: &Value) -> Option<ParsedVideo> {
    if item.is_string() {
        let aweme_id = item.as_str()?.trim().to_string();
        if !is_valid_aweme_id(&aweme_id) {
            return None;
        }
        return Some(ParsedVideo {
            aweme_id: aweme_id.clone(),
            video_url: format!("https://www.douyin.com/video/{aweme_id}"),
            title: String::new(),
            author: String::new(),
            raw_json: None,
        });
    }

    let obj = item.as_object()?;
    let aweme_id = obj
        .get("aweme_id")
        .and_then(|v| v.as_str())
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_string)
        .or_else(|| {
            obj.get("url")
                .and_then(|v| v.as_str())
                .and_then(parse_aweme_id_from_page_url)
        })
        .unwrap_or_default();

    if is_valid_aweme_id(&aweme_id) {
        return Some(ParsedVideo {
            aweme_id: aweme_id.clone(),
            video_url: obj
                .get("url")
                .and_then(|v| v.as_str())
                .filter(|s| !s.is_empty())
                .map(str::to_string)
                .unwrap_or_else(|| format!("https://www.douyin.com/video/{aweme_id}")),
            title: obj
                .get("title")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .trim()
                .to_string(),
            author: obj
                .get("author")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .trim()
                .to_string(),
            raw_json: serde_json::to_string(obj).ok(),
        });
    }

    let index = obj.get("index").and_then(|v| v.as_i64()).unwrap_or(0);
    if index <= 0 {
        return None;
    }
    Some(ParsedVideo {
        aweme_id: synthetic_dom_poster_id(index),
        video_url: String::new(),
        title: obj
            .get("title")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim()
            .to_string(),
        author: obj
            .get("author")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim()
            .to_string(),
        raw_json: serde_json::to_string(obj).ok(),
    })
}

/// 从 `plugin_lab.fetch_search_results` / `click_search_btn` 的结果解析视频列表。
pub fn parse_dom_search_results(resp: &Value) -> Vec<ParsedVideo> {
    let root = resp.get("data").unwrap_or(resp);
    let items = root
        .get("items")
        .or_else(|| root.get("results"))
        .and_then(|v| v.as_array());
    let Some(items) = items else {
        return Vec::new();
    };

    let mut out = Vec::new();
    let mut seen = std::collections::HashSet::new();
    for item in items {
        let Some(video) = parse_dom_search_item(item) else {
            continue;
        };
        if seen.insert(video.aweme_id.clone()) {
            out.push(video);
        }
    }
    out
}

fn walk_search_nodes(node: &Value, out: &mut Vec<ParsedVideo>, seen: &mut std::collections::HashSet<String>) {
    match node {
        Value::Object(map) => {
            if let Some(video) = normalize_search_aweme(map) {
                if seen.insert(video.aweme_id.clone()) {
                    out.push(video);
                }
            }
            for value in map.values() {
                walk_search_nodes(value, out, seen);
            }
        }
        Value::Array(list) => {
            for item in list {
                walk_search_nodes(item, out, seen);
            }
        }
        _ => {}
    }
}

fn normalize_search_aweme(node: &serde_json::Map<String, Value>) -> Option<ParsedVideo> {
    let aweme = node
        .get("aweme_info")
        .and_then(|v| v.as_object())
        .unwrap_or(node);

    let aweme_id = aweme
        .get("aweme_id")
        .and_then(|v| v.as_str().map(|s| s.to_string()))
        .or_else(|| aweme.get("aweme_id").and_then(|v| v.as_i64()).map(|n| n.to_string()))
        .unwrap_or_default();

    if !is_valid_aweme_id(&aweme_id) {
        return None;
    }

    let author = aweme.get("author").and_then(|v| v.as_object());
    let title = aweme
        .get("desc")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_string();
    let author_name = author
        .and_then(|a| a.get("nickname"))
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_string();

    Some(ParsedVideo {
        aweme_id: aweme_id.clone(),
        video_url: format!("https://www.douyin.com/video/{aweme_id}"),
        title,
        author: author_name,
        raw_json: serde_json::to_string(aweme).ok(),
    })
}

pub fn parse_comment_list(body: &Value, fallback_aweme_id: Option<&str>) -> (String, Vec<ParsedComment>) {
    let aweme_id = body
        .get("aweme_id")
        .and_then(|v| v.as_str())
        .map(|s| s.to_string())
        .or_else(|| {
            fallback_aweme_id.map(|s| s.to_string())
        })
        .unwrap_or_default();

    let mut comments = Vec::new();
    if let Some(list) = body.get("comments").and_then(|v| v.as_array()) {
        for item in list {
            if let Some(parsed) = normalize_comment(item, None) {
                let parent_id = parsed.comment_id.clone();
                comments.push(parsed);
                if let Some(replies) = item.get("reply_comment").and_then(|v| v.as_array()) {
                    for reply in replies {
                        if let Some(parsed_reply) = normalize_comment(reply, Some(parent_id.clone())) {
                            comments.push(parsed_reply);
                        }
                    }
                }
            }
        }
    }
    (aweme_id, comments)
}

fn normalize_comment(item: &Value, parent_comment_id: Option<String>) -> Option<ParsedComment> {
    let map = item.as_object()?;
    let comment_id = map
        .get("cid")
        .and_then(|v| v.as_str())
        .or_else(|| map.get("comment_id").and_then(|v| v.as_str()))
        .unwrap_or("")
        .to_string();
    if comment_id.is_empty() {
        return None;
    }

    let user = map.get("user").and_then(|v| v.as_object());
    let avatar = user
        .and_then(|u| u.get("avatar_larger"))
        .or_else(|| user.and_then(|u| u.get("avatar_medium")))
        .or_else(|| user.and_then(|u| u.get("avatar_thumb")));

    let _avatar_url = avatar
        .and_then(|a| a.get("url_list"))
        .and_then(|v| v.as_array())
        .and_then(|list| list.first())
        .and_then(|v| v.as_str())
        .unwrap_or("");

    Some(ParsedComment {
        comment_id,
        parent_comment_id,
        content: map
            .get("text")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string(),
        username: user
            .and_then(|u| u.get("nickname"))
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string(),
        user_id: user
            .and_then(|u| u.get("uid"))
            .and_then(|v| v.as_str().map(|s| s.to_string()))
            .or_else(|| {
                user.and_then(|u| u.get("uid"))
                    .and_then(|v| v.as_i64())
                    .map(|n| n.to_string())
            })
            .unwrap_or_default(),
        sec_uid: user
            .and_then(|u| u.get("sec_uid"))
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string(),
        digg_count: map
            .get("digg_count")
            .and_then(|v| v.as_i64())
            .unwrap_or(0),
        create_time: map.get("create_time").and_then(|v| v.as_i64()),
        raw_json: serde_json::to_string(item).ok(),
    })
}

/// 从 `scroll_and_collect_comments` DOM 结果解析评论（任务入库兜底）。
pub fn parse_dom_scroll_comments(resp: &Value) -> Vec<ParsedComment> {
    let items = resp
        .get("comments")
        .or_else(|| resp.get("items"))
        .and_then(|v| v.as_array());
    let Some(items) = items else {
        return Vec::new();
    };

    let mut out = Vec::new();
    let mut seen = std::collections::HashSet::new();
    for (idx, item) in items.iter().enumerate() {
        let Some(map) = item.as_object() else {
            continue;
        };
        let content = map
            .get("content")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim()
            .to_string();
        if content.is_empty() || content == "—" {
            continue;
        }
        let author = map
            .get("author")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim()
            .to_string();
        let comment_id = map
            .get("comment_id")
            .and_then(|v| v.as_str())
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .map(str::to_string)
            .unwrap_or_else(|| {
                format!(
                    "dom_{:08x}",
                    stable_hash(&format!("{author}|{}", &content[..content.len().min(80)]))
                )
            });
        if !seen.insert(comment_id.clone()) {
            continue;
        }
        let user_url = map
            .get("user_url")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let (user_id, sec_uid) = parse_user_ids_from_url(user_url);
        out.push(ParsedComment {
            comment_id,
            parent_comment_id: None,
            content,
            username: author,
            user_id,
            sec_uid,
            digg_count: 0,
            create_time: map.get("create_time").and_then(|v| v.as_i64()),
            raw_json: serde_json::to_string(item).ok(),
        });
        if idx + 1 >= 300 {
            break;
        }
    }
    out
}

fn stable_hash(text: &str) -> u32 {
    let mut hash = 0_u32;
    for b in text.bytes() {
        hash = hash.wrapping_mul(31).wrapping_add(u32::from(b));
    }
    hash
}

fn parse_user_ids_from_url(url: &str) -> (String, String) {
    let mut user_id = String::new();
    let mut sec_uid = String::new();
    if let Some(query) = url.split('?').nth(1) {
        for pair in query.split('&') {
            if let Some((key, value)) = pair.split_once('=') {
                match key {
                    "uid" | "user_id" => user_id = value.to_string(),
                    "sec_uid" => sec_uid = value.to_string(),
                    _ => {}
                }
            }
        }
    }
    (user_id, sec_uid)
}

pub fn resolve_aweme_id_for_video(
    aweme_id: &str,
    video_url: &str,
    page_url: Option<&str>,
) -> String {
    if !is_dom_poster_aweme_id(aweme_id) && is_valid_aweme_id(aweme_id) {
        return aweme_id.to_string();
    }
    if let Some(id) = page_url.and_then(parse_aweme_id_from_page_url) {
        return id;
    }
    if !video_url.is_empty() {
        if let Some(id) = parse_aweme_id_from_page_url(video_url) {
            return id;
        }
    }
    aweme_id.to_string()
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn parses_search_aweme_info() {
        let body = json!({
            "data": [{
                "aweme_info": {
                    "aweme_id": "7123456789012345678",
                    "desc": "测试视频",
                    "author": { "nickname": "作者A" }
                }
            }]
        });
        let videos = parse_search_videos(&body);
        assert_eq!(videos.len(), 1);
        assert_eq!(videos[0].aweme_id, "7123456789012345678");
        assert_eq!(videos[0].title, "测试视频");
    }

    #[test]
    fn parses_aweme_from_video_page_url() {
        let url = "https://www.douyin.com/video/7123456789012345678";
        assert_eq!(
            parse_aweme_id_from_page_url(url).as_deref(),
            Some("7123456789012345678")
        );
    }

    #[test]
    fn parses_comment_list() {
        let body = json!({
            "aweme_id": "7123456789012345678",
            "comments": [{
                "cid": "123",
                "text": "好棒",
                "digg_count": 3,
                "create_time": 1710000000,
                "user": { "uid": "99", "nickname": "用户1", "sec_uid": "sec_1" }
            }]
        });
        let (aweme_id, comments) = parse_comment_list(&body, None);
        assert_eq!(aweme_id, "7123456789012345678");
        assert_eq!(comments.len(), 1);
        assert_eq!(comments[0].comment_id, "123");
        assert_eq!(comments[0].content, "好棒");
    }

    #[test]
    fn parses_dom_search_results() {
        let resp = json!({
            "items": [
                { "aweme_id": "7123456789012345678", "title": "健身", "author": "教练", "url": "https://www.douyin.com/video/7123456789012345678" },
                "7123456789012345679"
            ]
        });
        let videos = parse_dom_search_results(&resp);
        assert_eq!(videos.len(), 2);
        assert_eq!(videos[0].aweme_id, "7123456789012345678");
        assert_eq!(videos[1].aweme_id, "7123456789012345679");
    }

    #[test]
    fn parses_dom_poster_search_results() {
        let resp = json!({
            "items": [
                {
                    "index": 1,
                    "title": "健身教程",
                    "author": "教练A",
                    "aweme_id": null,
                    "click_by": "dom_rect",
                    "rect": { "top": 100, "left": 200, "width": 180, "height": 240 }
                }
            ]
        });
        let videos = parse_dom_search_results(&resp);
        assert_eq!(videos.len(), 1);
        assert_eq!(videos[0].aweme_id, "poster_00000001");
        assert!(videos[0].video_url.is_empty());
        let payload = dom_poster_click_payload(videos[0].raw_json.as_deref());
        assert_eq!(payload["video_index"], 1);
        assert_eq!(payload["rect"]["top"], 100);
    }

    #[test]
    fn parses_dom_scroll_comments() {
        let resp = json!({
            "comments": [
                {
                    "content": "求带",
                    "author": "用户A",
                    "comment_id": "c1",
                    "create_time": 1710000000
                }
            ]
        });
        let comments = parse_dom_scroll_comments(&resp);
        assert_eq!(comments.len(), 1);
        assert_eq!(comments[0].content, "求带");
        assert_eq!(comments[0].comment_id, "c1");
    }
}
