use std::collections::HashSet;
use std::path::{Path, PathBuf};
use std::sync::LazyLock;
use std::time::Duration;

use tokio::sync::Mutex;
use tracing::{info, warn};

use crate::db::{CapturedComment, Database};
use crate::job_config::{EvaluationConfig, JobConfig};
use crate::llm_client::{parse_eval_batch, EvalResultItem, LlmClient};

const BATCH_SIZE: usize = 15;
const INGEST_EVAL_DEBOUNCE_MS: u64 = 1200;

static EVAL_IN_FLIGHT: LazyLock<Mutex<HashSet<String>>> =
    LazyLock::new(|| Mutex::new(HashSet::new()));

const SYSTEM_PROMPT: &str = r#"你是社交媒体评论线索评估助手。严格按任务给定的「线索识别标准」判断每条评论是否为精准客户。
只输出 JSON，格式：{"results":[{"comment_id":"...","is_precise":true/false,"reason":"简短中文说明","score":0.0-1.0}]}
规则：
- is_precise=true（精准客户）：评论与任务意图/评估标准吻合，表现出咨询、购买意向、使用需求、询价、预约，或像真实用户分享与产品相关的心得与痛点
- is_precise=false：无关内容、纯表情、同行广告、招聘、明显 spam、与任务完全无关
- reason 用一句话说明判断依据（引用评论中的关键信号）
- score 表示匹配度 0~1
- 必须为每条输入评论返回一条结果，comment_id 与输入完全一致"#;

/// 评论入库后异步触发评估（防抖合并短时间内的多次入库）
pub fn spawn_evaluate_job(db: Database, data_dir: PathBuf, job_id: String) {
    tokio::spawn(async move {
        tokio::time::sleep(Duration::from_millis(INGEST_EVAL_DEBOUNCE_MS)).await;
        {
            let mut in_flight = EVAL_IN_FLIGHT.lock().await;
            if in_flight.contains(&job_id) {
                return;
            }
            in_flight.insert(job_id.clone());
        }

        let result = async {
            let job = db.get_job(&job_id)?;
            let cfg = JobConfig::from_job(&job);
            evaluate_job_comments(
                &db,
                &data_dir,
                &job_id,
                &job.keyword,
                &cfg.evaluation,
            )
            .await
        }
        .await;

        match result {
            Ok(stats) if stats.evaluated > 0 => {
                info!(
                    "job {job_id}: ingest evaluation tagged {} precise / {} evaluated",
                    stats.precise, stats.evaluated
                );
            }
            Err(err) => warn!("job {job_id}: ingest evaluation failed: {err}"),
            _ => {}
        }

        EVAL_IN_FLIGHT.lock().await.remove(&job_id);
    });
}

pub struct EvaluationStats {
    pub evaluated: usize,
    pub precise: usize,
}

pub async fn evaluate_job_comments(
    db: &Database,
    data_dir: &Path,
    job_id: &str,
    keyword: &str,
    eval_cfg: &EvaluationConfig,
) -> Result<EvaluationStats, String> {
    let client = match LlmClient::from_data_dir(data_dir) {
        Some(c) => c,
        None => {
            info!("job {job_id}: LLM 未配置，跳过评论意图评估");
            return Ok(EvaluationStats {
                evaluated: 0,
                precise: 0,
            });
        }
    };

    let pending = db.list_unevaluated_comments(job_id, 2000)?;
    if pending.is_empty() {
        let precise = db.count_precise_comments_for_job(job_id)?;
        return Ok(EvaluationStats {
            evaluated: 0,
            precise: precise as usize,
        });
    }

    info!(
        "job {job_id}: evaluating {} comments with LLM",
        pending.len()
    );

    let mut evaluated = 0usize;
    let mut precise = 0usize;

    for chunk in pending.chunks(BATCH_SIZE) {
        let results = match evaluate_batch(&client, keyword, eval_cfg, chunk).await {
            Ok(rows) => rows,
            Err(err) => {
                warn!("job {job_id}: evaluation batch failed: {err}");
                continue;
            }
        };

        let now = Database::now_ms();
        for item in results {
            let is_prec = item.is_precise;
            if db
                .update_comment_evaluation(
                    job_id,
                    &item.comment_id,
                    is_prec,
                    &item.reason,
                    item.score,
                    now,
                )
                .unwrap_or(false)
            {
                evaluated += 1;
                if is_prec {
                    precise += 1;
                }
            }
        }
    }

    info!(
        "job {job_id}: evaluation done — evaluated={evaluated} precise={precise}"
    );
    Ok(EvaluationStats { evaluated, precise })
}

