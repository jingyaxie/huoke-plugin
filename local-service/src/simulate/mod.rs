mod fixtures;
mod mock_client;

pub use fixtures::{SIM_VIDEO_IDS, sim_video_url};
pub use mock_client::run_mock_extension;

use std::time::Duration;

pub fn enabled() -> bool {
    std::env::var("HUOKE_SIMULATE")
        .ok()
        .map(|v| v == "1" || v.eq_ignore_ascii_case("true"))
        .unwrap_or(false)
}

/// 模拟模式下将长 sleep 压缩为毫秒级，便于无浏览器自动化测试。
pub async fn pause(duration: Duration) {
    if enabled() {
        tokio::time::sleep(Duration::from_millis(8)).await;
    } else {
        tokio::time::sleep(duration).await;
    }
}
