use std::path::{Path, PathBuf};
use std::time::Duration;

use tokio::time;

use crate::db::Database;
use crate::llm_settings::read_backend_settings;

use super::{builder, client};

pub fn spawn(db: Database, data_dir: PathBuf) {
    tokio::spawn(async move {
        let mut interval = time::interval(Duration::from_secs(30));
        loop {
            interval.tick().await;
            if let Err(err) = run_cycle(&db, &data_dir).await {
                tracing::warn!("cloud sync cycle failed: {err}");
            }
        }
    });
}

async fn run_cycle(db: &Database, data_dir: &Path) -> Result<(), String> {
    let backend = read_backend_settings(data_dir);
    if !backend.configured {
        return Ok(());
    }
    let job_ids = db.cloud_sync_list_pending_jobs(20)?;
    for job_id in job_ids {
        if let Err(err) = sync_job(db, data_dir, &job_id).await {
            tracing::warn!("cloud sync job {job_id} failed: {err}");
        }
    }
    Ok(())
}

pub async fn sync_job(db: &Database, data_dir: &Path, job_id: &str) -> Result<(), String> {
    let backend = read_backend_settings(data_dir);
    if !backend.configured {
        return Ok(());
    }
    let job = db.get_job(job_id)?;
    let cloud_task_id = Database::cloud_sync_cloud_task_id(&job)
        .ok_or_else(|| "cloud_task_id_missing".to_string())?;
    let payload = builder::build_payload(db, &job, &cloud_task_id)?;
    client::push(&backend.base_url, &backend.access_token, &payload).await?;
    db.cloud_sync_clear_pending(job_id)?;
    tracing::info!(
        "cloud sync ok job={job_id} cloud_task={cloud_task_id} leads={}",
        payload
            .get("leads")
            .and_then(|value| value.as_array())
            .map(|rows| rows.len())
            .unwrap_or(0)
    );
    Ok(())
}