async fn evaluate_batch(
    client: &LlmClient,
    keyword: &str,
    eval_cfg: &EvaluationConfig,
    comments: &[CapturedComment],
) -> Result<Vec<EvalResultItem>, String> {
    let user_prompt = build_user_prompt(keyword, eval_cfg, comments);
    let value = client.chat_json(SYSTEM_PROMPT, &user_prompt).await?;
    Ok(parse_eval_batch(&value))
}

fn uses_experience_mode(eval_cfg: &EvaluationConfig) -> bool {
    eval_cfg.target_customer.as_ref().is_none_or(|s| s.trim().is_empty())
        && eval_cfg
            .accept_description
            .as_ref()
            .is_none_or(|s| s.trim().is_empty())
}

fn build_user_prompt(keyword: &str, eval_cfg: &EvaluationConfig, comments: &[CapturedComment]) -> String {
    let product = eval_cfg
        .product_or_service
        .as_deref()
        .filter(|s| !s.is_empty())
        .unwrap_or(keyword);
    let experience_mode = uses_experience_mode(eval_cfg);
    let target = eval_cfg
        .target_customer
        .as_deref()
        .filter(|s| !s.is_empty())
        .unwrap_or("未指定，请根据产品/服务推断");
    let accept = eval_cfg
        .accept_description
        .as_deref()
        .filter(|s| !s.is_empty())
        .unwrap_or(if experience_mode {
            "像真实用户分享与产品/服务相关的使用心得、体验感受，或表达咨询/购买意向、询问价格/效果/购买方式、描述自身需求或痛点"
        } else {
            "表达购买意向、咨询价格/联系方式、分享使用需求或痛点"
        });
    let reject = if eval_cfg.reject_signals.is_empty() {
        "同行广告、招聘、纯表情、无实质内容、与产品无关的闲聊".to_string()
    } else {
        eval_cfg.reject_signals.join("、")
    };

    let mut lines = vec![
        "## 线索识别标准".to_string(),
        format!("产品/服务：{product}"),
        format!("搜索关键词：{keyword}"),
        format!("目标客户：{target}"),
        format!("有效线索特征：{accept}"),
        format!("排除信号：{reject}"),
    ];
    if experience_mode {
        lines.push(String::new());
        lines.push("## 评估模式".to_string());
        lines.push(
            "未填写自定义标准，采用「使用心得」模式：优先识别像真实潜在客户的评论（体验分享、需求表达、咨询意向），排除灌水与无关内容。"
                .to_string(),
        );
    }
    lines.push(String::new());
    lines.push("## 待评估评论".to_string());

    for (idx, comment) in comments.iter().enumerate() {
        let content = comment.content.trim();
        let display = truncate_chars(content, 200);
        lines.push(format!(
            "{}. [comment_id:{}] {}",
            idx + 1,
            comment.comment_id,
            display
        ));
    }

    lines.join("\n")
}

fn truncate_chars(text: &str, max_chars: usize) -> String {
    if text.chars().count() <= max_chars {
        return text.to_string();
    }
    let trimmed: String = text.chars().take(max_chars).collect();
    format!("{trimmed}…")
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::job_config::EvaluationConfig;

    #[test]
    fn truncate_chars_respects_utf8_boundary() {
        let text = "以".repeat(120);
        let out = truncate_chars(&text, 100);
        assert!(out.ends_with('…'));
        assert!(out.chars().count() <= 101);
    }

    #[test]
    fn build_prompt_includes_comments() {
        let comments = vec![CapturedComment {
            id: "1".into(),
            job_id: "j1".into(),
            aweme_id: "v1".into(),
            comment_id: "c1".into(),
            parent_comment_id: None,
            content: "想咨询一下价格".into(),
            username: "user".into(),
            user_id: "u1".into(),
            sec_uid: String::new(),
            avatar_url: String::new(),
            digg_count: 0,
            create_time: None,
            created_at: 0,
            is_precise: false,
            evaluation_reason: String::new(),
            evaluation_score: None,
            evaluated_at: None,
        }];
        let cfg = EvaluationConfig {
            product_or_service: Some("团餐".into()),
            target_customer: None,
            accept_description: None,
            reject_signals: vec![],
        };
        let prompt = build_user_prompt("团餐", &cfg, &comments);
        assert!(prompt.contains("comment_id:c1"));
        assert!(prompt.contains("想咨询一下价格"));
    }

    #[test]
    fn build_prompt_uses_experience_mode_by_default() {
        let cfg = EvaluationConfig {
            product_or_service: Some("团餐".into()),
            target_customer: None,
            accept_description: None,
            reject_signals: vec![],
        };
        let prompt = build_user_prompt("团餐", &cfg, &[]);
        assert!(prompt.contains("使用心得"));
        assert!(prompt.contains("线索识别标准"));
    }
}
