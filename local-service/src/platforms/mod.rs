use serde_json::{json, Value};

use crate::douyin::parser::{ParsedComment, ParsedVideo};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PlatformCapabilities {
    pub collect: bool,
    pub outreach: bool,
}

/// 本机采集编排平台适配器（与 extension plugin-lab/platforms 对齐）
pub trait PlatformCollectAdapter: Send + Sync {
    fn id(&self) -> &'static str;
    fn label(&self) -> &'static str;
    fn capabilities(&self) -> PlatformCapabilities;
    fn supported_intents(&self) -> &'static [&'static str];
    fn network_hook_patterns(&self) -> &'static [&'static str];
    fn is_search_api(&self, url: &str) -> bool;
    fn is_profile_post_api(&self, url: &str) -> bool;
    fn is_comment_api(&self, url: &str) -> bool;
    fn parse_search_videos(&self, body: &Value) -> Vec<ParsedVideo>;
    fn parse_comment_list(
        &self,
        body: &Value,
        fallback_content_id: Option<&str>,
    ) -> (String, Vec<ParsedComment>);
    fn extract_content_id_from_url(&self, url: &str) -> Option<String>;
    fn content_url(&self, content_id: &str) -> String;
    fn normalize_manual_open_url(&self, input_url: &str, intent: &str) -> String;
}

mod douyin;
mod kuaishou;
mod xiaohongshu;

use douyin::DouyinCollectAdapter;
use kuaishou::KuaishouCollectAdapter;
use xiaohongshu::XiaohongshuCollectAdapter;

static ADAPTERS: [&dyn PlatformCollectAdapter; 3] = [
    &DouyinCollectAdapter,
    &XiaohongshuCollectAdapter,
    &KuaishouCollectAdapter,
];

pub fn normalize_platform(raw: &str) -> &'static str {
    match raw.trim().to_lowercase().as_str() {
        "xhs" | "xiaohongshu" | "redbook" => "xiaohongshu",
        "kuaishou" | "ks" => "kuaishou",
        _ => "douyin",
    }
}

pub fn get_platform_adapter(platform: &str) -> &'static dyn PlatformCollectAdapter {
    let id = normalize_platform(platform);
    ADAPTERS
        .iter()
        .find(|adapter| adapter.id() == id)
        .copied()
        .unwrap_or(&DouyinCollectAdapter)
}

pub fn assert_collect_supported(platform: &str) -> Result<(), String> {
    let adapter = get_platform_adapter(platform);
    if adapter.capabilities().collect {
        Ok(())
    } else {
        Err(format!(
            "platform {} extension collect is not supported yet",
            adapter.id()
        ))
    }
}

pub fn list_platform_capabilities() -> Value {
    json!({
        "platforms": ADAPTERS.iter().map(|adapter| json!({
            "id": adapter.id(),
            "label": adapter.label(),
            "collect": adapter.capabilities().collect,
            "outreach": adapter.capabilities().outreach,
            "intents": adapter.supported_intents(),
            "network_hook_patterns": adapter.network_hook_patterns(),
        })).collect::<Vec<_>>()
    })
}

/// 解析插件 lab 返回的搜索结果（items/results），兼容各平台 content_id 格式。
pub fn parse_plugin_lab_search_results(platform: &str, resp: &Value) -> Vec<ParsedVideo> {
    if normalize_platform(platform) == "douyin" {
        return crate::douyin::parser::parse_fetch_search_results(resp);
    }

    let adapter = get_platform_adapter(platform);
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
        let Some(obj) = item.as_object() else {
            continue;
        };
        let aweme_id = obj
            .get("aweme_id")
            .and_then(|v| v.as_str())
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .map(str::to_string)
            .or_else(|| adapter.extract_content_id_from_url(
                obj.get("url").and_then(|v| v.as_str()).unwrap_or(""),
            ))
            .unwrap_or_default();
        if aweme_id.is_empty() {
            continue;
        }
        if !seen.insert(aweme_id.clone()) {
            continue;
        }
        let title = obj
            .get("title")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim()
            .to_string();
        let author = obj
            .get("author")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim()
            .to_string();
        let video_url = obj
            .get("url")
            .and_then(|v| v.as_str())
            .filter(|s| !s.is_empty())
            .map(str::to_string)
            .unwrap_or_else(|| adapter.content_url(&aweme_id));
        out.push(ParsedVideo {
            aweme_id,
            video_url,
            title,
            author,
            raw_json: serde_json::to_string(obj).ok(),
        });
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn douyin_collect_supported() {
        assert!(get_platform_adapter("douyin").capabilities().collect);
    }

    #[test]
    fn xhs_collect_supported() {
        assert!(get_platform_adapter("xiaohongshu").capabilities().collect);
    }

    #[test]
    fn ks_collect_supported() {
        assert!(get_platform_adapter("kuaishou").capabilities().collect);
    }
}
