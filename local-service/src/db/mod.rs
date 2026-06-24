use std::path::Path;
use std::sync::{Arc, Mutex};

use rusqlite::{params, Connection};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::douyin::parser::parse_aweme_id_from_page_url;
use crate::job_config::JobConfig;

pub mod outreach;
pub use outreach::{
    OutreachItem, OutreachItemDraft, OutreachItemStatus, OutreachTask, OutreachTaskStatus, QuotaStatus,
};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum JobStatus {
    Pending,
    Running,
    Paused,
    Completed,
    Failed,
}

impl JobStatus {
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

#[derive(Debug, Clone, Serialize)]
pub struct CollectJob {
    pub id: String,
    pub platform: String,
    pub keyword: String,
    pub name: String,
    pub job_type: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub input_url: Option<String>,
    pub status: JobStatus,
    pub limit_videos: i64,
    pub max_comments_per_video: i64,
    pub error_message: Option<String>,
    pub created_at: i64,
    pub updated_at: i64,
    pub video_count: i64,
    pub comment_count: i64,
    pub reply_count: i64,
    pub dm_count: i64,
    pub follow_count: i64,
    pub precise_count: i64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub config: Option<serde_json::Value>,
}

#[derive(Debug, Clone, Serialize)]
pub struct CapturedVideo {
    pub id: String,
    pub job_id: String,
    pub aweme_id: String,
    pub video_url: String,
    pub title: String,
    pub author: String,
    pub created_at: i64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub raw_json: Option<String>,
}

impl CapturedVideo {
    pub fn raw_text(&self) -> String {
        self.raw_json.clone().unwrap_or_default()
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct CapturedComment {
    pub id: String,
    pub job_id: String,
    pub aweme_id: String,
    pub comment_id: String,
    pub parent_comment_id: Option<String>,
    pub content: String,
    pub username: String,
    pub user_id: String,
    pub sec_uid: String,
    pub avatar_url: String,
    pub digg_count: i64,
    pub create_time: Option<i64>,
    pub created_at: i64,
    pub is_precise: bool,
    pub evaluation_reason: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub evaluation_score: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub evaluated_at: Option<i64>,
}

#[derive(Debug, Clone, Serialize)]
pub struct InteractionRecord {
    pub id: String,
    pub job_id: String,
    pub action: String,
    pub comment_id: String,
    pub user_id: String,
    pub day: String,
    pub created_at: i64,
}

#[derive(Clone)]
pub struct Database {
    conn: Arc<Mutex<Connection>>,
}

impl Database {
    pub fn open(path: &Path) -> Result<Self, String> {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
        }
        let conn = Connection::open(path).map_err(|e| e.to_string())?;
        let db = Self {
            conn: Arc::new(Mutex::new(conn)),
        };
        db.migrate()?;
        Ok(db)
    }

    fn migrate(&self) -> Result<(), String> {
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        conn.execute_batch(
            r#"
            CREATE TABLE IF NOT EXISTS collect_jobs (
                id TEXT PRIMARY KEY,
                platform TEXT NOT NULL DEFAULT 'douyin',
                keyword TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                limit_videos INTEGER NOT NULL DEFAULT 5,
                max_comments_per_video INTEGER NOT NULL DEFAULT 50,
                error_message TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS captured_videos (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                aweme_id TEXT NOT NULL,
                video_url TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                author TEXT NOT NULL DEFAULT '',
                raw_json TEXT,
                created_at INTEGER NOT NULL,
                UNIQUE(job_id, aweme_id)
            );

            CREATE TABLE IF NOT EXISTS video_scans (
                job_id TEXT NOT NULL,
                aweme_id TEXT NOT NULL,
                scanned_at INTEGER NOT NULL,
                PRIMARY KEY (job_id, aweme_id)
            );
            CREATE INDEX IF NOT EXISTS idx_video_scans_job ON video_scans(job_id);

            CREATE TABLE IF NOT EXISTS captured_comments (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                aweme_id TEXT NOT NULL,
                comment_id TEXT NOT NULL,
                parent_comment_id TEXT,
                content TEXT NOT NULL DEFAULT '',
                username TEXT NOT NULL DEFAULT '',
                user_id TEXT NOT NULL DEFAULT '',
                sec_uid TEXT NOT NULL DEFAULT '',
                digg_count INTEGER NOT NULL DEFAULT 0,
                create_time INTEGER,
                raw_json TEXT,
                created_at INTEGER NOT NULL,
                avatar_url TEXT NOT NULL DEFAULT '',
                is_precise INTEGER NOT NULL DEFAULT 0,
                evaluation_reason TEXT NOT NULL DEFAULT '',
                evaluation_score REAL,
                evaluated_at INTEGER,
                UNIQUE(job_id, comment_id)
            );
            "#,
        )
        .map_err(|e| e.to_string())?;
        self.migrate_outreach(&conn)?;
        conn.execute_batch(
            r#"
            CREATE TABLE IF NOT EXISTS interaction_log (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL DEFAULT '',
                action TEXT NOT NULL,
                comment_id TEXT NOT NULL DEFAULT '',
                user_id TEXT NOT NULL DEFAULT '',
                day TEXT NOT NULL,
                created_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_interaction_log_day_action ON interaction_log(day, action);
            CREATE INDEX IF NOT EXISTS idx_interaction_log_comment ON interaction_log(comment_id);
            "#,
        )
        .map_err(|e| e.to_string())?;
        let _ = conn.execute(
            "ALTER TABLE collect_jobs ADD COLUMN name TEXT NOT NULL DEFAULT ''",
            [],
        );
        let _ = conn.execute("ALTER TABLE collect_jobs ADD COLUMN config_json TEXT", []);
        let _ = conn.execute(
            "ALTER TABLE collect_jobs ADD COLUMN job_type TEXT NOT NULL DEFAULT 'keyword'",
            [],
        );
        let _ = conn.execute("ALTER TABLE collect_jobs ADD COLUMN input_url TEXT", []);
        let _ = conn.execute(
            "ALTER TABLE captured_comments ADD COLUMN avatar_url TEXT NOT NULL DEFAULT ''",
            [],
        );
        let _ = conn.execute(
            "ALTER TABLE captured_comments ADD COLUMN is_precise INTEGER NOT NULL DEFAULT 0",
            [],
        );
        let _ = conn.execute(
            "ALTER TABLE captured_comments ADD COLUMN evaluation_reason TEXT NOT NULL DEFAULT ''",
            [],
        );
        let _ = conn.execute(
            "ALTER TABLE captured_comments ADD COLUMN evaluation_score REAL",
            [],
        );
        let _ = conn.execute(
            "ALTER TABLE captured_comments ADD COLUMN evaluated_at INTEGER",
            [],
        );
        let _ = conn.execute_batch(
            r#"
            CREATE TABLE IF NOT EXISTS video_scans (
                job_id TEXT NOT NULL,
                aweme_id TEXT NOT NULL,
                scanned_at INTEGER NOT NULL,
                PRIMARY KEY (job_id, aweme_id)
            );
            CREATE INDEX IF NOT EXISTS idx_video_scans_job ON video_scans(job_id);
            INSERT OR IGNORE INTO video_scans (job_id, aweme_id, scanned_at)
            SELECT job_id, aweme_id, MIN(created_at)
            FROM captured_comments
            GROUP BY job_id, aweme_id;
            "#,
        );
        Ok(())
    }

    fn parse_config_json(raw: Option<String>) -> Option<serde_json::Value> {
        raw.and_then(|text| serde_json::from_str(&text).ok())
    }

    fn build_collect_job(
        &self,
        id: String,
        platform: String,
        keyword: String,
        name: String,
        job_type: String,
        input_url: Option<String>,
        status: String,
        limit_videos: i64,
        max_comments_per_video: i64,
        error_message: Option<String>,
        created_at: i64,
        updated_at: i64,
        config_json: Option<String>,
    ) -> Result<CollectJob, String> {
        let (listed_video_count, comment_count) = self.counts_for_job(&id)?;
        // 关键词任务进度/「视频数」= 已打开并尝试采集的视频数（含无评论），不含搜索预写入列表。
        let video_count = if job_type == "keyword" {
            self.count_scanned_videos_for_job(&id)?
        } else {
            listed_video_count
        };
        let (reply_count, dm_count, follow_count) = self.interaction_counts_for_job(&id)?;
        let precise_count = self.count_precise_comments_for_job(&id)?;
        Ok(CollectJob {
            id,
            platform,
            keyword,
            name,
            job_type,
            input_url,
            status: JobStatus::from_str(&status),
            limit_videos,
            max_comments_per_video,
            error_message,
            created_at,
            updated_at,
            video_count,
            comment_count,
            reply_count,
            dm_count,
            follow_count,
            precise_count,
            config: Self::parse_config_json(config_json),
        })
    }

    pub fn now_ms() -> i64 {
        use std::time::{SystemTime, UNIX_EPOCH};
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_millis() as i64)
            .unwrap_or(0)
    }

    pub fn create_job(
        &self,
        platform: &str,
        keyword: &str,
        name: &str,
        job_type: &str,
        input_url: Option<&str>,
        limit_videos: i64,
        max_comments_per_video: i64,
        config_json: Option<&str>,
    ) -> Result<CollectJob, String> {
        let id = Uuid::new_v4().to_string();
        let now = Self::now_ms();
        let display_name = if name.trim().is_empty() {
            if job_type == "manual" {
                "手动获客".to_string()
            } else {
                format!("关键词获客-{}", keyword.trim())
            }
        } else {
            name.trim().to_string()
        };
        {
            let conn = self.conn.lock().map_err(|e| e.to_string())?;
            conn.execute(
                "INSERT INTO collect_jobs (id, platform, keyword, name, job_type, input_url, status, limit_videos, max_comments_per_video, config_json, created_at, updated_at)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, 'pending', ?7, ?8, ?9, ?10, ?10)",
                params![
                    id,
                    platform,
                    keyword,
                    display_name,
                    job_type,
                    input_url,
                    limit_videos,
                    max_comments_per_video,
                    config_json,
                    now
                ],
            )
            .map_err(|e| e.to_string())?;
        }
        self.get_job(&id)
    }

    pub fn list_jobs(&self, limit: i64) -> Result<Vec<CollectJob>, String> {
        let rows = {
            let conn = self.conn.lock().map_err(|e| e.to_string())?;
            let mut stmt = conn
                .prepare(
                    "SELECT id, platform, keyword, name, job_type, input_url, status, limit_videos, max_comments_per_video, error_message, created_at, updated_at, config_json
                     FROM collect_jobs ORDER BY created_at DESC LIMIT ?1",
                )
                .map_err(|e| e.to_string())?;
            let rows = stmt
                .query_map(params![limit], |row| {
                    Ok((
                        row.get::<_, String>(0)?,
                        row.get::<_, String>(1)?,
                        row.get::<_, String>(2)?,
                        row.get::<_, String>(3)?,
                        row.get::<_, String>(4)?,
                        row.get::<_, Option<String>>(5)?,
                        row.get::<_, String>(6)?,
                        row.get::<_, i64>(7)?,
                        row.get::<_, i64>(8)?,
                        row.get::<_, Option<String>>(9)?,
                        row.get::<_, i64>(10)?,
                        row.get::<_, i64>(11)?,
                        row.get::<_, Option<String>>(12)?,
                    ))
                })
                .map_err(|e| e.to_string())?;
            rows.map(|row| row.map_err(|e| e.to_string()))
                .collect::<Result<Vec<_>, _>>()?
        };

        let mut jobs = Vec::new();
        for (
            id,
            platform,
            keyword,
            name,
            job_type,
            input_url,
            status,
            limit_videos,
            max_comments_per_video,
            error_message,
            created_at,
            updated_at,
            config_json,
        ) in rows
        {
            jobs.push(self.build_collect_job(
                id,
                platform,
                keyword,
                name,
                job_type,
                input_url,
                status,
                limit_videos,
                max_comments_per_video,
                error_message,
                created_at,
                updated_at,
                config_json,
            )?);
        }
        Ok(jobs)
    }

    pub fn count_precise_comments_for_job(&self, job_id: &str) -> Result<i64, String> {
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        conn.query_row(
            "SELECT COUNT(*) FROM captured_comments WHERE job_id = ?1 AND is_precise = 1",
            params![job_id],
            |row| row.get(0),
        )
        .map_err(|e| e.to_string())
    }

    pub fn job_has_evaluated_comments(&self, job_id: &str) -> Result<bool, String> {
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        let count: i64 = conn
            .query_row(
                "SELECT COUNT(*) FROM captured_comments WHERE job_id = ?1 AND evaluated_at IS NOT NULL",
                params![job_id],
                |row| row.get(0),
            )
            .map_err(|e| e.to_string())?;
        Ok(count > 0)
    }

    pub fn list_unevaluated_comments(
        &self,
        job_id: &str,
        limit: i64,
    ) -> Result<Vec<CapturedComment>, String> {
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        let mut stmt = conn
            .prepare(
                "SELECT id, job_id, aweme_id, comment_id, parent_comment_id, content, username, user_id, sec_uid, avatar_url, digg_count, create_time, created_at, is_precise, evaluation_reason, evaluation_score, evaluated_at
                 FROM captured_comments WHERE job_id = ?1 AND evaluated_at IS NULL AND parent_comment_id IS NULL
                 ORDER BY create_time DESC LIMIT ?2",
            )
            .map_err(|e| e.to_string())?;
        let rows = stmt
            .query_map(params![job_id, limit.clamp(1, 5000)], map_comment_row)
            .map_err(|e| e.to_string())?;
        rows.map(|row| row.map_err(|e| e.to_string())).collect()
    }

    pub fn update_comment_evaluation(
        &self,
        job_id: &str,
        comment_id: &str,
        is_precise: bool,
        reason: &str,
        score: Option<f64>,
        evaluated_at: i64,
    ) -> Result<bool, String> {
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        let changed = conn
            .execute(
                "UPDATE captured_comments SET is_precise = ?1, evaluation_reason = ?2, evaluation_score = ?3, evaluated_at = ?4
                 WHERE job_id = ?5 AND comment_id = ?6",
                params![
                    if is_precise { 1 } else { 0 },
                    reason,
                    score,
                    evaluated_at,
                    job_id,
                    comment_id,
                ],
            )
            .map_err(|e| e.to_string())?;
        Ok(changed > 0)
    }

    fn counts_for_job(&self, job_id: &str) -> Result<(i64, i64), String> {
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        let video_count: i64 = conn
            .query_row(
                "SELECT COUNT(*) FROM captured_videos WHERE job_id = ?1",
                params![job_id],
                |row| row.get(0),
            )
            .map_err(|e| e.to_string())?;
        let comment_count: i64 = conn
            .query_row(
                "SELECT COUNT(*) FROM captured_comments WHERE job_id = ?1",
                params![job_id],
                |row| row.get(0),
            )
            .map_err(|e| e.to_string())?;
        Ok((video_count, comment_count))
    }

    fn interaction_counts_for_job(&self, job_id: &str) -> Result<(i64, i64, i64), String> {
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        let count_action = |action: &str| -> Result<i64, String> {
            conn.query_row(
                "SELECT COUNT(*) FROM interaction_log WHERE job_id = ?1 AND action = ?2",
                params![job_id, action],
                |row| row.get(0),
            )
            .map_err(|e| e.to_string())
        };
        Ok((
            count_action("reply")?,
            count_action("dm")?,
            count_action("follow")?,
        ))
    }

    pub fn list_interactions_for_job(
        &self,
        job_id: &str,
        limit: i64,
    ) -> Result<Vec<InteractionRecord>, String> {
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        let mut stmt = conn
            .prepare(
                "SELECT id, job_id, action, comment_id, user_id, day, created_at
                 FROM interaction_log WHERE job_id = ?1
                 ORDER BY created_at DESC LIMIT ?2",
            )
            .map_err(|e| e.to_string())?;
        let rows = stmt
            .query_map(params![job_id, limit.clamp(1, 5000)], |row| {
                Ok(InteractionRecord {
                    id: row.get(0)?,
                    job_id: row.get(1)?,
                    action: row.get(2)?,
                    comment_id: row.get(3)?,
                    user_id: row.get(4)?,
                    day: row.get(5)?,
                    created_at: row.get(6)?,
                })
            })
            .map_err(|e| e.to_string())?;
        rows.map(|row| row.map_err(|e| e.to_string())).collect()
    }

    pub fn get_job(&self, job_id: &str) -> Result<CollectJob, String> {
        let row = {
            let conn = self.conn.lock().map_err(|e| e.to_string())?;
            conn.query_row(
                "SELECT id, platform, keyword, name, job_type, input_url, status, limit_videos, max_comments_per_video, error_message, created_at, updated_at, config_json
                 FROM collect_jobs WHERE id = ?1",
                params![job_id],
                |row| {
                    Ok((
                        row.get::<_, String>(0)?,
                        row.get::<_, String>(1)?,
                        row.get::<_, String>(2)?,
                        row.get::<_, String>(3)?,
                        row.get::<_, String>(4)?,
                        row.get::<_, Option<String>>(5)?,
                        row.get::<_, String>(6)?,
                        row.get::<_, i64>(7)?,
                        row.get::<_, i64>(8)?,
                        row.get::<_, Option<String>>(9)?,
                        row.get::<_, i64>(10)?,
                        row.get::<_, i64>(11)?,
                        row.get::<_, Option<String>>(12)?,
                    ))
                },
            )
            .map_err(|e| e.to_string())?
        };

        self.build_collect_job(
            row.0, row.1, row.2, row.3, row.4, row.5, row.6, row.7, row.8, row.9, row.10, row.11,
            row.12,
        )
    }

    pub fn update_job_status(
        &self,
        job_id: &str,
        status: JobStatus,
        error_message: Option<&str>,
    ) -> Result<(), String> {
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        conn.execute(
            "UPDATE collect_jobs SET status = ?1, error_message = ?2, updated_at = ?3 WHERE id = ?4",
            params![status.as_str(), error_message, Self::now_ms(), job_id],
        )
        .map_err(|e| e.to_string())?;
        Ok(())
    }

    pub fn list_running_job_ids(&self) -> Result<Vec<String>, String> {
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        let mut stmt = conn
            .prepare("SELECT id FROM collect_jobs WHERE status = 'running'")
            .map_err(|e| e.to_string())?;
        let rows = stmt
            .query_map([], |row| row.get::<_, String>(0))
            .map_err(|e| e.to_string())?;
        rows.map(|row| row.map_err(|e| e.to_string())).collect()
    }

    /// 服务重启后，内存里的编排任务已不存在；已达目标的标记 completed，其余标记 failed。
    pub fn reconcile_stale_running_jobs(&self, fail_reason: &str) -> Result<(usize, usize), String> {
        let ids = self.list_running_job_ids()?;
        let mut completed = 0usize;
        let mut failed = 0usize;
        for id in ids {
            let job = self.get_job(&id)?;
            if self.collect_goal_met_for_job(&job)? {
                self.update_job_status(&id, JobStatus::Completed, None)?;
                completed += 1;
            } else {
                self.update_job_status(&id, JobStatus::Failed, Some(fail_reason))?;
                failed += 1;
            }
        }
        Ok((completed, failed))
    }

    /// 因服务重启/被取代等标记为 failed，但采集目标已达成 → 修正为 completed。
    pub fn reconcile_interrupted_failed_jobs(&self) -> Result<usize, String> {
        let rows = {
            let conn = self.conn.lock().map_err(|e| e.to_string())?;
            let mut stmt = conn
                .prepare(
                    "SELECT id FROM collect_jobs WHERE status = 'failed' AND (
                       error_message LIKE '%服务重启%'
                       OR error_message LIKE '%运行环境已重新初始化%'
                       OR error_message LIKE '%已被新任务取代%'
                       OR error_message LIKE '%任务已中断%'
                     )",
                )
                .map_err(|e| e.to_string())?;
            let rows = stmt
                .query_map([], |row| row.get::<_, String>(0))
                .map_err(|e| e.to_string())?;
            rows.map(|row| row.map_err(|e| e.to_string())).collect::<Result<Vec<_>, _>>()?
        };

        let mut promoted = 0usize;
        for id in rows {
            let job = self.get_job(&id)?;
            if !self.collect_goal_met_for_job(&job)? {
                continue;
            }
            self.update_job_status(&id, JobStatus::Completed, None)?;
            promoted += 1;
        }
        Ok(promoted)
    }

    fn scanned_video_count_for_job(&self, job_id: &str) -> Result<i64, String> {
        self.count_scanned_videos_for_job(job_id)
    }

    fn collect_goal_met_for_job(&self, job: &CollectJob) -> Result<bool, String> {
        let scanned = self.scanned_video_count_for_job(&job.id)?;
        let precise = self.count_precise_comments_for_job(&job.id)?;
        Ok(JobConfig::collect_goal_met(job, scanned, precise))
    }

    /// @deprecated 使用 reconcile_stale_running_jobs
    pub fn fail_stale_running_jobs(&self, reason: &str) -> Result<usize, String> {
        let (_, failed) = self.reconcile_stale_running_jobs(reason)?;
        Ok(failed)
    }

    /// 启动新任务前，结束其它仍在 running 的采集任务（单 Chrome 标签页同时只能跑一个）。
    pub fn supersede_other_running_jobs(&self, keep_job_id: &str) -> Result<usize, String> {
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        let n = conn
            .execute(
                "UPDATE collect_jobs SET status = 'failed', error_message = '已被新任务取代', updated_at = ?1 WHERE status = 'running' AND id != ?2",
                params![Self::now_ms(), keep_job_id],
            )
            .map_err(|e| e.to_string())?;
        Ok(n)
    }

    pub fn delete_collect_job(&self, job_id: &str) -> Result<bool, String> {
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        let status: String = conn
            .query_row(
                "SELECT status FROM collect_jobs WHERE id = ?1",
                params![job_id],
                |row| row.get(0),
            )
            .map_err(|_| "job not found".to_string())?;
        if status == JobStatus::Running.as_str() {
            return Err("cannot delete running job".into());
        }
        conn.execute(
            "DELETE FROM captured_comments WHERE job_id = ?1",
            params![job_id],
        )
        .map_err(|e| e.to_string())?;
        conn.execute(
            "DELETE FROM video_scans WHERE job_id = ?1",
            params![job_id],
        )
        .map_err(|e| e.to_string())?;
        conn.execute(
            "DELETE FROM captured_videos WHERE job_id = ?1",
            params![job_id],
        )
        .map_err(|e| e.to_string())?;
        let n = conn
            .execute("DELETE FROM collect_jobs WHERE id = ?1", params![job_id])
            .map_err(|e| e.to_string())?;
        Ok(n > 0)
    }

    pub fn replace_videos_for_job(
        &self,
        job_id: &str,
        videos: &[crate::douyin::parser::ParsedVideo],
    ) -> Result<usize, String> {
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        conn.execute(
            "DELETE FROM captured_videos WHERE job_id = ?1",
            params![job_id],
        )
        .map_err(|e| e.to_string())?;
        drop(conn);
        self.upsert_videos(job_id, videos)
    }

    pub fn upsert_videos(
        &self,
        job_id: &str,
        videos: &[crate::douyin::parser::ParsedVideo],
    ) -> Result<usize, String> {
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        let now = Self::now_ms();
        let mut inserted = 0usize;
        for video in videos {
            let changed = conn
                .execute(
                    "INSERT INTO captured_videos (id, job_id, aweme_id, video_url, title, author, raw_json, created_at)
                     VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)
                     ON CONFLICT(job_id, aweme_id) DO UPDATE SET
                       title = excluded.title,
                       author = excluded.author,
                       raw_json = excluded.raw_json",
                    params![
                        Uuid::new_v4().to_string(),
                        job_id,
                        video.aweme_id,
                        video.video_url,
                        video.title,
                        video.author,
                        video.raw_json,
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

    pub fn count_comments_for_job(&self, job_id: &str) -> Result<i64, String> {
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        conn.query_row(
            "SELECT COUNT(*) FROM captured_comments WHERE job_id = ?1",
            params![job_id],
            |row| row.get(0),
        )
        .map_err(|e| e.to_string())
    }

    pub fn count_comments_for_aweme(&self, job_id: &str, aweme_id: &str) -> Result<i64, String> {
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        conn.query_row(
            "SELECT COUNT(*) FROM captured_comments WHERE job_id = ?1 AND aweme_id = ?2",
            params![job_id, aweme_id],
            |row| row.get(0),
        )
        .map_err(|e| e.to_string())
    }

    pub fn count_distinct_comment_awemes_for_job(&self, job_id: &str) -> Result<i64, String> {
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        conn.query_row(
            "SELECT COUNT(DISTINCT aweme_id) FROM captured_comments WHERE job_id = ?1",
            params![job_id],
            |row| row.get(0),
        )
        .map_err(|e| e.to_string())
    }

    /// 已打开并尝试采集评论的视频数（含无评论视频），不含搜索 Hook 预写入的列表。
    pub fn count_scanned_videos_for_job(&self, job_id: &str) -> Result<i64, String> {
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        conn.query_row(
            "SELECT COUNT(*) FROM video_scans WHERE job_id = ?1",
            params![job_id],
            |row| row.get(0),
        )
        .map_err(|e| e.to_string())
    }

    pub fn is_video_scanned(&self, job_id: &str, aweme_id: &str) -> Result<bool, String> {
        if aweme_id.trim().is_empty() {
            return Ok(false);
        }
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        let n: i64 = conn
            .query_row(
                "SELECT COUNT(*) FROM video_scans WHERE job_id = ?1 AND aweme_id = ?2",
                params![job_id, aweme_id],
                |row| row.get(0),
            )
            .map_err(|e| e.to_string())?;
        Ok(n > 0)
    }

    pub fn mark_video_scanned(&self, job_id: &str, aweme_id: &str) -> Result<(), String> {
        let aweme_id = aweme_id.trim();
        if aweme_id.is_empty() {
            return Ok(());
        }
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        conn.execute(
            "INSERT INTO video_scans (job_id, aweme_id, scanned_at)
             VALUES (?1, ?2, ?3)
             ON CONFLICT(job_id, aweme_id) DO NOTHING",
            params![job_id, aweme_id, Self::now_ms()],
        )
        .map_err(|e| e.to_string())?;
        Ok(())
    }

    pub fn get_video_url_for_job(&self, job_id: &str, aweme_id: &str) -> Result<String, String> {
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        conn.query_row(
            "SELECT video_url FROM captured_videos WHERE job_id = ?1 AND aweme_id = ?2",
            params![job_id, aweme_id],
            |row| row.get(0),
        )
        .map_err(|e| e.to_string())
    }

    pub fn patch_video_collect_url(
        &self,
        job_id: &str,
        video_aweme_id: &str,
        resolved_aweme_id: &str,
        page_url: Option<&str>,
    ) -> Result<(), String> {
        let url = page_url
            .filter(|u| !u.trim().is_empty() && parse_aweme_id_from_page_url(u).is_some())
            .map(str::to_string)
            .unwrap_or_else(|| format!("https://www.douyin.com/video/{resolved_aweme_id}"));
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        conn.execute(
            "UPDATE captured_videos SET video_url = ?1 WHERE job_id = ?2 AND aweme_id = ?3",
            params![url, job_id, video_aweme_id],
        )
        .map_err(|e| e.to_string())?;
        Ok(())
    }

    pub fn comment_days_for_running_job(&self, job_id: &str) -> i64 {
        self.get_job(job_id)
            .ok()
            .and_then(|job| {
                job.config
                    .as_ref()
                    .and_then(|c| c.get("comment_days"))
                    .and_then(|v| v.as_i64())
            })
            .unwrap_or(0)
    }

    pub fn record_interaction(
        &self,
        job_id: &str,
        action: &str,
        comment_id: &str,
        user_id: &str,
    ) -> Result<(), String> {
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        let day = chrono::Local::now().format("%Y-%m-%d").to_string();
        conn.execute(
            "INSERT INTO interaction_log (id, job_id, action, comment_id, user_id, day, created_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
            params![
                Uuid::new_v4().to_string(),
                job_id,
                action,
                comment_id,
                user_id,
                day,
                Self::now_ms(),
            ],
        )
        .map_err(|e| e.to_string())?;
        Ok(())
    }

    pub fn count_interactions_today(&self, action: &str) -> Result<i64, String> {
        let day = chrono::Local::now().format("%Y-%m-%d").to_string();
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        conn.query_row(
            "SELECT COUNT(*) FROM interaction_log WHERE day = ?1 AND action = ?2",
            params![day, action],
            |row| row.get(0),
        )
        .map_err(|e| e.to_string())
    }

    pub fn user_interacted_today(&self, user_id: &str, action: &str) -> Result<bool, String> {
        if user_id.trim().is_empty() {
            return Ok(false);
        }
        let day = chrono::Local::now().format("%Y-%m-%d").to_string();
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        let count: i64 = conn
            .query_row(
                "SELECT COUNT(*) FROM interaction_log WHERE day = ?1 AND action = ?2 AND user_id = ?3",
                params![day, action, user_id],
                |row| row.get(0),
            )
            .map_err(|e| e.to_string())?;
        Ok(count > 0)
    }

    pub fn list_eligible_comments_for_outreach(
        &self,
        job_id: &str,
        comment_days: i64,
        min_digg: i64,
        limit: i64,
        precise_only: bool,
    ) -> Result<Vec<CapturedComment>, String> {
        let all = self.list_comments_for_job(job_id, None, limit.clamp(1, 2000))?;
        let day = chrono::Local::now().format("%Y-%m-%d").to_string();
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        let mut touched_comments: std::collections::HashSet<String> =
            std::collections::HashSet::new();
        let mut touched_users: std::collections::HashSet<String> =
            std::collections::HashSet::new();
        {
            let mut stmt = conn
                .prepare(
                    "SELECT comment_id, user_id, action FROM interaction_log WHERE day = ?1",
                )
                .map_err(|e| e.to_string())?;
            let rows = stmt
                .query_map(params![day], |row| {
                    Ok((
                        row.get::<_, String>(0)?,
                        row.get::<_, String>(1)?,
                        row.get::<_, String>(2)?,
                    ))
                })
                .map_err(|e| e.to_string())?;
            for row in rows {
                if let Ok((comment_id, user_id, action)) = row {
                    if action == "reply" {
                        touched_comments.insert(comment_id);
                    }
                    if action == "dm" || action == "follow" {
                        if !user_id.is_empty() {
                            touched_users.insert(user_id);
                        }
                    }
                }
            }
        }

        let mut eligible: Vec<CapturedComment> = all
            .into_iter()
            .filter(|c| c.parent_comment_id.is_none())
            .filter(|c| c.digg_count >= min_digg)
            .filter(|c| crate::filters::within_days(c.create_time, comment_days))
            .filter(|c| !touched_comments.contains(&c.comment_id))
            .filter(|c| !touched_users.contains(&c.user_id))
            .filter(|c| !precise_only || c.is_precise)
            .collect();
        eligible.sort_by(|a, b| b.digg_count.cmp(&a.digg_count));
        eligible.truncate(limit.clamp(1, 500) as usize);
        Ok(eligible)
    }

    pub fn upsert_comments(
        &self,
        job_id: &str,
        aweme_id: &str,
        comments: &[crate::douyin::parser::ParsedComment],
    ) -> Result<usize, String> {
        let comment_days = self.comment_days_for_running_job(job_id);
        let filtered = crate::filters::filter_comments_by_days(comments, comment_days);
        self.upsert_comments_raw(job_id, aweme_id, &filtered)
    }

    fn upsert_comments_raw(
        &self,
        job_id: &str,
        aweme_id: &str,
        comments: &[crate::douyin::parser::ParsedComment],
    ) -> Result<usize, String> {
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        let now = Self::now_ms();
        let mut inserted = 0usize;
        for comment in comments {
            let changed = conn
                .execute(
                    "INSERT INTO captured_comments
                     (id, job_id, aweme_id, comment_id, parent_comment_id, content, username, user_id, sec_uid, avatar_url, digg_count, create_time, raw_json, created_at)
                     VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14)
                     ON CONFLICT(job_id, comment_id) DO UPDATE SET
                       content = excluded.content,
                       username = CASE
                         WHEN excluded.username != '' AND excluded.username != '—' THEN excluded.username
                         ELSE username
                       END,
                       user_id = excluded.user_id,
                       sec_uid = excluded.sec_uid,
                       avatar_url = CASE WHEN excluded.avatar_url != '' THEN excluded.avatar_url ELSE avatar_url END,
                       digg_count = excluded.digg_count,
                       create_time = COALESCE(excluded.create_time, create_time),
                       raw_json = excluded.raw_json,
                       is_precise = CASE WHEN excluded.content != content THEN 0 ELSE is_precise END,
                       evaluation_reason = CASE WHEN excluded.content != content THEN '' ELSE evaluation_reason END,
                       evaluation_score = CASE WHEN excluded.content != content THEN NULL ELSE evaluation_score END,
                       evaluated_at = CASE WHEN excluded.content != content THEN NULL ELSE evaluated_at END",
                    params![
                        Uuid::new_v4().to_string(),
                        job_id,
                        aweme_id,
                        comment.comment_id,
                        comment.parent_comment_id,
                        comment.content,
                        comment.username,
                        comment.user_id,
                        comment.sec_uid,
                        comment.avatar_url,
                        comment.digg_count,
                        comment.create_time,
                        comment.raw_json,
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

    pub fn list_videos_for_job(&self, job_id: &str) -> Result<Vec<CapturedVideo>, String> {
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        let mut stmt = conn
            .prepare(
                "SELECT id, job_id, aweme_id, video_url, title, author, created_at, raw_json
                 FROM captured_videos WHERE job_id = ?1 ORDER BY created_at ASC",
            )
            .map_err(|e| e.to_string())?;
        let rows = stmt
            .query_map(params![job_id], |row| {
                Ok(CapturedVideo {
                    id: row.get(0)?,
                    job_id: row.get(1)?,
                    aweme_id: row.get(2)?,
                    video_url: row.get(3)?,
                    title: row.get(4)?,
                    author: row.get(5)?,
                    created_at: row.get(6)?,
                    raw_json: row.get(7)?,
                })
            })
            .map_err(|e| e.to_string())?;
        rows.map(|row| row.map_err(|e| e.to_string())).collect()
    }

    pub fn list_comments_for_job(
        &self,
        job_id: &str,
        aweme_id: Option<&str>,
        limit: i64,
    ) -> Result<Vec<CapturedComment>, String> {
        let conn = self.conn.lock().map_err(|e| e.to_string())?;
        let mut comments = Vec::new();
        if let Some(aweme_id) = aweme_id {
            let mut stmt = conn
                .prepare(
                    "SELECT id, job_id, aweme_id, comment_id, parent_comment_id, content, username, user_id, sec_uid, avatar_url, digg_count, create_time, created_at, is_precise, evaluation_reason, evaluation_score, evaluated_at
                     FROM captured_comments WHERE job_id = ?1 AND aweme_id = ?2
                     ORDER BY create_time DESC LIMIT ?3",
                )
                .map_err(|e| e.to_string())?;
            let rows = stmt
                .query_map(params![job_id, aweme_id, limit], map_comment_row)
                .map_err(|e| e.to_string())?;
            for row in rows {
                comments.push(row.map_err(|e| e.to_string())?);
            }
        } else {
            let mut stmt = conn
                .prepare(
                    "SELECT id, job_id, aweme_id, comment_id, parent_comment_id, content, username, user_id, sec_uid, avatar_url, digg_count, create_time, created_at, is_precise, evaluation_reason, evaluation_score, evaluated_at
                     FROM captured_comments WHERE job_id = ?1
                     ORDER BY create_time DESC LIMIT ?2",
                )
                .map_err(|e| e.to_string())?;
            let rows = stmt
                .query_map(params![job_id, limit], map_comment_row)
                .map_err(|e| e.to_string())?;
            for row in rows {
                comments.push(row.map_err(|e| e.to_string())?);
            }
        }
        Ok(comments)
    }
}

fn map_comment_row(row: &rusqlite::Row<'_>) -> rusqlite::Result<CapturedComment> {
    Ok(CapturedComment {
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
        is_precise: row.get::<_, i64>(13).unwrap_or(0) != 0,
        evaluation_reason: row.get(14).unwrap_or_default(),
        evaluation_score: row.get(15).ok(),
        evaluated_at: row.get(16).ok(),
    })
}
