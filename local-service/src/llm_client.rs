use serde::{Deserialize, Serialize};
use serde_json::Value;

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

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn parse_eval_batch_from_results_array() {
        let payload = json!({
            "results": [
                {"comment_id": "c1", "is_precise": true, "reason": "ok", "score": 0.9}
            ]
        });
        let rows = parse_eval_batch(&payload);
        assert_eq!(rows.len(), 1);
        assert!(rows[0].is_precise);
    }
}
