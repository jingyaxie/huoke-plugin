use std::path::Path;

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use crate::llm_settings::{deepseek_api_key_for_data_dir, read_llm_settings};

#[derive(Debug, Clone)]
pub struct LlmClient {
    api_key: String,
    base_url: String,
    model: String,
}

#[derive(Debug, Deserialize)]
struct ChatCompletionResponse {
    choices: Vec<ChatChoice>,
}

#[derive(Debug, Deserialize)]
struct ChatChoice {
    message: ChatMessage,
}

#[derive(Debug, Deserialize)]
struct ChatMessage {
    content: String,
}

impl LlmClient {
    pub fn from_data_dir(data_dir: &Path) -> Option<Self> {
        let settings = read_llm_settings(data_dir);
        if !settings.llm_configured {
            return None;
        }
        Some(Self {
            api_key: deepseek_api_key_for_data_dir(data_dir),
            base_url: settings.deepseek.base_url,
            model: settings.deepseek.model,
        })
    }

    pub async fn chat_json(&self, system: &str, user: &str) -> Result<Value, String> {
        let url = format!(
            "{}/chat/completions",
            self.base_url.trim_end_matches('/')
        );
        let body = json!({
            "model": self.model,
            "messages": [
                { "role": "system", "content": system },
                { "role": "user", "content": user },
            ],
            "temperature": 0.1,
            "response_format": { "type": "json_object" },
        });

        let client = reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(120))
            .build()
            .map_err(|e| e.to_string())?;

        let resp = client
            .post(&url)
            .bearer_auth(&self.api_key)
            .json(&body)
            .send()
            .await
            .map_err(|e| format!("LLM 请求失败: {e}"))?;

        let status = resp.status();
        let text = resp.text().await.map_err(|e| e.to_string())?;
        if !status.is_success() {
            return Err(format!("LLM HTTP {status}: {text}"));
        }

        let parsed: ChatCompletionResponse =
            serde_json::from_str(&text).map_err(|e| format!("LLM 响应解析失败: {e}"))?;
        let content = parsed
            .choices
            .first()
            .map(|c| c.message.content.trim())
            .filter(|s| !s.is_empty())
            .ok_or_else(|| "LLM 返回空内容".to_string())?;

        serde_json::from_str(content).map_err(|e| format!("LLM JSON 无效: {e}; raw={content}"))
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EvalResultItem {
    pub comment_id: String,
    pub is_precise: bool,
    #[serde(default)]
    pub reason: String,
    #[serde(default)]
    pub score: Option<f64>,
}

#[derive(Debug, Clone, Deserialize)]
struct EvalBatchResponse {
    #[serde(default)]
    results: Vec<EvalResultItem>,
}

pub fn parse_eval_batch(value: &Value) -> Vec<EvalResultItem> {
    if let Ok(batch) = serde_json::from_value::<EvalBatchResponse>(value.clone()) {
        if !batch.results.is_empty() {
            return batch.results;
        }
    }
    value
        .get("results")
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|row| serde_json::from_value(row.clone()).ok())
                .collect()
        })
        .unwrap_or_default()
}
