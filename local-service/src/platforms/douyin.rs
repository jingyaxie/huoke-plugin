use serde_json::Value;

use crate::douyin::parser::{
    extract_aweme_id_from_url, is_comment_api, is_profile_post_api, is_search_api,
    parse_comment_list, parse_search_videos,
};

use super::{PlatformCapabilities, PlatformCollectAdapter};

pub struct DouyinCollectAdapter;

impl PlatformCollectAdapter for DouyinCollectAdapter {
    fn id(&self) -> &'static str {
        "douyin"
    }

    fn label(&self) -> &'static str {
        "抖音"
    }

    fn capabilities(&self) -> PlatformCapabilities {
        PlatformCapabilities {
            collect: true,
            outreach: true,
        }
    }

    fn supported_intents(&self) -> &'static [&'static str] {
        &["keyword_auto", "single_video", "account_home"]
    }

    fn network_hook_patterns(&self) -> &'static [&'static str] {
        &["/aweme/", "/comment/", "/search/"]
    }

    fn is_search_api(&self, url: &str) -> bool {
        is_search_api(url)
    }

    fn is_profile_post_api(&self, url: &str) -> bool {
        is_profile_post_api(url)
    }

    fn is_comment_api(&self, url: &str) -> bool {
        is_comment_api(url)
    }

    fn parse_search_videos(&self, body: &Value) -> Vec<crate::douyin::parser::ParsedVideo> {
        parse_search_videos(body)
    }

    fn parse_comment_list(
        &self,
        body: &Value,
        fallback_content_id: Option<&str>,
    ) -> (String, Vec<crate::douyin::parser::ParsedComment>) {
        parse_comment_list(body, fallback_content_id)
    }

    fn extract_content_id_from_url(&self, url: &str) -> Option<String> {
        extract_aweme_id_from_url(url)
    }

    fn content_url(&self, content_id: &str) -> String {
        format!("https://www.douyin.com/video/{content_id}")
    }

    fn normalize_manual_open_url(&self, input_url: &str, intent: &str) -> String {
        if intent != "account_home" {
            return input_url.to_string();
        }
        let base = input_url.split('#').next().unwrap_or(input_url);
        let (path, _query) = base.split_once('?').unwrap_or((base, ""));
        format!("{path}?from_tab_name=main")
    }
}
