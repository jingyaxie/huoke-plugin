use crate::db::CapturedVideo;
use crate::douyin::parser::ParsedComment;

/// 视频发布时间筛选：与 Python `PUBLISH_TIME_RANGE_TO_DAYS` 对齐。
pub fn map_publish_time_range(value: &str) -> Option<i64> {
    match value.trim().to_lowercase().as_str() {
        "1d" => Some(1),
        "3d" => Some(3),
        "7d" => Some(7),
        "180d" => Some(180),
        "unlimited" | "" => None,
        _ => None,
    }
}

/// 去掉行政区划后缀，得到更易命中的搜索词（如「通州区」→「通州」）。
fn strip_admin_suffix(name: &str) -> String {
    let mut s = name.trim().to_string();
    for suf in [
        "维吾尔自治区",
        "壮族自治区",
        "回族自治区",
        "特别行政区",
        "自治区",
        "自治州",
        "自治县",
        "地区",
        "林区",
    ] {
        if s.ends_with(suf) && s.len() > suf.len() {
            return s[..s.len() - suf.len()].to_string();
        }
    }
    for suf in ["省", "市", "区", "县", "旗", "盟"] {
        if s.ends_with(suf) && s.len() > suf.len() {
            s = s[..s.len() - suf.len()].to_string();
            break;
        }
    }
    s
}

/// 地区搜索词：只取最后一级城市名并去后缀，
/// 避免把全路径（如「江苏省 南通市 通州区」）整体拼入导致搜不到内容。
fn region_search_token(region: &str) -> String {
    let leaf = region
        .split(|c: char| c.is_whitespace() || c == '·')
        .filter(|s| !s.trim().is_empty())
        .last()
        .unwrap_or("")
        .trim();
    if leaf.is_empty() {
        return String::new();
    }
    strip_admin_suffix(leaf)
}

/// 地域拼入搜索词：地区只取最后一级城市名（Python SearchFilterOptions.composed_keyword）。
pub fn composed_keyword(keyword: &str, region: Option<&str>) -> String {
    let kw = keyword.trim();
    let token = region.map(region_search_token).unwrap_or_default();
    if token.is_empty() {
        return kw.to_string();
    }
    if kw.contains(&token) {
        return kw.to_string();
    }
    format!("{token} {kw}")
}

pub fn within_days(create_time: Option<i64>, days: i64) -> bool {
    if days <= 0 {
        return true;
    }
    let Some(mut ts) = create_time else {
        return true;
    };
    if ts > 1_000_000_000_000 {
        ts /= 1000;
    }
    let cutoff = chrono::Utc::now().timestamp() - days * 86400;
    ts >= cutoff
}

fn region_tokens(region: &str) -> Vec<String> {
    let text = region.trim();
    if text.is_empty() {
        return vec![];
    }
    let mut tokens = vec![text.to_string()];
    for suffix in ["省", "市", "区", "县"] {
        if text.ends_with(suffix) && text.len() > suffix.len() {
            tokens.push(text[..text.len() - suffix.len()].to_string());
        }
    }
    if text.contains('·') {
        for part in text.split('·') {
            let p = part.trim();
            if !p.is_empty() {
                tokens.push(p.to_string());
            }
        }
    }
    tokens.sort();
    tokens.dedup();
    tokens
}

pub fn matches_region_text(text: &str, region: &str) -> bool {
    if region.trim().is_empty() {
        return true;
    }
    let haystack = text.to_lowercase();
    region_tokens(region)
        .iter()
        .any(|token| haystack.contains(&token.to_lowercase()))
}

pub fn matches_video_region(video: &CapturedVideo, region: Option<&str>) -> bool {
    let Some(region) = region.filter(|r| !r.trim().is_empty()) else {
        return true;
    };
    let blob = format!("{} {} {}", video.title, video.author, video.raw_text());
    matches_region_text(&blob, region)
}

pub fn filter_videos_by_region(mut videos: Vec<CapturedVideo>, region: Option<&str>) -> Vec<CapturedVideo> {
    if region.map(str::trim).unwrap_or("").is_empty() {
        return videos;
    }
    videos.retain(|v| matches_video_region(v, region));
    videos
}

pub fn filter_comments_by_days(comments: &[ParsedComment], comment_days: i64) -> Vec<ParsedComment> {
    if comment_days <= 0 {
        return comments.to_vec();
    }
    comments
        .iter()
        .filter(|c| within_days(c.create_time, comment_days))
        .cloned()
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn composed_keyword_adds_region() {
        assert_eq!(composed_keyword("团餐", Some("深圳")), "深圳 团餐");
        assert_eq!(composed_keyword("深圳团餐", Some("深圳")), "深圳团餐");
    }

    #[test]
    fn composed_keyword_uses_last_city_name() {
        // 只取最后一级城市名，不拼全路径
        assert_eq!(composed_keyword("团餐", Some("江苏省 南通市 通州区")), "通州 团餐");
        assert_eq!(composed_keyword("团餐", Some("通州区")), "通州 团餐");
        assert_eq!(composed_keyword("团餐", Some("南通市")), "南通 团餐");
        assert_eq!(composed_keyword("团餐", Some("广东")), "广东 团餐");
        // 兼容旧的 · 分隔
        assert_eq!(composed_keyword("团餐", Some("广东·深圳")), "深圳 团餐");
        // 无地区
        assert_eq!(composed_keyword("团餐", Some("")), "团餐");
        assert_eq!(composed_keyword("团餐", None), "团餐");
    }

    #[test]
    fn publish_time_mapping() {
        assert_eq!(map_publish_time_range("7d"), Some(7));
        assert_eq!(map_publish_time_range("unlimited"), None);
    }

    #[test]
    fn within_days_filters_old() {
        let old = chrono::Utc::now().timestamp() - 10 * 86400;
        assert!(!within_days(Some(old), 3));
        let recent = chrono::Utc::now().timestamp() - 86400;
        assert!(within_days(Some(recent), 3));
    }
}
