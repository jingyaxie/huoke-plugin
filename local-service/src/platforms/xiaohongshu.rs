use serde_json::Value;

use crate::douyin::parser::{ParsedComment, ParsedVideo};

use super::{PlatformCapabilities, PlatformCollectAdapter};

pub struct XiaohongshuCollectAdapter;

fn is_note_id(value: &str) -> bool {
    let len = value.len();
    len >= 16 && len <= 32 && value.chars().all(|c| c.is_ascii_hexdigit())
}

fn build_note_url(note_id: &str, xsec_token: Option<&str>, xsec_source: Option<&str>) -> String {
    let mut url = format!("https://www.xiaohongshu.com/explore/{note_id}");
    let mut params = Vec::new();
    if let Some(token) = xsec_token.filter(|s| !s.is_empty()) {
        params.push(format!("xsec_token={token}"));
    }
    if let Some(source) = xsec_source.filter(|s| !s.is_empty()) {
        params.push(format!("xsec_source={source}"));
    }
    if !params.is_empty() {
        url.push('?');
        url.push_str(&params.join("&"));
    }
    url
}

fn find_xsec(node: &Value) -> (Option<String>, Option<String>) {
    let mut token: Option<String> = None;
    let mut source: Option<String> = None;

    fn walk(node: &Value, token: &mut Option<String>, source: &mut Option<String>) {
        match node {
            Value::Object(map) => {
                if token.is_none() {
                    if let Some(raw) = map.get("xsec_token").or_else(|| map.get("xsecToken")) {
                        if let Some(s) = raw.as_str().map(str::trim).filter(|s| !s.is_empty()) {
                            *token = Some(s.to_string());
                        }
                    }
                }
                if source.is_none() {
                    if let Some(raw) = map.get("xsec_source").or_else(|| map.get("xsecSource")) {
                        if let Some(s) = raw.as_str().map(str::trim).filter(|s| !s.is_empty()) {
                            *source = Some(s.to_string());
                        }
                    }
                }
                for value in map.values() {
                    walk(value, token, source);
                }
            }
            Value::Array(list) => {
                for item in list {
                    walk(item, token, source);
                }
            }
            _ => {}
        }
    }

    walk(node, &mut token, &mut source);
    (token, source)
}

fn normalize_note_card(item: &Value, rank: usize) -> Option<ParsedVideo> {
    let obj = item.as_object()?;
    let card = obj
        .get("note_card")
        .or_else(|| obj.get("note"))
        .unwrap_or(item);
    let card_map = card.as_object()?;

    let note_id = card_map
        .get("note_id")
        .or_else(|| card_map.get("id"))
        .or_else(|| obj.get("note_id"))
        .or_else(|| obj.get("id"))
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_string();
    if !is_note_id(&note_id) {
        return None;
    }

    let user = card_map
        .get("user")
        .or_else(|| card_map.get("author"))
        .and_then(|v| v.as_object());
    let title = card_map
        .get("display_title")
        .or_else(|| card_map.get("title"))
        .or_else(|| card_map.get("desc"))
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_string();
    let title = if title.is_empty() {
        format!("小红书笔记 {}", &note_id[..note_id.len().min(8)])
    } else {
        title
    };
    let author = user
        .and_then(|u| u.get("nickname").or_else(|| u.get("nick_name")).or_else(|| u.get("name")))
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_string();

    let mut xsec_token = card_map
        .get("xsec_token")
        .or_else(|| obj.get("xsec_token"))
        .and_then(|v| v.as_str())
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_string);
    let mut xsec_source = card_map
        .get("xsec_source")
        .or_else(|| obj.get("xsec_source"))
        .and_then(|v| v.as_str())
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_string)
        .or_else(|| Some("pc_search".to_string()));
    if xsec_token.is_none() {
        let (nested_token, nested_source) = find_xsec(item);
        xsec_token = nested_token.or(xsec_token);
        xsec_source = nested_source.or(xsec_source);
    }

    Some(ParsedVideo {
        aweme_id: note_id.clone(),
        video_url: build_note_url(
            &note_id,
            xsec_token.as_deref(),
            xsec_source.as_deref(),
        ),
        title,
        author,
        raw_json: serde_json::to_string(item).ok(),
    })
}

