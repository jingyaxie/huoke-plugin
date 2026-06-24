use std::collections::HashSet;
use std::path::{Path, PathBuf};
use std::sync::LazyLock;
use std::time::Duration;

use tokio::sync::Mutex;
use tracing::{info, warn};

use crate::db::Database;
use crate::evaluation_provider::{evaluate_batch, evaluation_ready};
use crate::job_config::{EvaluationConfig, JobConfig};

const BATCH_SIZE: usize = 15;
const INGEST_EVAL_DEBOUNCE_MS: u64 = 1200;

static EVAL_IN_FLIGHT: LazyLock<Mutex<HashSet<String>>> =
    LazyLock::new(|| Mutex::new(HashSet::new()));

/// 评论入库后异步触发评估（防抖合并短时间内的多次入库）
pub fn spawn_evaluate_job(db: Database, data_dir: PathBuf, job_id: String) {
    tokio::spawn(async move {
        tokio::time::sleep(Duration::from_millis(INGEST_EVAL_DEBOUNCE_MS)).await;
        {
            let mut in_flight = EVAL_IN_FLIGHT.lock().await;
            if in_flight.contains(&job_id) {
                return;
            }
            in_flight.insert(job_id.clone());
        }

        let result = async {
            let job = db.get_job(&job_id)?;
            let cfg = JobConfig::from_job(&job);
            evaluate_job_comments(
                &db,
                &data_dir,
                &job_id,
                &job.keyword,
                &cfg.evaluation,
            )
            .await
        }
        .await;

        match result {
            Ok(stats) if stats.evaluated > 0 => {
                info!(
                    "job {job_id}: ingest evaluation tagged {} precise / {} evaluated",
                    stats.precise, stats.evaluated
                );
            }
            Err(err) => warn!("job {job_id}: ingest evaluation failed: {err}"),
            _ => {}
        }

        EVAL_IN_FLIGHT.lock().await.remove(&job_id);
    });
}

pub struct EvaluationStats {
    pub evaluated: usize,
    pub precise: usize,
}

pub async fn evaluate_job_comments(
    db: &Database,
    data_dir: &Path,
    job_id: &str,
    keyword: &str,
    eval_cfg: &EvaluationConfig,
) -> Result<EvaluationStats, String> {
    if !evaluation_ready(data_dir) {
        info!("job {job_id}: 评论评估未配置（请先登录盈小蚁同步后台令牌），跳过");
        return Ok(EvaluationStats {
            evaluated: 0,
            precise: 0,
        });
    }

    let pending = db.list_unevaluated_comments(job_id, 2000)?;
    if pending.is_empty() {
        let precise = db.count_precise_comments_for_job(job_id)?;
        return Ok(EvaluationStats {
            evaluated: 0,
            precise: precise as usize,
        });
    }

    info!(
        "job {job_id}: evaluating {} comments",
        pending.len()
    );

    let mut evaluated = 0usize;
    let mut precise = 0usize;

    for chunk in pending.chunks(BATCH_SIZE) {
        let results = match evaluate_batch(data_dir, keyword, eval_cfg, chunk).await {
            Ok(rows) => rows,
            Err(err) => {
                warn!("job {job_id}: evaluation batch failed: {err}");
                continue;
            }
        };

        let now = Database::now_ms();
        for item in results {
            let is_prec = item.is_precise;
            if db
                .update_comment_evaluation(
                    job_id,
                    &item.comment_id,
                    is_prec,
                    &item.reason,
                    item.score,
                    now,
                )
                .unwrap_or(false)
            {
                evaluated += 1;
                if is_prec {
                    precise += 1;
                }
            }
        }
    }

    info!(
        "job {job_id}: evaluation done — evaluated={evaluated} precise={precise}"
    );
    Ok(EvaluationStats { evaluated, precise })
}
