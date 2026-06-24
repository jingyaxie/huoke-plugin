use rusqlite::params;

use super::{CollectJob, Database};

pub const CONFIG_KEY: &str = "huoke_desktop";

pub fn migrate(conn: &rusqlite::Connection) -> Result<(), String> {
    let _ = conn.execute(
        "ALTER TABLE collect_jobs ADD COLUMN sync_pending INTEGER NOT NULL DEFAULT 0",
        [],
    );
    Ok(())
}

impl Database {
    pub fn cloud_sync_cloud_task_id(job: &CollectJob) -> Option<String> {
        job.config
            .as_ref()
            .and_then(|cfg| cfg.get(CONFIG_KEY))
            .and_then(|desktop| desktop.get("cloud_task_id"))
            .and_then(|value| value.as_str())
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .map(str::to_string)
    }

    pub fn cloud_sync_set_cloud_task_id(&self, job_id: &str, cloud_task_id: &str) -> Result<(), String> {
        let mut job = self.get_job(job_id)?;
        let mut config = job
            .config
            .take()
            .and_then(|value| value.as_object().cloned())
            .unwrap_or_default();
        let mut desktop = config
            .remove(CONFIG_KEY)
            .and_then(|value| value.as_object().cloned())
            .unwrap_or_default();
        desktop.insert(
            "cloud_task_id".into(),
            serde_json::Value::String(cloud_task_id.trim().to_string()),
        );
        desktop.insert(
            "local_job_id".into(),
            serde_json::Value::String(job_id.to_string()),
        );
        config.insert(CONFIG_KEY.into(), serde_json::Value::Object(desktop));
        let config_text = serde_json::to_string(&serde_json::Value::Object(config))
            .map_err(|e| e.to_string())?;
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        conn.execute(
            "UPDATE collect_jobs SET config_json = ?1, sync_pending = 1, updated_at = ?2 WHERE id = ?3",
            params![config_text, Self::now_ms(), job_id],
        )
        .map_err(|e| e.to_string())?;
        Ok(())
    }

    pub fn cloud_sync_mark_pending_if_linked(&self, job_id: &str) -> Result<(), String> {
        let job = self.get_job(job_id)?;
        if Self::cloud_sync_cloud_task_id(&job).is_none() {
            return Ok(());
        }
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        conn.execute(
            "UPDATE collect_jobs SET sync_pending = 1, updated_at = ?1 WHERE id = ?2",
            params![Self::now_ms(), job_id],
        )
        .map_err(|e| e.to_string())?;
        Ok(())
    }

    pub fn cloud_sync_clear_pending(&self, job_id: &str) -> Result<(), String> {
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        conn.execute(
            "UPDATE collect_jobs SET sync_pending = 0 WHERE id = ?1",
            params![job_id],
        )
        .map_err(|e| e.to_string())?;
        Ok(())
    }

    pub fn cloud_sync_list_pending_jobs(&self, limit: i64) -> Result<Vec<String>, String> {
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        let mut stmt = conn
            .prepare(
                "SELECT id FROM collect_jobs WHERE sync_pending = 1 ORDER BY updated_at ASC LIMIT ?1",
            )
            .map_err(|e| e.to_string())?;
        let rows = stmt
            .query_map(params![limit.clamp(1, 50)], |row| row.get::<_, String>(0))
            .map_err(|e| e.to_string())?;
        rows.map(|row| row.map_err(|e| e.to_string())).collect()
    }
}
