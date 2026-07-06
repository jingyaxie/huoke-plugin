use rusqlite::{params, Connection};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use super::{CapturedComment, Database};

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
    pub platform: String,
    pub action_type: String,
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
    pub platform: String,
    pub action_type: String,
    pub source_job_id: Option<String>,
    pub video_url: String,
    pub aweme_id: String,
    pub comment_id: String,
    pub comment_text: String,
    pub username: String,
    pub user_id: String,
    pub sec_uid: String,
    pub profile_url: String,
    pub reply_text: String,
    pub dm_text: String,
    pub status: OutreachItemStatus,
    pub attempts: i64,
    pub max_retries: i64,
    pub error_message: Option<String>,
    pub result_json: Option<String>,
    pub created_at: i64,
    pub updated_at: i64,
}

#[derive(Debug, Clone, Serialize)]
pub struct OutreachCandidate {
    pub job_id: String,
    pub job_name: String,
    pub platform: String,
    pub aweme_id: String,
    pub video_url: String,
    pub comment_id: String,
    pub comment_text: String,
    pub username: String,
    pub user_id: String,
    pub sec_uid: String,
    pub avatar_url: String,
    pub profile_url: String,
    pub digg_count: i64,
    pub create_time: Option<i64>,
    pub evaluation_reason: String,
    pub evaluation_score: Option<f64>,
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
                platform TEXT NOT NULL DEFAULT 'douyin',
                action_type TEXT NOT NULL DEFAULT 'reply',
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
                platform TEXT NOT NULL DEFAULT 'douyin',
                action_type TEXT NOT NULL DEFAULT 'reply',
                source_job_id TEXT,
                video_url TEXT NOT NULL,
                aweme_id TEXT NOT NULL DEFAULT '',
                comment_id TEXT NOT NULL,
                comment_text TEXT NOT NULL DEFAULT '',
                username TEXT NOT NULL DEFAULT '',
                user_id TEXT NOT NULL DEFAULT '',
                sec_uid TEXT NOT NULL DEFAULT '',
                profile_url TEXT NOT NULL DEFAULT '',
                reply_text TEXT NOT NULL,
                dm_text TEXT NOT NULL DEFAULT '',
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
        let _ = conn.execute("ALTER TABLE outreach_tasks ADD COLUMN platform TEXT NOT NULL DEFAULT 'douyin'", []);
        let _ = conn.execute("ALTER TABLE outreach_tasks ADD COLUMN action_type TEXT NOT NULL DEFAULT 'reply'", []);
        let _ = conn.execute("ALTER TABLE outreach_items ADD COLUMN platform TEXT NOT NULL DEFAULT 'douyin'", []);
        let _ = conn.execute("ALTER TABLE outreach_items ADD COLUMN action_type TEXT NOT NULL DEFAULT 'reply'", []);
        let _ = conn.execute("ALTER TABLE outreach_items ADD COLUMN source_job_id TEXT", []);
        let _ = conn.execute("ALTER TABLE outreach_items ADD COLUMN username TEXT NOT NULL DEFAULT ''", []);
        let _ = conn.execute("ALTER TABLE outreach_items ADD COLUMN user_id TEXT NOT NULL DEFAULT ''", []);
        let _ = conn.execute("ALTER TABLE outreach_items ADD COLUMN sec_uid TEXT NOT NULL DEFAULT ''", []);
        let _ = conn.execute("ALTER TABLE outreach_items ADD COLUMN profile_url TEXT NOT NULL DEFAULT ''", []);
        let _ = conn.execute("ALTER TABLE outreach_items ADD COLUMN dm_text TEXT NOT NULL DEFAULT ''", []);
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
        platform: &str,
        action_type: &str,
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
                 (id, source_job_id, platform, action_type, name, status, max_retries, interval_ms, daily_quota, created_at, updated_at)
                 VALUES (?1, ?2, ?3, ?4, ?5, 'pending', ?6, ?7, ?8, ?9, ?9)",
                params![id, source_job_id, platform, action_type, name, max_retries, interval_ms, daily_quota, now],
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
                 (id, task_id, platform, action_type, source_job_id, video_url, aweme_id, comment_id, comment_text, username, user_id, sec_uid, profile_url, reply_text, dm_text, status, attempts, max_retries, created_at, updated_at)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15, 'pending', 0, ?16, ?17, ?17)",
                params![
                    Uuid::new_v4().to_string(),
                    task_id,
                    item.platform,
                    item.action_type,
                    item.source_job_id,
                    item.video_url,
                    item.aweme_id,
                    item.comment_id,
                    item.comment_text,
                    item.username,
                    item.user_id,
                    item.sec_uid,
                    item.profile_url,
                    item.reply_text,
                    item.dm_text,
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
                    "SELECT id, source_job_id, platform, action_type, name, status, max_retries, interval_ms, daily_quota, error_message,
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
                        row.get::<_, String>(4)?,
                        row.get::<_, String>(5)?,
                        row.get::<_, i64>(6)?,
                        row.get::<_, i64>(7)?,
                        row.get::<_, i64>(8)?,
                        row.get::<_, Option<String>>(9)?,
                        row.get::<_, i64>(10)?,
                        row.get::<_, i64>(11)?,
                        row.get::<_, i64>(12)?,
                        row.get::<_, i64>(13)?,
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
                platform: row.2,
                action_type: row.3,
                name: row.4,
                status: OutreachTaskStatus::from_str(&row.5),
                max_retries: row.6,
                interval_ms: row.7,
                daily_quota: row.8,
                error_message: row.9,
                completed_count: row.10,
                failed_count: row.11,
                pending_count,
                created_at: row.12,
                updated_at: row.13,
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
                "SELECT id, source_job_id, platform, action_type, name, status, max_retries, interval_ms, daily_quota, error_message,
                        completed_count, failed_count, created_at, updated_at
                 FROM outreach_tasks WHERE id = ?1",
                params![task_id],
                |row| {
                    Ok((
                        row.get::<_, String>(0)?,
                        row.get::<_, Option<String>>(1)?,
                        row.get::<_, String>(2)?,
                        row.get::<_, String>(3)?,
                        row.get::<_, String>(4)?,
                        row.get::<_, String>(5)?,
                        row.get::<_, i64>(6)?,
                        row.get::<_, i64>(7)?,
                        row.get::<_, i64>(8)?,
                        row.get::<_, Option<String>>(9)?,
                        row.get::<_, i64>(10)?,
                        row.get::<_, i64>(11)?,
                        row.get::<_, i64>(12)?,
                        row.get::<_, i64>(13)?,
                    ))
                },
            )
            .map_err(|e| e.to_string())?
        };
        let pending_count = self.count_pending_items(task_id)?;
        Ok(OutreachTask {
            id: row.0,
            source_job_id: row.1,
            platform: row.2,
            action_type: row.3,
            name: row.4,
            status: OutreachTaskStatus::from_str(&row.5),
            max_retries: row.6,
            interval_ms: row.7,
            daily_quota: row.8,
            error_message: row.9,
            completed_count: row.10,
            failed_count: row.11,
            pending_count,
            created_at: row.12,
            updated_at: row.13,
        })
    }

    pub fn list_outreach_items(&self, task_id: &str, limit: i64) -> Result<Vec<OutreachItem>, String> {
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        let mut stmt = conn
            .prepare(
                "SELECT id, task_id, platform, action_type, source_job_id, video_url, aweme_id, comment_id, comment_text, username, user_id, sec_uid, profile_url, reply_text, dm_text, status, attempts,
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
            "SELECT id, task_id, platform, action_type, source_job_id, video_url, aweme_id, comment_id, comment_text, username, user_id, sec_uid, profile_url, reply_text, dm_text, status, attempts,
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

    pub fn list_outreach_candidates(
        &self,
        platform: Option<&str>,
        source_job_id: Option<&str>,
        limit: i64,
        include_contacted: bool,
    ) -> Result<Vec<OutreachCandidate>, String> {
        let platform_filter = platform.map(str::trim).filter(|s| !s.is_empty());
        let job_filter = source_job_id.map(str::trim).filter(|s| !s.is_empty());
        let raw_rows = {
            let conn = self.conn.lock().map_err(|e| e.to_string())?;
            let mut stmt = conn
                .prepare(
                    "SELECT c.id, c.job_id, c.aweme_id, c.comment_id, c.parent_comment_id, c.content,
                            c.username, c.user_id, c.sec_uid, c.avatar_url, c.digg_count, c.create_time,
                            c.created_at, c.is_precise, c.evaluation_reason, c.evaluation_score, c.evaluated_at,
                            j.name, j.keyword, j.platform, COALESCE(v.video_url, '')
                     FROM captured_comments c
                     JOIN collect_jobs j ON j.id = c.job_id
                     LEFT JOIN captured_videos v ON v.job_id = c.job_id AND v.aweme_id = c.aweme_id
                     WHERE c.is_precise = 1
                       AND c.parent_comment_id IS NULL
                       AND j.status = 'completed'
                       AND (?1 IS NULL OR j.platform = ?1)
                       AND (?2 IS NULL OR c.job_id = ?2)
                     ORDER BY COALESCE(c.evaluation_score, 0) DESC, c.create_time DESC
                     LIMIT ?3",
                )
                .map_err(|e| e.to_string())?;
            let rows = stmt
                .query_map(params![platform_filter, job_filter, limit.clamp(1, 1000)], |row| {
                    Ok((
                        CapturedComment {
                            id: row.get(0)?,
                            job_id: row.get(1)?,
                            aweme_id: row.get(2)?,
                            comment_id: row.get(3)?,
                            parent_comment_id: row.get(4)?,
                            content: row.get(5)?,
                            username: row.get(6)?,
                            user_id: row.get(7)?,
                            sec_uid: row.get(8)?,
                            avatar_url: row.get(9)?,
                            digg_count: row.get(10)?,
                            create_time: row.get(11)?,
                            created_at: row.get(12)?,
                            is_precise: row.get::<_, i64>(13)? != 0,
                            evaluation_reason: row.get(14)?,
                            evaluation_score: row.get(15)?,
                            evaluated_at: row.get(16)?,
                        },
                        row.get::<_, String>(17)?,
                        row.get::<_, String>(18)?,
                        row.get::<_, String>(19)?,
                        row.get::<_, String>(20)?,
                    ))
                })
                .map_err(|e| e.to_string())?;
            rows.map(|row| row.map_err(|e| e.to_string()))
                .collect::<Result<Vec<_>, _>>()?
        };

        let mut out = Vec::new();
        for (comment, job_name, keyword, platform, video_url) in raw_rows {
            let profile_url = profile_url_for_comment(&platform, &comment);
            if profile_url.is_empty() {
                continue;
            }
            let contacted = self.user_has_completed_outreach(&comment.user_id, &comment.sec_uid)?;
            if contacted && !include_contacted {
                continue;
            }
            out.push(OutreachCandidate {
                job_id: comment.job_id,
                job_name: if job_name.trim().is_empty() { keyword } else { job_name },
                platform,
                aweme_id: comment.aweme_id,
                video_url,
                comment_id: comment.comment_id,
                comment_text: comment.content,
                username: comment.username,
                user_id: comment.user_id,
                sec_uid: comment.sec_uid,
                avatar_url: comment.avatar_url,
                profile_url,
                digg_count: comment.digg_count,
                create_time: comment.create_time,
                evaluation_reason: comment.evaluation_reason,
                evaluation_score: comment.evaluation_score,
            });
        }
        Ok(out)
    }

    fn user_has_completed_outreach(&self, user_id: &str, sec_uid: &str) -> Result<bool, String> {
        if user_id.trim().is_empty() && sec_uid.trim().is_empty() {
            return Ok(false);
        }
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        let count: i64 = conn
            .query_row(
                "SELECT COUNT(*) FROM outreach_items
                 WHERE status = 'completed'
                   AND ((?1 != '' AND user_id = ?1) OR (?2 != '' AND sec_uid = ?2))",
                params![user_id, sec_uid],
                |row| row.get(0),
            )
            .map_err(|e| e.to_string())?;
        Ok(count > 0)
    }
}

#[derive(Debug, Clone)]
pub struct OutreachItemDraft {
    pub platform: String,
    pub action_type: String,
    pub source_job_id: Option<String>,
    pub video_url: String,
    pub aweme_id: String,
    pub comment_id: String,
    pub comment_text: String,
    pub username: String,
    pub user_id: String,
    pub sec_uid: String,
    pub profile_url: String,
    pub reply_text: String,
    pub dm_text: String,
}

fn map_outreach_item_row(row: &rusqlite::Row<'_>) -> rusqlite::Result<OutreachItem> {
    Ok(OutreachItem {
        id: row.get(0)?,
        task_id: row.get(1)?,
        platform: row.get(2)?,
        action_type: row.get(3)?,
        source_job_id: row.get(4)?,
        video_url: row.get(5)?,
        aweme_id: row.get(6)?,
        comment_id: row.get(7)?,
        comment_text: row.get(8)?,
        username: row.get(9)?,
        user_id: row.get(10)?,
        sec_uid: row.get(11)?,
        profile_url: row.get(12)?,
        reply_text: row.get(13)?,
        dm_text: row.get(14)?,
        status: OutreachItemStatus::from_str(&row.get::<_, String>(15)?),
        attempts: row.get(16)?,
        max_retries: row.get(17)?,
        error_message: row.get(18)?,
        result_json: row.get(19)?,
        created_at: row.get(20)?,
        updated_at: row.get(21)?,
    })
}

pub fn profile_url_for_comment(platform: &str, comment: &CapturedComment) -> String {
    match platform {
        "xiaohongshu" => {
            if comment.user_id.trim().is_empty() {
                String::new()
            } else {
                format!("https://www.xiaohongshu.com/user/profile/{}", comment.user_id.trim())
            }
        }
        _ => {
            if !comment.sec_uid.trim().is_empty() {
                format!("https://www.douyin.com/user/{}", comment.sec_uid.trim())
            } else if !comment.user_id.trim().is_empty() {
                format!("https://www.douyin.com/user/{}", comment.user_id.trim())
            } else {
                String::new()
            }
        }
    }
}
