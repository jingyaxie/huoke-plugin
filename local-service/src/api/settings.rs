use axum::{extract::State, Json};

use crate::llm_settings::{read_llm_settings, save_llm_settings, LlmSettingsOut, LlmSettingsUpdate, LlmSettingsUpdateResult};
use crate::state::AppState;

pub async fn get_llm_settings(State(state): State<AppState>) -> Json<LlmSettingsOut> {
    Json(read_llm_settings(&state.data_dir))
}

pub async fn put_llm_settings(
    State(state): State<AppState>,
    Json(payload): Json<LlmSettingsUpdate>,
) -> Result<Json<LlmSettingsUpdateResult>, (axum::http::StatusCode, String)> {
    match save_llm_settings(&state.data_dir, payload) {
        Ok(result) => Ok(Json(result)),
        Err(err) => Err((axum::http::StatusCode::INTERNAL_SERVER_ERROR, err)),
    }
}
