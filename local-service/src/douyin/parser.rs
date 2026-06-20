use serde_json::Value;

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
    for (key, value) in url
        .split('?')
        .nth(1)?
        .split('&')
        .filter_map(|pair| pair.split_once('='))
    {
        if key == "aweme_id" && !value.is_empty() {
            return Some(value.to_string());
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

fn is_valid_aweme_id(value: &str) -> bool {
    value.len() >= 8 && value.len() <= 22 && value.chars().all(|c| c.is_ascii_digit())
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
}
