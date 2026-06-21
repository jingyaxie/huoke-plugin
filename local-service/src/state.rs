use std::sync::Arc;

use crate::capture::CaptureService;
use crate::db::Database;
use crate::job_run::JobRunRegistry;
use crate::outreach::OutreachService;
use crate::ws::BridgeHub;

#[derive(Clone)]
pub struct AppState {
    pub hub: BridgeHub,
    pub db: Database,
    pub capture: Arc<CaptureService>,
    pub outreach: Arc<OutreachService>,
    pub default_daily_quota: i64,
    pub job_runs: JobRunRegistry,
}
