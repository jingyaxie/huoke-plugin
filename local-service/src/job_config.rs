use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::db::CollectJob;
use crate::filters;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PresetRef {
    pub id: String,
    #[serde(default)]
    pub content: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct InteractionSettings {
    #[serde(default = "default_interval_min")]
    pub comment_dm_interval_seconds_min: i64,
    #[serde(default = "default_interval_max")]
    pub comment_dm_interval_seconds_max: i64,
    #[serde(default = "default_percentage")]
    pub comment_dm_percentage: i64,
    #[serde(default = "default_follow_per_day")]
    pub follow_per_day: i64,
    #[serde(default = "default_dm_per_day")]
    pub dm_per_day: i64,
    #[serde(default = "default_batch_cooldown")]
    pub batch_cooldown_minutes: i64,
}

fn default_interval_min() -> i64 {
    10
}
fn default_interval_max() -> i64 {
    30
}
fn default_percentage() -> i64 {
    50
}
fn default_follow_per_day() -> i64 {
    30
}
fn default_dm_per_day() -> i64 {
    30
}
fn default_batch_cooldown() -> i64 {
    8
}

impl Default for InteractionSettings {
    fn default() -> Self {
        Self {
            comment_dm_interval_seconds_min: default_interval_min(),
            comment_dm_interval_seconds_max: default_interval_max(),
            comment_dm_percentage: default_percentage(),
            follow_per_day: default_follow_per_day(),
            dm_per_day: default_dm_per_day(),
            batch_cooldown_minutes: default_batch_cooldown(),
        }
    }
}

impl InteractionSettings {
    pub fn interval_ms_range(&self) -> (i64, i64) {
        let min = self.comment_dm_interval_seconds_min.clamp(1, 600) * 1000;
        let max = self
            .comment_dm_interval_seconds_max
            .clamp(self.comment_dm_interval_seconds_min, 600)
            * 1000;
        (min, max.max(min))
    }

}

#[derive(Debug, Clone, Default)]
pub struct EvaluationConfig {
    pub product_or_service: Option<String>,
    pub target_customer: Option<String>,
    pub accept_description: Option<String>,
    pub reject_signals: Vec<String>,
}

impl EvaluationConfig {
    pub fn from_config(cfg: &Value) -> Self {
        let eval = cfg.get("evaluation").unwrap_or(cfg);
        let reject_signals = eval
            .get("reject_signals")
            .and_then(|v| v.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|v| v.as_str().map(str::trim).filter(|s| !s.is_empty()))
                    .map(str::to_string)
                    .collect()
            })
            .unwrap_or_default();
        Self {
            product_or_service: eval
                .get("product_or_service")
                .and_then(|v| v.as_str())
                .map(str::trim)
                .filter(|s| !s.is_empty())
                .map(str::to_string),
            target_customer: eval
                .get("target_customer")
                .and_then(|v| v.as_str())
                .map(str::trim)
                .filter(|s| !s.is_empty())
                .map(str::to_string),
            accept_description: eval
                .get("accept_description")
                .and_then(|v| v.as_str())
                .map(str::trim)
                .filter(|s| !s.is_empty())
                .map(str::to_string),
            reject_signals,
        }
    }

    pub fn with_keyword_fallback(mut self, keyword: &str) -> Self {
        if self.product_or_service.is_none() {
            let kw = keyword.trim();
            if !kw.is_empty() {
                self.product_or_service = Some(kw.to_string());
            }
        }
        self
    }
}

#[derive(Debug, Clone)]
pub struct JobConfig {
    pub intent: String,
    pub input_url: Option<String>,
    pub region_code: Option<String>,
    pub region_name: Option<String>,
    pub publish_time_range: String,
    pub publish_days: Option<i64>,
    pub comment_days: i64,
    pub target_count: i64,
    pub interaction: InteractionSettings,
    pub comment_presets: Vec<PresetRef>,
    pub dm_presets: Vec<PresetRef>,
    pub auto_start: bool,
    pub auto_outreach: bool,
    pub evaluation: EvaluationConfig,
}

impl JobConfig {
    pub fn from_job(job: &CollectJob) -> Self {
        let cfg = job.config.as_ref().cloned().unwrap_or(Value::Null);
        Self::from_parts(
            &cfg,
            job.limit_videos,
            job.max_comments_per_video,
            &job.keyword,
        )
    }

    pub fn from_parts(
        cfg: &Value,
        limit_videos: i64,
        max_comments_per_video: i64,
        keyword: &str,
    ) -> Self {
        let intent = cfg
            .get("intent")
            .and_then(|v| v.as_str())
            .unwrap_or("keyword_auto")
            .to_string();
        let input_url = cfg
            .get("input_url")
            .and_then(|v| v.as_str())
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .map(str::to_string);
        let region_code = cfg
            .get("region_code")
            .and_then(|v| v.as_str())
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .map(str::to_string);
        let region_name = cfg
            .get("region_name")
            .and_then(|v| v.as_str())
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .map(str::to_string);
        let publish_time_range = cfg
            .get("publish_time_range")
            .and_then(|v| v.as_str())
            .unwrap_or("unlimited")
            .to_string();
        let publish_days = filters::map_publish_time_range(&publish_time_range);
        let comment_days = cfg
            .get("comment_days")
            .and_then(|v| v.as_i64())
            .unwrap_or(3);
        let target_count = cfg
            .get("target_count")
            .and_then(|v| v.as_i64())
            .unwrap_or(limit_videos * max_comments_per_video)
            .max(1);
        let interaction = cfg
            .get("interaction")
            .and_then(|v| serde_json::from_value(v.clone()).ok())
            .unwrap_or_default();
        let comment_presets = parse_presets(cfg, "comment_presets", "comment_preset_ids");
        let dm_presets = parse_presets(cfg, "dm_presets", "dm_preset_ids");
        let auto_start = cfg
            .get("auto_start")
            .and_then(|v| v.as_bool())
            .unwrap_or(false);
        let auto_outreach = cfg
            .get("auto_outreach")
            .and_then(|v| v.as_bool())
            .unwrap_or(true);
        let evaluation = EvaluationConfig::from_config(cfg).with_keyword_fallback(keyword);
        Self {
            intent,
            input_url,
            region_code,
            region_name,
            publish_time_range,
            publish_days,
            comment_days,
            target_count,
            interaction,
            comment_presets,
            dm_presets,
            auto_start,
            auto_outreach,
            evaluation,
        }
    }

