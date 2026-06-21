use axum::Json;
use serde_json::Value;

use crate::platforms;

pub async fn capabilities() -> Json<Value> {
    Json(platforms::list_platform_capabilities())
}
