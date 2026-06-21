use std::collections::HashMap;
use std::sync::{Arc, Mutex};

/// 同一 job 只允许一个有效编排代际；重新启动/暂停会使旧 tokio 任务自行退出。
#[derive(Clone, Default)]
pub struct JobRunRegistry {
    generations: Arc<Mutex<HashMap<String, u64>>>,
}

impl JobRunRegistry {
    pub fn begin(&self, job_id: &str) -> u64 {
        let mut guard = self.generations.lock().expect("job run registry lock");
        let next = guard.get(job_id).copied().unwrap_or(0).saturating_add(1);
        guard.insert(job_id.to_string(), next);
        next
    }

    pub fn invalidate(&self, job_id: &str) {
        self.begin(job_id);
    }

    pub fn is_current(&self, job_id: &str, generation: u64) -> bool {
        let guard = self.generations.lock().expect("job run registry lock");
        guard.get(job_id).copied() == Some(generation)
    }
}
