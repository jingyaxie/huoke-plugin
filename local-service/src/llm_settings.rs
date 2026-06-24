use std::collections::HashMap;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

const LLM_ENV_KEYS: &[&str] = &[
    "COMMENT_EVAL_PROVIDER",
    "AI_BACKEND_BASE_URL",
    "AI_BACKEND_ACCESS_TOKEN",
];

#[derive(Debug, Clone, Serialize)]
pub struct BackendSettingsOut {
    pub configured: bool,
    pub base_url: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub access_token_masked: Option<String>,
}

#[derive(Debug, Clone)]
pub struct BackendSettings {
    pub configured: bool,
    pub base_url: String,
    pub access_token: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct LlmSettingsOut {
    pub env_file: String,
    /// 兼容旧前端字段，等同 evaluation_ready
    pub llm_configured: bool,
    pub evaluation_ready: bool,
    pub backend: BackendSettingsOut,
}

#[derive(Debug, Deserialize, Default)]
pub struct LlmSettingsUpdate {
    #[serde(default)]
    pub deepseek_api_key: Option<String>,
    #[serde(default)]
    pub deepseek_base_url: Option<String>,
    #[serde(default)]
    pub deepseek_model: Option<String>,
    #[serde(default)]
    pub evaluation_provider: Option<String>,
    pub backend_base_url: Option<String>,
    pub backend_access_token: Option<String>,
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

fn backend_from_env(parsed: &HashMap<String, String>) -> BackendSettings {
    let base_url = parsed
        .get("AI_BACKEND_BASE_URL")
        .map(|s| s.trim().to_string())
        .unwrap_or_default();
    let access_token = parsed
        .get("AI_BACKEND_ACCESS_TOKEN")
        .map(|s| s.trim().to_string())
        .unwrap_or_default();
    let configured = !base_url.is_empty() && !access_token.is_empty();
    BackendSettings {
        configured,
        base_url,
        access_token,
    }
}

pub fn read_backend_settings(data_dir: &Path) -> BackendSettings {
    let parsed = parse_env_file(&resolve_llm_env_file(data_dir));
    backend_from_env(&parsed)
}

pub fn read_llm_settings(data_dir: &Path) -> LlmSettingsOut {
    let env_path = resolve_llm_env_file(data_dir);
    let parsed = parse_env_file(&env_path);
    let backend = backend_from_env(&parsed);
    let ready = backend.configured;
    LlmSettingsOut {
        env_file: env_path.display().to_string(),
        llm_configured: ready,
        evaluation_ready: ready,
        backend: BackendSettingsOut {
            configured: backend.configured,
            base_url: backend.base_url.clone(),
            access_token_masked: if backend.access_token.is_empty() {
                None
            } else {
                mask_api_key(&backend.access_token)
            },
        },
    }
}

fn build_env_updates(payload: &LlmSettingsUpdate) -> HashMap<String, Option<String>> {
    let mut updates = HashMap::new();
    if payload.backend_base_url.is_some()
        || payload.backend_access_token.is_some()
        || payload.evaluation_provider.is_some()
    {
        updates.insert(
            "COMMENT_EVAL_PROVIDER".to_string(),
            Some("backend".to_string()),
        );
    }
    if let Some(base_url) = &payload.backend_base_url {
        let trimmed = base_url.trim();
        updates.insert(
            "AI_BACKEND_BASE_URL".to_string(),
            if trimmed.is_empty() {
                None
            } else {
                Some(trimmed.to_string())
            },
        );
    }
    if let Some(token) = &payload.backend_access_token {
        let trimmed = token.trim();
        updates.insert(
            "AI_BACKEND_ACCESS_TOKEN".to_string(),
            if trimmed.is_empty() {
                None
            } else {
                Some(trimmed.to_string())
            },
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
    fn evaluation_not_ready_without_backend() {
        let tmp = std::env::temp_dir().join(format!("huoke-llm-empty-{}", uuid::Uuid::new_v4()));
        fs::create_dir_all(&tmp).unwrap();
        let env_path = tmp.join(".env.local");
        fs::write(&env_path, "# empty\n").unwrap();
        std::env::set_var("HUOKE_ENV_PATH", env_path.to_string_lossy().to_string());

        let payload = read_llm_settings(&tmp);
        assert!(!payload.evaluation_ready);
        assert!(!payload.llm_configured);

        std::env::remove_var("HUOKE_ENV_PATH");
        let _ = fs::remove_dir_all(tmp);
    }

    #[test]
    fn save_backend_roundtrip() {
        let tmp = std::env::temp_dir().join(format!("huoke-llm-backend-{}", uuid::Uuid::new_v4()));
        fs::create_dir_all(&tmp).unwrap();
        let env_path = tmp.join(".env.local");
        std::env::set_var("HUOKE_ENV_PATH", env_path.to_string_lossy().to_string());

        let result = save_llm_settings(
            &tmp,
            LlmSettingsUpdate {
                backend_base_url: Some("https://example.com/api".to_string()),
                backend_access_token: Some("token-abcdefgh".to_string()),
                ..Default::default()
            },
        )
        .unwrap();
        assert!(result.ok);
        assert!(result.llm_configured);

        let payload = read_llm_settings(&tmp);
        assert!(payload.evaluation_ready);
        assert!(payload.backend.configured);
        assert_eq!(payload.backend.base_url, "https://example.com/api");

        std::env::remove_var("HUOKE_ENV_PATH");
        let _ = fs::remove_dir_all(tmp);
    }
}
