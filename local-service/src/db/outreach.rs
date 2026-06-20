use rusqlite::{params, Connection};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use super::Database;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum OutreachTaskStatus {
    Pending,
    Running,
    Paused,
    Completed,
    Failed,
}

impl OutreachTaskStatus {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Pending => "pending",
            Self::Running => "running",
            Self::Paused => "paused",
            Self::Completed => "completed",
            Self::Failed => "failed",
        }
    }

    pub fn from_str(value: &str) -> Self {
        match value {
            "running" => Self::Running,
            "paused" => Self::Paused,
            "completed" => Self::Completed,
            "failed" => Self::Failed,
            _ => Self::Pending,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum OutreachItemStatus {
    Pending,
    Running,
    Completed,
    Failed,
    Skipped,
}

impl OutreachItemStatus {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Pending => "pending",
            Self::Running => "running",
            Self::Completed => "completed",
            Self::Failed => "failed",
            Self::Skipped => "skipped",
        }
    }

    pub fn from_str(value: &str) -> Self {
        match value {
            "running" => Self::Running,
            "completed" => Self::Completed,
            "failed" => Self::Failed,
            "skipped" => Self::Skipped,
            _ => Self::Pending,
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct OutreachTask {
    pub id: String,
    pub source_job_id: Option<String>,
    pub name: String,
    pub status: OutreachTaskStatus,
    pub max_retries: i64,
    pub interval_ms: i64,
    pub daily_quota: i64,
    pub error_message: Option<String>,
    pub completed_count: i64,
    pub failed_count: i64,
    pub pending_count: i64,
    pub created_at: i64,
    pub updated_at: i64,
}

#[derive(Debug, Clone, Serialize)]
pub struct OutreachItem {
    pub id: String,
    pub task_id: String,
    pub video_url: String,
    pub aweme_id: String,
    pub comment_id: String,
    pub comment_text: String,
    pub reply_text: String,
    pub status: OutreachItemStatus,
    pub attempts: i64,
    pub max_retries: i64,
    pub error_message: Option<String>,
    pub result_json: Option<String>,
    pub created_at: i64,
    pub updated_at: i64,
}

#[derive(Debug, Clone, Serialize)]
pub struct QuotaStatus {
    pub day: String,
    pub reply_count: i64,
    pub daily_limit: i64,
    pub remaining: i64,
}

impl Database {
    pub fn migrate_outreach(&self, conn: &Connection) -> Result<(), String> {
        conn.execute_batch(
            r#"
            CREATE TABLE IF NOT EXISTS outreach_tasks (
                id TEXT PRIMARY KEY,
                source_job_id TEXT,
                name TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                max_retries INTEGER NOT NULL DEFAULT 2,
                interval_ms INTEGER NOT NULL DEFAULT 4000,
                daily_quota INTEGER NOT NULL DEFAULT 50,
                error_message TEXT,
                completed_count INTEGER NOT NULL DEFAULT 0,
                failed_count INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS outreach_items (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                video_url TEXT NOT NULL,
                aweme_id TEXT NOT NULL DEFAULT '',
                comment_id TEXT NOT NULL,
                comment_text TEXT NOT NULL DEFAULT '',
                reply_text TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                max_retries INTEGER NOT NULL DEFAULT 2,
                error_message TEXT,
                result_json TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS outreach_quota (
                day TEXT PRIMARY KEY,
                reply_count INTEGER NOT NULL DEFAULT 0,
                daily_limit INTEGER NOT NULL DEFAULT 50
            );
            "#,
        )
        .map_err(|e| e.to_string())?;
        Ok(())
    }

    fn outreach_now_ms() -> i64 {
        use std::time::{SystemTime, UNIX_EPOCH};
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_millis() as i64)
            .unwrap_or(0)
    }

    fn today_key() -> String {
        chrono::Local::now().format("%Y-%m-%d").to_string()
    }

    pub fn get_quota_status(&self, daily_limit: i64) -> Result<QuotaStatus, String> {
        let day = Self::today_key();
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        let row = conn.query_row(
            "SELECT reply_count, daily_limit FROM outreach_quota WHERE day = ?1",
            params![day],
            |row| Ok((row.get::<_, i64>(0)?, row.get::<_, i64>(1)?)),
        );

        let (reply_count, limit) = match row {
            Ok((count, limit)) => (count, limit),
            Err(_) => (0, daily_limit),
        };

        let remaining = (limit - reply_count).max(0);
        Ok(QuotaStatus {
            day,
            reply_count,
            daily_limit: limit,
            remaining,
        })
    }

    pub fn consume_reply_quota(&self, daily_limit: i64) -> Result<bool, String> {
        let day = Self::today_key();
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        conn.execute(
            "INSERT INTO outreach_quota (day, reply_count, daily_limit) VALUES (?1, 0, ?2)
             ON CONFLICT(day) DO NOTHING",
            params![day, daily_limit],
        )
        .map_err(|e| e.to_string())?;

        let updated = conn.execute(
            "UPDATE outreach_quota
             SET reply_count = reply_count + 1
             WHERE day = ?1 AND reply_count < daily_limit",
            params![day],
        )
        .map_err(|e| e.to_string())?;
        Ok(updated > 0)
    }

    pub fn create_outreach_task(
        &self,
        name: &str,
        source_job_id: Option<&str>,
        max_retries: i64,
        interval_ms: i64,
        daily_quota: i64,
    ) -> Result<OutreachTask, String> {
        let id = Uuid::new_v4().to_string();
        let now = Self::outreach_now_ms();
        {
            let conn = self.conn.lock().map_err(|e| e.to_string())?;
            conn.execute(
                "INSERT INTO outreach_tasks
                 (id, source_job_id, name, status, max_retries, interval_ms, daily_quota, created_at, updated_at)
                 VALUES (?1, ?2, ?3, 'pending', ?4, ?5, ?6, ?7, ?7)",
                params![id, source_job_id, name, max_retries, interval_ms, daily_quota, now],
            )
            .map_err(|e| e.to_string())?;
        }
        self.get_outreach_task(&id)
    }

    pub fn add_outreach_items(&self, task_id: &str, items: &[OutreachItemDraft]) -> Result<usize, String> {
        if items.is_empty() {
            return Ok(0);
        }
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        let now = Self::outreach_now_ms();
        let task = conn.query_row(
            "SELECT max_retries FROM outreach_tasks WHERE id = ?1",
            params![task_id],
            |row| row.get::<_, i64>(0),
        )
        .map_err(|e| e.to_string())?;
        let mut inserted = 0usize;
        for item in items {
            let changed = conn.execute(
                "INSERT OR IGNORE INTO outreach_items
                 (id, task_id, video_url, aweme_id, comment_id, comment_text, reply_text, status, attempts, max_retries, created_at, updated_at)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, 'pending', 0, ?8, ?9, ?9)",
                params![
                    Uuid::new_v4().to_string(),
                    task_id,
                    item.video_url,
                    item.aweme_id,
                    item.comment_id,
                    item.comment_text,
                    item.reply_text,
                    task,
                    now,
                ],
            )
            .map_err(|e| e.to_string())?;
            if changed > 0 {
                inserted += 1;
            }
        }
        Ok(inserted)
    }

    pub fn list_outreach_tasks(&self, limit: i64) -> Result<Vec<OutreachTask>, String> {
        let rows = {
            let conn = self.conn.lock().map_err(|e| e.to_string())?;
            let mut stmt = conn
                .prepare(
                    "SELECT id, source_job_id, name, status, max_retries, interval_ms, daily_quota, error_message,
                            completed_count, failed_count, created_at, updated_at
                     FROM outreach_tasks ORDER BY created_at DESC LIMIT ?1",
                )
                .map_err(|e| e.to_string())?;
            let rows = stmt
                .query_map(params![limit], |row| {
                    Ok((
                        row.get::<_, String>(0)?,
                        row.get::<_, Option<String>>(1)?,
                        row.get::<_, String>(2)?,
                        row.get::<_, String>(3)?,
                        row.get::<_, i64>(4)?,
                        row.get::<_, i64>(5)?,
                        row.get::<_, i64>(6)?,
                        row.get::<_, Option<String>>(7)?,
                        row.get::<_, i64>(8)?,
                        row.get::<_, i64>(9)?,
                        row.get::<_, i64>(10)?,
                        row.get::<_, i64>(11)?,
                    ))
                })
                .map_err(|e| e.to_string())?;
            rows.map(|row| row.map_err(|e| e.to_string()))
                .collect::<Result<Vec<_>, _>>()?
        };

        let mut tasks = Vec::new();
        for row in rows {
            let pending_count = self.count_pending_items(&row.0)?;
            tasks.push(OutreachTask {
                id: row.0,
                source_job_id: row.1,
                name: row.2,
                status: OutreachTaskStatus::from_str(&row.3),
                max_retries: row.4,
                interval_ms: row.5,
                daily_quota: row.6,
                error_message: row.7,
                completed_count: row.8,
                failed_count: row.9,
                pending_count,
                created_at: row.10,
                updated_at: row.11,
            });
        }
        Ok(tasks)
    }

    fn count_pending_items(&self, task_id: &str) -> Result<i64, String> {
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        let count: i64 = conn
            .query_row(
                "SELECT COUNT(*) FROM outreach_items WHERE task_id = ?1 AND status = 'pending'",
                params![task_id],
                |row| row.get(0),
            )
            .map_err(|e| e.to_string())?;
        Ok(count)
    }

    pub fn get_outreach_task(&self, task_id: &str) -> Result<OutreachTask, String> {
        let row = {
            let conn = self.conn.lock().map_err(|e| e.to_string())?;
            conn.query_row(
                "SELECT id, source_job_id, name, status, max_retries, interval_ms, daily_quota, error_message,
                        completed_count, failed_count, created_at, updated_at
                 FROM outreach_tasks WHERE id = ?1",
                params![task_id],
                |row| {
                    Ok((
                        row.get::<_, String>(0)?,
                        row.get::<_, Option<String>>(1)?,
                        row.get::<_, String>(2)?,
                        row.get::<_, String>(3)?,
                        row.get::<_, i64>(4)?,
                        row.get::<_, i64>(5)?,
                        row.get::<_, i64>(6)?,
                        row.get::<_, Option<String>>(7)?,
                        row.get::<_, i64>(8)?,
                        row.get::<_, i64>(9)?,
                        row.get::<_, i64>(10)?,
                        row.get::<_, i64>(11)?,
                    ))
                },
            )
            .map_err(|e| e.to_string())?
        };
        let pending_count = self.count_pending_items(task_id)?;
        Ok(OutreachTask {
            id: row.0,
            source_job_id: row.1,
            name: row.2,
            status: OutreachTaskStatus::from_str(&row.3),
            max_retries: row.4,
            interval_ms: row.5,
            daily_quota: row.6,
            error_message: row.7,
            completed_count: row.8,
            failed_count: row.9,
            pending_count,
            created_at: row.10,
            updated_at: row.11,
        })
    }

    pub fn list_outreach_items(&self, task_id: &str, limit: i64) -> Result<Vec<OutreachItem>, String> {
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        let mut stmt = conn
            .prepare(
                "SELECT id, task_id, video_url, aweme_id, comment_id, comment_text, reply_text, status, attempts,
                        max_retries, error_message, result_json, created_at, updated_at
                 FROM outreach_items WHERE task_id = ?1 ORDER BY created_at ASC LIMIT ?2",
            )
            .map_err(|e| e.to_string())?;
        let rows = stmt
            .query_map(params![task_id, limit], map_outreach_item_row)
            .map_err(|e| e.to_string())?;
        rows.map(|row| row.map_err(|e| e.to_string())).collect()
    }

    pub fn update_outreach_task_status(
        &self,
        task_id: &str,
        status: OutreachTaskStatus,
        error_message: Option<&str>,
    ) -> Result<(), String> {
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        conn.execute(
            "UPDATE outreach_tasks SET status = ?1, error_message = ?2, updated_at = ?3 WHERE id = ?4",
            params![status.as_str(), error_message, Self::outreach_now_ms(), task_id],
        )
        .map_err(|e| e.to_string())?;
        Ok(())
    }

    pub fn next_pending_outreach_item(&self, task_id: &str) -> Result<Option<OutreachItem>, String> {
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        let row = conn.query_row(
            "SELECT id, task_id, video_url, aweme_id, comment_id, comment_text, reply_text, status, attempts,
                    max_retries, error_message, result_json, created_at, updated_at
             FROM outreach_items
             WHERE task_id = ?1 AND status = 'pending'
             ORDER BY created_at ASC LIMIT 1",
            params![task_id],
            map_outreach_item_row,
        );
        match row {
            Ok(item) => Ok(Some(item)),
            Err(rusqlite::Error::QueryReturnedNoRows) => Ok(None),
            Err(err) => Err(err.to_string()),
        }
    }

    pub fn mark_outreach_item_running(&self, item_id: &str) -> Result<(), String> {
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        conn.execute(
            "UPDATE outreach_items SET status = 'running', attempts = attempts + 1, updated_at = ?1 WHERE id = ?2",
            params![Self::outreach_now_ms(), item_id],
        )
        .map_err(|e| e.to_string())?;
        Ok(())
    }

    pub fn mark_outreach_item_completed(&self, item_id: &str, result_json: &str) -> Result<(), String> {
        let now = Self::outreach_now_ms();
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        let task_id: String = conn
            .query_row(
                "SELECT task_id FROM outreach_items WHERE id = ?1",
                params![item_id],
                |row| row.get(0),
            )
            .map_err(|e| e.to_string())?;
        conn.execute(
            "UPDATE outreach_items SET status = 'completed', result_json = ?1, error_message = NULL, updated_at = ?2 WHERE id = ?3",
            params![result_json, now, item_id],
        )
        .map_err(|e| e.to_string())?;
        conn.execute(
            "UPDATE outreach_tasks SET completed_count = completed_count + 1, updated_at = ?1 WHERE id = ?2",
            params![now, task_id],
        )
        .map_err(|e| e.to_string())?;
        Ok(())
    }

    pub fn mark_outreach_item_failed(
        &self,
        item_id: &str,
        error_message: &str,
        retryable: bool,
    ) -> Result<(), String> {
        let now = Self::outreach_now_ms();
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        let (task_id, attempts, max_retries): (String, i64, i64) = conn
            .query_row(
                "SELECT task_id, attempts, max_retries FROM outreach_items WHERE id = ?1",
                params![item_id],
                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
            )
            .map_err(|e| e.to_string())?;

        let next_status = if retryable && attempts < max_retries {
            "pending"
        } else {
            "failed"
        };

        conn.execute(
            "UPDATE outreach_items SET status = ?1, error_message = ?2, updated_at = ?3 WHERE id = ?4",
            params![next_status, error_message, now, item_id],
        )
        .map_err(|e| e.to_string())?;

        if next_status == "failed" {
            conn.execute(
                "UPDATE outreach_tasks SET failed_count = failed_count + 1, updated_at = ?1 WHERE id = ?2",
                params![now, task_id],
            )
            .map_err(|e| e.to_string())?;
        }
        Ok(())
    }

    pub fn outreach_task_has_pending(&self, task_id: &str) -> Result<bool, String> {
        Ok(self.count_pending_items(task_id)? > 0)
    }
}

#[derive(Debug, Clone)]
pub struct OutreachItemDraft {
    pub video_url: String,
    pub aweme_id: String,
    pub comment_id: String,
    pub comment_text: String,
    pub reply_text: String,
}

fn map_outreach_item_row(row: &rusqlite::Row<'_>) -> rusqlite::Result<OutreachItem> {
    Ok(OutreachItem {
        id: row.get(0)?,
        task_id: row.get(1)?,
        video_url: row.get(2)?,
        aweme_id: row.get(3)?,
        comment_id: row.get(4)?,
        comment_text: row.get(5)?,
        reply_text: row.get(6)?,
        status: OutreachItemStatus::from_str(&row.get::<_, String>(7)?),
        attempts: row.get(8)?,
        max_retries: row.get(9)?,
        error_message: row.get(10)?,
        result_json: row.get(11)?,
        created_at: row.get(12)?,
        updated_at: row.get(13)?,
    })
}