fn walk_search_nodes(node: &Value, out: &mut Vec<ParsedVideo>, seen: &mut std::collections::HashSet<String>) {
    match node {
        Value::Object(map) => {
            if map.contains_key("note_card") || map.contains_key("note_id") || map.contains_key("noteId") {
                if let Some(video) = normalize_note_card(node, out.len() + 1) {
                    if seen.insert(video.aweme_id.clone()) {
                        out.push(video);
                    }
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

fn normalize_unix_seconds(value: Option<&Value>) -> Option<i64> {
    let ts = value.and_then(|v| v.as_i64())?;
    if ts <= 0 {
        return None;
    }
    if ts > 10_000_000_000 {
        Some(ts / 1000)
    } else {
        Some(ts)
    }
}

fn normalize_xhs_comment(item: &Value, parent_comment_id: Option<String>) -> Option<ParsedComment> {
    let map = item.as_object()?;
    let comment_id = map
        .get("id")
        .or_else(|| map.get("comment_id"))
        .or_else(|| map.get("commentId"))
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_string();
    if comment_id.is_empty() {
        return None;
    }
    let user = map
        .get("user_info")
        .or_else(|| map.get("user"))
        .and_then(|v| v.as_object());
    Some(ParsedComment {
        comment_id,
        parent_comment_id,
        content: map
            .get("content")
            .or_else(|| map.get("text"))
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string(),
        username: user
            .and_then(|u| u.get("nickname").or_else(|| u.get("nick_name")))
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string(),
        user_id: user
            .and_then(|u| u.get("user_id").or_else(|| u.get("userId")))
            .and_then(|v| v.as_str().map(str::to_string))
            .or_else(|| user.and_then(|u| u.get("user_id")).and_then(|v| v.as_i64()).map(|n| n.to_string()))
            .unwrap_or_default(),
        sec_uid: String::new(),
        avatar_url: user
            .and_then(|u| u.get("image").or_else(|| u.get("avatar")))
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string(),
        digg_count: map
            .get("like_count")
            .or_else(|| map.get("liked_count"))
            .and_then(|v| v.as_i64())
            .unwrap_or(0),
        create_time: normalize_unix_seconds(
            map.get("create_time").or_else(|| map.get("createTime")),
        ),
        raw_json: serde_json::to_string(item).ok(),
    })
}

impl PlatformCollectAdapter for XiaohongshuCollectAdapter {
    fn id(&self) -> &'static str {
        "xiaohongshu"
    }

    fn label(&self) -> &'static str {
        "小红书"
    }

    fn capabilities(&self) -> PlatformCapabilities {
        PlatformCapabilities {
            collect: true,
            outreach: false,
        }
    }

    fn supported_intents(&self) -> &'static [&'static str] {
        &["keyword_auto", "single_video", "account_home"]
    }

    fn network_hook_patterns(&self) -> &'static [&'static str] {
        &["/api/sns/web/", "edith.xiaohongshu.com"]
    }

    fn is_search_api(&self, url: &str) -> bool {
        let lower = url.to_lowercase();
        if lower.contains("login") || lower.contains("qrcode") || lower.contains("suggest") {
            return false;
        }
        lower.contains("/api/sns/web/v1/search/notes") || lower.contains("/search/notes")
    }

    fn is_profile_post_api(&self, url: &str) -> bool {
        let lower = url.to_lowercase();
        lower.contains("/api/sns/web/v1/user_posted") || lower.contains("/user_posted")
    }

    fn is_comment_api(&self, url: &str) -> bool {
        let lower = url.to_lowercase();
        lower.contains("/api/sns/web/v2/comment/page") || lower.contains("/comment/page")
    }

    fn parse_search_videos(&self, body: &Value) -> Vec<ParsedVideo> {
        let mut items = Vec::new();
        let mut seen = std::collections::HashSet::new();
        walk_search_nodes(body, &mut items, &mut seen);
        items
    }

    fn parse_comment_list(
        &self,
        body: &Value,
        fallback_content_id: Option<&str>,
    ) -> (String, Vec<ParsedComment>) {
        let note_id = fallback_content_id.unwrap_or("").to_string();
        let mut comments = Vec::new();
        let data = body.get("data").unwrap_or(body);
        let list = data
            .get("comments")
            .and_then(|v| v.as_array())
            .cloned()
            .unwrap_or_default();
        for row in list {
            if let Some(parsed) = normalize_xhs_comment(&row, None) {
                let parent_id = parsed.comment_id.clone();
                comments.push(parsed);
                if let Some(subs) = row.get("sub_comments").or_else(|| row.get("subComments")).and_then(|v| v.as_array()) {
                    for sub in subs {
                        if let Some(child) = normalize_xhs_comment(sub, Some(parent_id.clone())) {
                            comments.push(child);
                        }
                    }
                }
            }
        }
        (note_id, comments)
    }

    fn extract_content_id_from_url(&self, url: &str) -> Option<String> {
        for marker in ["/explore/", "/discovery/item/", "/note/"] {
            let pos = url.find(marker)?;
            let rest = &url[pos + marker.len()..];
            let id: String = rest
                .chars()
                .take_while(|c| c.is_ascii_hexdigit())
                .collect();
            if is_note_id(&id) {
                return Some(id);
            }
        }
        None
    }

    fn content_url(&self, content_id: &str) -> String {
        build_note_url(content_id, None, Some("pc_search"))
    }

    fn normalize_manual_open_url(&self, input_url: &str, _intent: &str) -> String {
        input_url.to_string()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn parses_note_card() {
        let body = json!({
            "note_card": {
                "note_id": "674a1b2c3d4e5f6071829304",
                "display_title": "测试笔记",
                "user": { "nickname": "作者A" },
                "xsec_token": "abc"
            }
        });
        let videos = XiaohongshuCollectAdapter.parse_search_videos(&body);
        assert_eq!(videos.len(), 1);
        assert_eq!(videos[0].aweme_id, "674a1b2c3d4e5f6071829304");
        assert!(videos[0].video_url.contains("xsec_token=abc"));
    }
}
