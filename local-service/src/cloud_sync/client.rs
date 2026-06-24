use std::time::Duration;

use reqwest::Client;
use serde_json::Value;

pub const PUSH_PATH: &str = "/cloud-sync/push";

pub async fn push(base_url: &str, access_token: &str, payload: &Value) -> Result<(), String> {
    let url = format!("{}{}", base_url.trim_end_matches('/'), PUSH_PATH);
    let client = Client::builder()
        .timeout(Duration::from_secs(60))
        .build()
        .map_err(|err| err.to_string())?;
    let resp = client
        .post(url)
        .bearer_auth(access_token)
        .header("X-Client-Type", "pc")
        .json(payload)
        .send()
        .await
        .map_err(|err| format!("cloud sync request failed: {err}"))?;
    let status = resp.status();
    let text = resp.text().await.map_err(|err| err.to_string())?;
    if !status.is_success() {
        return Err(format!("cloud sync HTTP {status}: {text}"));
    }
    let parsed: Value = serde_json::from_str(&text).map_err(|err| format!("cloud sync parse failed: {err}"))?;
    let code = parsed.get("code").and_then(|value| value.as_i64()).unwrap_or(-1);
    if code != 0 {
        let message = parsed
            .get("message")
            .and_then(|value| value.as_str())
            .unwrap_or("unknown");
        return Err(format!("cloud sync rejected: {message}"));
    }
    Ok(())
}
