use std::fs;
use std::path::Path;

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BundleInfo {
    pub app_version: String,
    pub extension_version: String,
    pub local_service_version: String,
}

pub fn bundle_info_path(data_dir: &Path) -> std::path::PathBuf {
    data_dir.join("bundle-info.json")
}

pub fn read_bundle_info(data_dir: &Path) -> Option<BundleInfo> {
    let path = bundle_info_path(data_dir);
    let text = fs::read_to_string(path).ok()?;
    serde_json::from_str(&text).ok()
}

pub fn compare_versions(left: &str, right: &str) -> Option<std::cmp::Ordering> {
    let parse = |value: &str| -> Vec<u32> {
        value
            .split(|c: char| !c.is_ascii_digit())
            .filter(|part| !part.is_empty())
            .filter_map(|part| part.parse().ok())
            .collect()
    };
    let mut left_parts = parse(left);
    let mut right_parts = parse(right);
    let max_len = left_parts.len().max(right_parts.len());
    left_parts.resize(max_len, 0);
    right_parts.resize(max_len, 0);
    left_parts.partial_cmp(&right_parts)
}

pub fn versions_equal(left: &str, right: &str) -> bool {
    compare_versions(left, right) == Some(std::cmp::Ordering::Equal)
}

pub fn version_older_than(actual: &str, expected: &str) -> bool {
    matches!(
        compare_versions(actual, expected),
        Some(std::cmp::Ordering::Less)
    )
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ExtensionVersionStatus {
    pub app_version: Option<String>,
    pub expected_extension_version: Option<String>,
    pub installed_extension_version: Option<String>,
    pub connected_extension_version: Option<String>,
    pub connected_extension_build_id: Option<String>,
    pub extension_version_matched: bool,
    pub extension_version_message: Option<String>,
}

pub fn evaluate_extension_versions(
    bundle: Option<&BundleInfo>,
    installed_extension_version: Option<&str>,
    connected_extension_version: Option<&str>,
    connected_extension_build_id: Option<&str>,
) -> ExtensionVersionStatus {
    let expected = bundle.map(|info| info.extension_version.as_str());
    let app_version = bundle.map(|info| info.app_version.clone());

    let mut message: Option<String> = None;
    let mut matched = true;

    if let Some(expected_version) = expected {
        if let Some(connected) = connected_extension_version {
            if version_older_than(connected, expected_version) {
                matched = false;
                message = Some(format!(
                    "当前 Chrome 插件 v{connected} 低于 App 要求 v{expected_version}，请更新插件。"
                ));
            } else if !versions_equal(connected, expected_version) {
                matched = false;
                message = Some(format!(
                    "当前 Chrome 插件 v{connected} 与 App 要求 v{expected_version} 不一致，请更新插件。"
                ));
            }
        } else if let Some(installed) = installed_extension_version {
            if version_older_than(installed, expected_version)
                || !versions_equal(installed, expected_version)
            {
                matched = false;
                message = Some(format!(
                    "本地插件目录仍为 v{installed}，App 要求 v{expected_version}，请重启 App 或点击「启动浏览器插件」。"
                ));
            }
        }
    }

    ExtensionVersionStatus {
        app_version,
        expected_extension_version: expected.map(str::to_string),
        installed_extension_version: installed_extension_version.map(str::to_string),
        connected_extension_version: connected_extension_version.map(str::to_string),
        connected_extension_build_id: connected_extension_build_id.map(str::to_string),
        extension_version_matched: matched,
        extension_version_message: message,
    }
}

pub fn read_installed_extension_version(data_dir: &Path) -> Option<String> {
    let manifest = data_dir.join("extension").join("manifest.json");
    let text = fs::read_to_string(manifest).ok()?;
    let json: serde_json::Value = serde_json::from_str(&text).ok()?;
    json.get("version")
        .and_then(|v| v.as_str())
        .map(str::to_string)
}
