use serde_json::Value;

use crate::douyin::parser::{ParsedComment, ParsedVideo};

use super::{PlatformCapabilities, PlatformCollectAdapter};

pub struct KuaishouCollectAdapter;

fn is_photo_id(value: &str) -> bool {
    let len = value.len();
    len >= 8 && len <= 32 && value.chars().all(|c| c.is_ascii_alphanumeric())
}

fn build_video_url(photo_id: &str) -> String {
    format!("https://www.kuaishou.com/short-video/{photo_id}")
}

fn normalize_feed_item(feed: &Value) -> Option<ParsedVideo> {
    let obj = feed.as_object()?;
    let photo = obj.get("photo").unwrap_or(feed);
    let photo_map = photo.as_object()?;
    let author = obj
        .get("author")
        .and_then(|v| v.as_object())
        .cloned()
        .unwrap_or_default();

    let photo_id = photo_map
        .get("id")
        .or_else(|| photo_map.get("photoId"))
        .or_else(|| obj.get("photoId"))
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_string();
    if !is_photo_id(&photo_id) {
        return None;
    }

    let title = photo_map
        .get("caption")
        .or_else(|| photo_map.get("title"))
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_string();
    let title = if title.is_empty() {
        format!("快手视频 {}", &photo_id[..photo_id.len().min(8)])
    } else {
        title
    };
    let author_name = author
        .get("name")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_string();

    Some(ParsedVideo {
        aweme_id: photo_id.clone(),
        video_url: build_video_url(&photo_id),
        title,
        author: author_name,
        raw_json: serde_json::to_string(feed).ok(),
    })
}

fn walk_search_nodes(node: &Value, out: &mut Vec<ParsedVideo>, seen: &mut std::collections::HashSet<String>) {
    match node {
        Value::Object(map) => {
            if map.contains_key("photo") || map.contains_key("photoId") {
                if let Some(video) = normalize_feed_item(node) {
                    if seen.insert(video.aweme_id.clone()) {
                        out.push(video);
                    }
                }
            }
            if let Some(feeds) = map.get("feeds").and_then(|v| v.as_array()) {
                for feed in feeds {
                    if let Some(video) = normalize_feed_item(feed) {
                        if seen.insert(video.aweme_id.clone()) {
                            out.push(video);
                        }
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

fn normalize_ks_comment(item: &Value, parent_comment_id: Option<String>) -> Option<ParsedComment> {
    let map = item.as_object()?;
    let comment_id = map
        .get("commentId")
        .or_else(|| map.get("comment_id"))
        .or_else(|| map.get("id"))
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_string();
    if comment_id.is_empty() {
        return None;
    }
    let author = map.get("author").and_then(|v| v.as_object());
    let user_id = map
        .get("authorId")
        .or_else(|| map.get("author_id"))
        .or_else(|| author.and_then(|a| a.get("id")))
        .or_else(|| author.and_then(|a| a.get("authorId")))
        .and_then(|v| v.as_str().map(str::to_string))
        .unwrap_or_default();
    let mut create_time = map
        .get("timestamp")
        .or_else(|| map.get("create_time"))
        .and_then(|v| v.as_i64());
    if let Some(ts) = create_time {
        if ts > 10_000_000_000 {
            create_time = Some(ts / 1000);
        }
    }
    Some(ParsedComment {
        comment_id,
        parent_comment_id,
        content: map
            .get("content")
            .or_else(|| map.get("text"))
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string(),
        username: map
            .get("authorName")
            .or_else(|| map.get("author_name"))
            .or_else(|| author.and_then(|a| a.get("name")))
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string(),
        user_id,
        sec_uid: String::new(),
        avatar_url: map
            .get("headurl")
            .or_else(|| map.get("avatar"))
            .or_else(|| author.and_then(|a| a.get("headurl")))
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string(),
        digg_count: map
            .get("likedCount")
            .or_else(|| map.get("liked_count"))
            .and_then(|v| v.as_i64())
            .unwrap_or(0),
        create_time,
        raw_json: serde_json::to_string(item).ok(),
    })
}

fn walk_comment_nodes(node: &Value, out: &mut Vec<ParsedComment>, seen: &mut std::collections::HashSet<String>) {
    match node {
        Value::Object(map) => {
            if map.contains_key("commentId") || map.contains_key("comment_id") {
                if let Some(parsed) = normalize_ks_comment(node, None) {
                    if seen.insert(parsed.comment_id.clone()) {
                        out.push(parsed);
                    }
                }
            }
            if let Some(list) = map
                .get("rootComments")
                .or_else(|| map.get("comments"))
                .and_then(|v| v.as_array())
            {
                for row in list {
                    if let Some(parsed) = normalize_ks_comment(row, None) {
                        if seen.insert(parsed.comment_id.clone()) {
                            let parent_id = parsed.comment_id.clone();
                            out.push(parsed);
                            if let Some(subs) = row.get("subComments").and_then(|v| v.as_array()) {
                                for sub in subs {
                                    if let Some(child) = normalize_ks_comment(sub, Some(parent_id.clone())) {
                                        if seen.insert(child.comment_id.clone()) {
                                            out.push(child);
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
            for value in map.values() {
                walk_comment_nodes(value, out, seen);
            }
        }
        Value::Array(list) => {
            for item in list {
                walk_comment_nodes(item, out, seen);
            }
        }
        _ => {}
    }
}

impl PlatformCollectAdapter for KuaishouCollectAdapter {
    fn id(&self) -> &'static str {
        "kuaishou"
    }

    fn label(&self) -> &'static str {
        "快手"
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
        &["/graphql", "/rest/", "captcha"]
    }

    fn is_search_api(&self, url: &str) -> bool {
        let lower = url.to_lowercase();
        lower.contains("/rest/v/search/feed") || lower.contains("/search/feed")
    }

    fn is_profile_post_api(&self, url: &str) -> bool {
        let lower = url.to_lowercase();
        lower.contains("/rest/v/profile/feed") || lower.contains("/profile/feed")
    }

    fn is_comment_api(&self, url: &str) -> bool {
        let lower = url.to_lowercase();
        lower.contains("graphql") || lower.contains("comment")
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
        let photo_id = fallback_content_id.unwrap_or("").to_string();
        let mut comments = Vec::new();
        let mut seen = std::collections::HashSet::new();
        walk_comment_nodes(body, &mut comments, &mut seen);
        (photo_id, comments)
    }

    fn extract_content_id_from_url(&self, url: &str) -> Option<String> {
        for marker in ["/short-video/", "/fw/photo/"] {
            let pos = url.find(marker)?;
            let rest = &url[pos + marker.len()..];
            let id: String = rest
                .chars()
                .take_while(|c| c.is_ascii_alphanumeric() || *c == '_')
                .collect();
            if is_photo_id(&id) {
                return Some(id);
            }
        }
        None
    }

    fn content_url(&self, content_id: &str) -> String {
        build_video_url(content_id)
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
    fn parses_search_feed() {
        let body = json!({
            "feeds": [{
                "photo": { "id": "3xabc123def456", "caption": "测试视频" },
                "author": { "name": "作者B" }
            }]
        });
        let videos = KuaishouCollectAdapter.parse_search_videos(&body);
        assert_eq!(videos.len(), 1);
        assert_eq!(videos[0].aweme_id, "3xabc123def456");
    }
}