    pub fn search_keyword(&self, keyword: &str) -> String {
        filters::composed_keyword(keyword, self.region_name.as_deref())
    }

    pub fn filter_publish_days_for_ui(&self) -> i64 {
        // unlimited → None → 0，不点发布时间筛选
        self.publish_days.unwrap_or(0)
    }

    pub fn has_reply_presets(&self) -> bool {
        self.comment_presets
            .iter()
            .any(|p| !p.content.trim().is_empty())
    }

    pub fn has_dm_presets(&self) -> bool {
        self.dm_presets.iter().any(|p| !p.content.trim().is_empty())
    }

    pub fn should_run_auto_outreach(&self) -> bool {
        if !self.auto_outreach {
            return false;
        }
        self.has_reply_presets()
            || self.has_dm_presets()
            || self.interaction.follow_per_day > 0
            || self.interaction.dm_per_day > 0
    }

    pub fn reply_templates(&self) -> Vec<String> {
        self.comment_presets
            .iter()
            .map(|p| p.content.trim().to_string())
            .filter(|s| !s.is_empty())
            .collect()
    }

    pub fn dm_templates(&self) -> Vec<String> {
        self.dm_presets
            .iter()
            .map(|p| p.content.trim().to_string())
            .filter(|s| !s.is_empty())
            .collect()
    }
}

fn parse_presets(cfg: &Value, array_key: &str, ids_key: &str) -> Vec<PresetRef> {
    if let Some(arr) = cfg.get(array_key).and_then(|v| v.as_array()) {
        return arr
            .iter()
            .filter_map(|row| {
                let id = row.get("id").and_then(|v| v.as_str())?.to_string();
                let content = row
                    .get("content")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string();
                Some(PresetRef { id, content })
            })
            .collect();
    }
    cfg.get(ids_key)
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str())
                .map(|id| PresetRef {
                    id: id.to_string(),
                    content: String::new(),
                })
                .collect()
        })
        .unwrap_or_default()
}

pub fn build_config_json(
    base: &Value,
    comment_presets: &[PresetRef],
    dm_presets: &[PresetRef],
) -> String {
    let mut obj = base
        .as_object()
        .cloned()
        .unwrap_or_default();
    if !comment_presets.is_empty() {
        obj.insert(
            "comment_presets".into(),
            serde_json::to_value(comment_presets).unwrap_or(Value::Null),
        );
    }
    if !dm_presets.is_empty() {
        obj.insert(
            "dm_presets".into(),
            serde_json::to_value(dm_presets).unwrap_or(Value::Null),
        );
    }
    serde_json::to_string(&Value::Object(obj)).unwrap_or_else(|_| "{}".into())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn parses_presets_with_content() {
        let cfg = json!({
            "target_count": 80,
            "comment_days": 5,
            "publish_time_range": "7d",
            "region_name": "深圳",
            "comment_presets": [{ "id": "p1", "content": "您好" }]
        });
        let job_cfg = JobConfig::from_parts(&cfg, 10, 8, "团餐");
        assert_eq!(job_cfg.target_count, 80);
        assert_eq!(job_cfg.comment_days, 5);
        assert_eq!(job_cfg.publish_days, Some(7));
        assert_eq!(job_cfg.search_keyword("团餐"), "深圳 团餐");
        assert!(job_cfg.has_reply_presets());
        assert!(job_cfg.should_run_auto_outreach());
    }

    #[test]
    fn unlimited_publish_skips_filter_days() {
        let cfg = json!({ "publish_time_range": "unlimited" });
        let job_cfg = JobConfig::from_parts(&cfg, 5, 10, "健身");
        assert_eq!(job_cfg.publish_days, None);
        assert_eq!(job_cfg.filter_publish_days_for_ui(), 0);
    }

    #[test]
    fn auto_outreach_with_dm_only() {
        let cfg = json!({
            "auto_outreach": true,
            "dm_presets": [{ "id": "d1", "content": "你好" }],
            "interaction": { "follow_per_day": 0 }
        });
        let job_cfg = JobConfig::from_parts(&cfg, 5, 10, "test");
        assert!(job_cfg.should_run_auto_outreach());
        assert!(!job_cfg.has_reply_presets());
        assert!(job_cfg.has_dm_presets());
    }

    #[test]
    fn auto_outreach_with_follow_quota_only() {
        let cfg = json!({
            "auto_outreach": true,
            "interaction": { "follow_per_day": 30, "dm_per_day": 0 }
        });
        let job_cfg = JobConfig::from_parts(&cfg, 5, 10, "test");
        assert!(job_cfg.should_run_auto_outreach());
    }
}
