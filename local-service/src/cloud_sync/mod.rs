use std::path::PathBuf;

use axum::{routing::post, Router};

use crate::state::AppState;

mod api;
mod builder;
mod client;
mod worker;

pub const CONFIG_KEY: &str = "huoke_desktop";

pub mod notify {
    use crate::db::Database;

    pub fn job_changed(db: &Database, job_id: &str) {
        let _ = db.cloud_sync_mark_pending_if_linked(job_id);
    }
}

/// 挂载 cloud-sync 路由并启动后台 worker。
pub fn bootstrap(app: Router, state: &AppState) -> Router {
    worker::spawn(state.db.clone(), state.data_dir.clone());
    app.merge(
        Router::new()
            .route(
                "/api/cloud-sync/jobs/:job_id/link",
                post(api::link_cloud_task),
            )
            .with_state(state.clone()),
    )
}

pub async fn sync_job_now(
    db: &crate::db::Database,
    data_dir: &PathBuf,
    job_id: &str,
) -> Result<(), String> {
    worker::sync_job(db, data_dir, job_id).await
}
