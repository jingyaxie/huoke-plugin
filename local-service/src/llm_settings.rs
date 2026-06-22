use std::collections::HashMap;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

const DEFAULT_DEEPSEEK_BASE_URL: &str = "https://api.deepseek.com/v1";
const DEFAULT_DEEPSEEK_MODEL: &str = "deepseek-chat";
/// 内置默认 Key，用户未配置 .env 时也可使用评论评估等 LLM 能力。
const DEFAULT_DEEPSEEK_API_KEY: &str = "sk-63aca3444e6d41c09fe3d53afd3444c9";

const LLM_ENV_KEYS: &[&str] = &[
    "AGENT_DEFAULT_PROVIDER",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_MODEL",
];

#[derive(Debug, Clone, Serialize)]
pub struct LlmProviderSettingsOut {
    pub configured: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub api_key_masked: Option<String>,
    pub base_url: String,
    pub model: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct LlmSettingsOut {
    pub env_file: String,
    pub deepseek: LlmProviderSettingsOut,
    pub llm_configured: bool,
}

#[derive(Debug, Deserialize)]
pub struct LlmSettingsUpdate {
    pub deepseek_api_key: Option<String>,
    pub deepseek_base_url: Option<String>,
    pub deepseek_model: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct LlmSettingsUpdateResult {
    pub ok: bool,
    pub llm_configured: bool,
    pub message: String,
}

pub fn mask_api_key(value: &str) -> Option<String> {
    let raw = value.trim();
    if raw.is_empty() {
        return None;
    }
    if raw.len() <= 8 {
        return Some("*".repeat(raw.len()));
    }
    Some(format!("{}***{}", &raw[..3], &raw[raw.len() - 4..]))
}

pub fn resolve_llm_env_file(data_dir: &Path) -> PathBuf {
    for key in ["HUOKE_ENV_PATH", "HUOKE_ENV_SIDECAR_PATH"] {
        if let Ok(explicit) = std::env::var(key) {
            let path = PathBuf::from(explicit.trim());
            if !path.as_os_str().is_empty() {
                return path;
            }
        }
    }
    if let Ok(desktop) = std::env::var("HUOKE_DESKTOP_MODE") {
        if desktop == "1" || desktop.eq_ignore_ascii_case("true") {
            if let Some(root) = data_dir.parent().and_then(|p| p.parent()) {
                return root.join(".env.desktop");
            }
        }
    }
    if let Some(root) = data_dir.parent().and_then(|p| p.parent()) {
        let local = root.join(".env.local");
        if local.is_file() {
            return local;
        }
        return local;
    }
    std::env::current_dir()
        .unwrap_or_else(|_| PathBuf::from("."))
        .join(".env.local")
}

fn parse_env_file(path: &Path) -> HashMap<String, String> {
    let mut out = HashMap::new();
    let Ok(content) = std::fs::read_to_string(path) else {
        return out;
    };
    for line in content.lines() {
        let stripped = line.trim();
        if stripped.is_empty() || stripped.starts_with('#') {
            continue;
        }
        let Some((key, value)) = stripped.split_once('=') else {
            continue;
        };
        let key = key.trim();
        if key.is_empty() {
            continue;
        }
        let mut raw = value.trim().to_string();
        if raw.len() >= 2 {
            let first = raw.chars().next().unwrap_or(' ');
            let last = raw.chars().last().unwrap_or(' ');
            if (first == '"' && last == '"') || (first == '\'' && last == '\'') {
                raw = raw[1..raw.len() - 1].to_string();
            }
        }
        out.insert(key.to_string(), raw);
    }
    out
}

fn quote_env_value(value: &str) -> String {
    if value.is_empty() {
        return "\"\"".to_string();
    }
    if value
        .chars()
        .any(|c| c.is_whitespace() || c == '#' || c == '"' || c == '\'')
    {
        let escaped = value.replace('\\', "\\\\").replace('"', "\\\"");
        return format!("\"{escaped}\"");
    }
    value.to_string()
}

fn write_env_updates(path: &Path, updates: &HashMap<String, Option<String>>) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    let mut lines: Vec<String> = Vec::new();
    let mut seen = std::collections::HashSet::new();
    if path.is_file() {
        let content = std::fs::read_to_string(path).map_err(|e| e.to_string())?;
        for line in content.lines() {
            let stripped = line.trim();
            if !stripped.is_empty()
                && !stripped.starts_with('#')
                && stripped.contains('=')
            {
                let key = stripped.split('=').next().unwrap_or("").trim();
                if updates.contains_key(key) {
                    seen.insert(key.to_string());
                    if let Some(Some(value)) = updates.get(key) {
                        let trimmed = value.trim();
                        if !trimmed.is_empty() {
                            lines.push(format!("{key}={}", quote_env_value(trimmed)));
                        }
                    }
                    continue;
                }
            }
            lines.push(line.to_string());
        }
    }
    for (key, value) in updates {
        if seen.contains(key) {
            continue;
        }
        let Some(raw) = value else { continue };
        let trimmed = raw.trim();
        if trimmed.is_empty() {
            continue;
        }
        lines.push(format!("{key}={}", quote_env_value(trimmed)));
    }
    let content = lines.join("\n").trim_end().to_string() + "\n";
    std::fs::write(path, content).map_err(|e| e.to_string())
}

fn effective_deepseek_api_key(parsed: &HashMap<String, String>) -> String {
    let raw = parsed
        .get("DEEPSEEK_API_KEY")
        .map(|s| s.as_str())
        .unwrap_or("")
        .trim();
    if raw.is_empty() {
        DEFAULT_DEEPSEEK_API_KEY.to_string()
    } else {
        raw.to_string()
    }
}

pub fn deepseek_api_key_for_data_dir(data_dir: &Path) -> String {
    let parsed = parse_env_file(&resolve_llm_env_file(data_dir));
    effective_deepseek_api_key(&parsed)
}

fn deepseek_from_env(parsed: &HashMap<String, String>) -> (String, String, String) {
    let api_key = effective_deepseek_api_key(parsed);
    let base_url = parsed
        .get("DEEPSEEK_BASE_URL")
        .filter(|v| !v.trim().is_empty())
        .cloned()
        .unwrap_or_else(|| DEFAULT_DEEPSEEK_BASE_URL.to_string());
    let model = parsed
        .get("DEEPSEEK_MODEL")
        .filter(|v| !v.trim().is_empty())
        .cloned()
        .unwrap_or_else(|| DEFAULT_DEEPSEEK_MODEL.to_string());
    (api_key, base_url, model)
}

pub fn read_llm_settings(data_dir: &Path) -> LlmSettingsOut {
    let env_path = resolve_llm_env_file(data_dir);
    let parsed = parse_env_file(&env_path);
    let (api_key, base_url, model) = deepseek_from_env(&parsed);
    let configured = !api_key.trim().is_empty();
    LlmSettingsOut {
        env_file: env_path.display().to_string(),
        deepseek: LlmProviderSettingsOut {
            configured,
            api_key_masked: if configured {
                mask_api_key(&api_key)
            } else {
                None
            },
            base_url,
            model,
        },
        llm_configured: configured,
    }
}

fn build_env_updates(payload: &LlmSettingsUpdate) -> HashMap<String, Option<String>> {
    let mut updates = HashMap::new();
    if let Some(base_url) = &payload.deepseek_base_url {
        let trimmed = base_url.trim();
        updates.insert(
            "DEEPSEEK_BASE_URL".to_string(),
            if trimmed.is_empty() {
                None
            } else {
                Some(trimmed.to_string())
            },
        );
    }
    if let Some(model) = &payload.deepseek_model {
        let trimmed = model.trim();
        updates.insert(
            "DEEPSEEK_MODEL".to_string(),
            if trimmed.is_empty() {
                None
            } else {
                Some(trimmed.to_string())
            },
        );
    }
    if let Some(api_key) = &payload.deepseek_api_key {
        let trimmed = api_key.trim();
        updates.insert(
            "DEEPSEEK_API_KEY".to_string(),
            if trimmed.is_empty() {
                None
            } else {
                Some(trimmed.to_string())
            },
        );
    }
    if !updates.is_empty() {
        updates.insert(
            "AGENT_DEFAULT_PROVIDER".to_string(),
            Some("deepseek".to_string()),
        );
    }
    updates
        .into_iter()
        .filter(|(key, _)| LLM_ENV_KEYS.contains(&key.as_str()))
        .collect()
}

pub fn save_llm_settings(data_dir: &Path, payload: LlmSettingsUpdate) -> Result<LlmSettingsUpdateResult, String> {
    let updates = build_env_updates(&payload);
    if updates.is_empty() {
        let current = read_llm_settings(data_dir);
        return Ok(LlmSettingsUpdateResult {
            ok: true,
            llm_configured: current.llm_configured,
            message: "无变更".to_string(),
        });
    }
    let env_path = resolve_llm_env_file(data_dir);
    write_env_updates(&env_path, &updates)?;
    let refreshed = read_llm_settings(data_dir);
    Ok(LlmSettingsUpdateResult {
        ok: true,
        llm_configured: refreshed.llm_configured,
        message: "已保存到本机配置并立即生效".to_string(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    #[test]
    fn mask_api_key_works() {
        assert_eq!(mask_api_key(""), None);
        assert_eq!(mask_api_key("sk-abcdefgh"), Some("sk-***efgh".to_string()));
    }

    #[test]
    fn default_api_key_when_env_empty() {
        let tmp = std::env::temp_dir().join(format!("huoke-llm-default-{}", uuid::Uuid::new_v4()));
        fs::create_dir_all(&tmp).unwrap();
        let env_path = tmp.join(".env.local");
        fs::write(&env_path, "# empty\n").unwrap();
        std::env::set_var("HUOKE_ENV_PATH", env_path.to_string_lossy().to_string());

        let payload = read_llm_settings(&tmp);
        assert!(payload.llm_configured);
        assert!(payload.deepseek.configured);
        assert_eq!(
            deepseek_api_key_for_data_dir(&tmp),
            DEFAULT_DEEPSEEK_API_KEY
        );

        std::env::remove_var("HUOKE_ENV_PATH");
        let _ = fs::remove_dir_all(tmp);
    }

    #[test]
    fn save_and_read_roundtrip() {
        let tmp = std::env::temp_dir().join(format!("huoke-llm-{}", uuid::Uuid::new_v4()));
        fs::create_dir_all(&tmp).unwrap();
        let env_path = tmp.join(".env.local");
        std::env::set_var("HUOKE_ENV_PATH", env_path.to_string_lossy().to_string());

        let result = save_llm_settings(
            &tmp,
            LlmSettingsUpdate {
                deepseek_api_key: Some("sk-test-deepseek-key".to_string()),
                deepseek_base_url: None,
                deepseek_model: Some("deepseek-chat".to_string()),
            },
        )
        .unwrap();
        assert!(result.ok);
        assert!(result.llm_configured);

        let payload = read_llm_settings(&tmp);
        assert!(payload.llm_configured);
        assert!(payload.deepseek.configured);
        assert_eq!(payload.deepseek.api_key_masked, Some("sk-***-key".to_string()));
        assert_eq!(payload.deepseek.model, "deepseek-chat");

        std::env::remove_var("HUOKE_ENV_PATH");
        let _ = fs::remove_dir_all(tmp);
    }
}
