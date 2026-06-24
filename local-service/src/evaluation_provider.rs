use std::path::Path;

use serde_json::{json, Value};

use crate::db::CapturedComment;
use crate::job_config::EvaluationConfig;
use crate::llm_client::{parse_eval_batch, EvalResultItem};
use crate::llm_settings::read_backend_settings;

pub fn evaluation_ready(data_dir: &Path) -> bool {
    read_backend_settings(data_dir).configured
}

pub async fn evaluate_batch(
    data_dir: &Path,
    keyword: &str,
    eval_cfg: &EvaluationConfig,
    comments: &[CapturedComment],
) -> Result<Vec<EvalResultItem>, String> {
    let backend = read_backend_settings(data_dir);
    evaluate_batch_via_backend(&backend, keyword, eval_cfg, comments).await
}

async fn evaluate_batch_via_backend(
    backend: &crate::llm_settings::BackendSettings,
    keyword: &str,
    eval_cfg: &EvaluationConfig,
    comments: &[CapturedComment],
) -> Result<Vec<EvalResultItem>, String> {
    if !backend.configured {
        return Err("评论评估未就绪：请先登录盈小蚁，系统会自动同步后台访问令牌".to_string());
    }
    let url = format!(
        "{}/huoke-agent-bridge/comments/evaluate",
        backend.base_url.trim_end_matches('/')
    );
    let reject_signals: Vec<&str> = eval_cfg
        .reject_signals
        .iter()
        .map(String::as_str)
        .collect();
    let evaluation = json!({
        "product_or_service": eval_cfg.product_or_service,
        "target_customer": eval_cfg.target_customer,
        "accept_description": eval_cfg.accept_description,
        "reject_signals": reject_signals,
    });
    let comment_rows: Vec<Value> = comments
        .iter()
        .map(|c| {
            json!({
                "comment_id": c.comment_id,
                "content": c.content,
            })
        })
        .collect();
    let body = json!({
        "keyword": keyword,
        "evaluation": evaluation,
        "comments": comment_rows,
    });

    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(120))
        .build()
        .map_err(|e| e.to_string())?;

    let resp = client
        .post(&url)
        .bearer_auth(&backend.access_token)
        .json(&body)
        .send()
        .await
        .map_err(|e| format!("后台评估请求失败: {e}"))?;

    let status = resp.status();
    let text = resp.text().await.map_err(|e| e.to_string())?;
    if !status.is_success() {
        return Err(format!("后台评估 HTTP {status}: {text}"));
    }

    let parsed: Value = serde_json::from_str(&text).map_err(|e| format!("后台评估响应解析失败: {e}"))?;
    let code = parsed.get("code").and_then(|v| v.as_i64()).unwrap_or(-1);
    if code != 0 {
        let message = parsed
            .get("message")
            .and_then(|v| v.as_str())
            .unwrap_or("unknown");
        return Err(format!("后台评估失败: {message}"));
    }
    let data = parsed.get("data").cloned().unwrap_or(Value::Null);
    Ok(parse_eval_batch(&data))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::llm_client::parse_eval_batch;

    #[test]
    fn parse_backend_payload() {
        let payload = json!({
            "results": [
                {"comment_id": "c1", "is_precise": true, "reason": "询价", "score": 0.8}
            ]
        });
        let rows = parse_eval_batch(&payload);
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0].comment_id, "c1");
    }
}
