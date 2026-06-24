use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use crate::db::{Database, JobRunLogEntry, JobRunSummary};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StepStatus {
    Ok,
    Fail,
    Skip,
    Warn,
    Info,
}

impl StepStatus {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Ok => "ok",
            Self::Fail => "fail",
            Self::Skip => "skip",
            Self::Warn => "warn",
            Self::Info => "info",
        }
    }

    pub fn label_zh(self) -> &'static str {
        match self {
            Self::Ok => "成功",
            Self::Fail => "失败",
            Self::Skip => "跳过",
            Self::Warn => "警告",
            Self::Info => "信息",
        }
    }
}

pub fn append_step(
    db: &Database,
    job_id: &str,
    run_id: u64,
    step_key: &str,
    step_label: &str,
    status: StepStatus,
    reason: &str,
    detail: Option<Value>,
) {
    if let Err(err) = db.append_job_run_log(
        job_id,
        run_id as i64,
        step_key,
        step_label,
        status.as_str(),
        reason,
        detail,
    ) {
        tracing::warn!("job {job_id}: failed to write run log: {err}");
    }
}

pub fn log_lab_action(
    db: &Database,
    job_id: &str,
    run_id: u64,
    action_id: &str,
    payload: &Value,
    result: Result<&Value, &str>,
) {
    let (label, reason) = lab_action_meta(action_id);
    let status = match &result {
        Ok(v) => lab_result_status(action_id, v),
        Err(_) => StepStatus::Fail,
    };
    let mut detail = json!({
        "action": action_id,
        "payload": summarize_payload(payload),
    });
    match result {
        Ok(v) => {
            if let Some(summary) = summarize_result(v) {
                detail["result"] = summary;
            }
        }
        Err(err) => {
            detail["error"] = json!(err);
        }
    }
    append_step(
        db,
        job_id,
        run_id,
        action_id,
        label,
        status,
        reason,
        Some(detail),
    );
}

pub fn log_bridge_command(
    db: &Database,
    job_id: &str,
    run_id: u64,
    bridge_action: &str,
    payload: &Value,
    result: Result<&Value, &str>,
) {
    let (label, reason) = bridge_command_meta(bridge_action);
    let step_key = bridge_action.replace('.', "_");
    let status = match &result {
        Ok(v) => {
            if v.get("ok").and_then(|x| x.as_bool()) == Some(false) {
                StepStatus::Fail
            } else {
                StepStatus::Ok
            }
        }
        Err(_) => StepStatus::Fail,
    };
    let mut detail = json!({
        "bridge_action": bridge_action,
        "payload": summarize_payload(payload),
    });
    match result {
        Ok(v) => {
            if let Some(summary) = summarize_result(v) {
                detail["result"] = summary;
            }
        }
        Err(err) => detail["error"] = json!(err),
    }
    append_step(db, job_id, run_id, &step_key, label, status, reason, Some(detail));
}

fn lab_result_status(action_id: &str, value: &Value) -> StepStatus {
    if action_id.starts_with("probe_") {
        if value.get("ok").and_then(|v| v.as_bool()) == Some(true) {
            return StepStatus::Info;
        }
        return StepStatus::Warn;
    }
    if value.get("ok").and_then(|v| v.as_bool()) == Some(false) {
        return StepStatus::Fail;
    }
    StepStatus::Ok
}

fn lab_action_meta(action_id: &str) -> (&'static str, &'static str) {
    match action_id {
        "open_browser" => ("打开浏览器", "启动或聚焦 Chrome 工作窗口"),
        "close_browser" => ("关闭浏览器", "任务结束，关闭工作窗口释放资源"),
        "find_search_box" => ("定位搜索框", "在抖音首页找到搜索输入框"),
        "input_search_text" => ("输入搜索关键词", "输入任务关键词并触发搜索"),
        "click_search_btn" => ("点击搜索", "提交关键词进入搜索结果页"),
        "click_filter_btn" => ("打开筛选", "按任务配置打开发布时间等筛选"),
        "click_filter_overlay" => ("选择筛选项", "点击筛选面板中的时间/排序选项"),
        "ensure_search_multi_column" => ("切换多列布局", "搜索结果需多列卡片布局便于点击视频"),
        "fetch_search_results" => ("抓取搜索结果", "读取当前页视频列表供后续打开"),
        "click_search_video" => ("点击搜索结果视频", "从列表打开视频进入播放/评论采集"),
        "click_profile_video" => ("点击主页视频", "从博主主页打开指定视频"),
        "prepare_search_for_video" => ("准备搜索页", "关闭浮层回到搜索结果列表"),
        "prepare_profile_for_video" => ("准备主页", "回到博主主页以便点击下一条视频"),
        "back_to_profile" => ("返回博主主页", "采集完一条后回到主页继续"),
        "close_video_detail" => ("关闭视频详情", "关闭独立视频页或浮层"),
        "open_url" | "open_douyin_video_detail" => ("打开链接", "导航到指定 URL 或视频页"),
        "open_video" => ("打开视频", "直达视频详情页采集评论"),
        "click_comment_btn" => ("点击评论按钮", "展开评论侧栏以滚动采集评论"),
        "scroll_and_collect_comments" => ("滚动采集评论", "在评论侧栏滚动加载并解析评论"),
        "prepare_feed_for_swipe" => ("准备 Feed 翻页", "收起评论侧栏，准备切下一个视频"),
        "prepare_video_detail_for_swipe" => ("准备详情页翻页", "收起评论侧栏，准备切下一个视频"),
        "swipe_search_feed_next" => ("Feed 切下一个视频", "Feed 内翻页或滑动到下一个视频"),
        "swipe_video_detail_next" => ("详情页切下一个视频", "详情页内翻页或滑动到下一个视频"),
        "recover_search_feed" => ("恢复 Feed 浮层", "Feed 被误关时用 modal_id 恢复"),
        "probe_douyin_feed" | "probe_current_playback" => ("探测播放状态", "确认当前是否在 Feed/详情播放中"),
        "probe_video_detail" => ("探测详情页", "确认是否在 /video/ 详情页"),
        "search_video_probe" => ("探测搜索卡片", "定位搜索结果中目标视频索引"),
        "jump_search_feed_video" => ("跳转 Feed 视频", "在 Feed 中跳到指定 aweme"),
        "fetch_profile_videos" => ("抓取主页视频", "读取博主主页视频列表"),
        "scroll_search_list_to_top" => ("搜索列表回顶", "滚动搜索结果回到顶部"),
        "swipe_page" => ("滑动页面", "滚动搜索列表或页面加载更多"),
        "reply_comment" => ("回复评论", "在评论侧栏输入并发送回复"),
        "send_comment" => ("发送评论", "提交回复内容"),
        "click_comment_avatar" => ("点击评论头像", "进入评论用户主页以便私信/关注"),
        "click_follow_btn" => ("点击关注", "在用户主页点击关注按钮"),
        "click_dm_btn" => ("打开私信", "在用户主页打开私信对话框"),
        "input_dm_text" => ("输入私信", "填写私信文案"),
        "send_dm" => ("发送私信", "提交私信消息"),
        "prepare_video_for_outreach" => ("准备触达视频", "打开视频并定位到目标评论"),
        _ => ("执行插件指令", "通过 Chrome 扩展操作抖音页面"),
    }
}

fn bridge_command_meta(action: &str) -> (&'static str, &'static str) {
    match action {
        "network.hook.enable" => ("启用网络拦截", "监听抖音 API 以自动入库视频/评论"),
        "huoke.extension.reload" => ("重载扩展", "浏览器打开后 reload 扩展确保 content script 就绪"),
        _ => ("系统指令", "local-service 与扩展之间的底层调用"),
    }
}

fn summarize_payload(payload: &Value) -> Value {
    let Some(obj) = payload.as_object() else {
        return payload.clone();
    };
    let mut out = serde_json::Map::new();
    for (key, value) in obj {
        if matches!(key.as_str(), "platform") {
            continue;
        }
        let v = match key.as_str() {
            "dm_text" | "reply_text" | "comment_text" | "text" => {
                truncate_str(value.as_str().unwrap_or(""), 80)
            }
            "raw_json" => json!("[omitted]"),
            _ => value.clone(),
        };
        out.insert(key.clone(), v);
    }
    Value::Object(out)
}

fn summarize_result(value: &Value) -> Option<Value> {
    let keys = [
        "ok",
        "message",
        "error",
        "aweme_id",
        "previous_aweme_id",
        "method",
        "has_next_button",
        "pager_button_disabled",
        "count",
        "found",
        "sidebar_ready",
        "sidebar_active",
        "comment_item_count",
        "is_search_feed",
        "is_standalone_video",
        "mode",
        "attempt",
        "parsed_count",
        "inserted",
        "capture_method",
        "url",
    ];
    let mut out = serde_json::Map::new();
    for key in keys {
        if let Some(v) = value.get(key) {
            if !v.is_null() {
                out.insert(key.to_string(), v.clone());
            }
        }
    }
    if out.is_empty() {
        None
    } else {
        Some(Value::Object(out))
    }
}

fn truncate_str(s: &str, max: usize) -> Value {
    if s.chars().count() <= max {
        json!(s)
    } else {
        let short: String = s.chars().take(max).collect();
        json!(format!("{short}…"))
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct JobRunLogsResponse {
    pub job_id: String,
    pub runs: Vec<JobRunSummary>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct JobRunDetailResponse {
    pub job_id: String,
    pub run_id: i64,
    pub steps: Vec<JobRunLogEntry>,
}

pub fn format_run_log_text(
    job_id: &str,
    run_id: i64,
    job_name: Option<&str>,
    steps: &[JobRunLogEntry],
) -> String {
    let mut out = String::new();
    out.push_str("=== Huoke 任务运行日志 ===\n");
    out.push_str(&format!("任务 ID: {job_id}\n"));
    if let Some(name) = job_name.filter(|s| !s.is_empty()) {
        out.push_str(&format!("任务名称: {name}\n"));
    }
    out.push_str(&format!("运行批次: {run_id}\n"));
    out.push_str(&format!("步骤数: {}\n", steps.len()));
    out.push_str("\n");

    for step in steps {
        let status = match step.status.as_str() {
            "ok" => "✓ 成功",
            "fail" => "✗ 失败",
            "skip" => "→ 跳过",
            "warn" => "! 警告",
            _ => "· 信息",
        };
        let ts = format_timestamp(step.created_at);
        out.push_str(&format!(
            "[{}] {} {} — {}\n",
            step.seq, ts, status, step.step_label
        ));
        if !step.reason.is_empty() {
            out.push_str(&format!("    原因: {}\n", step.reason));
        }
        if let Some(detail) = &step.detail {
            let compact = serde_json::to_string(detail).unwrap_or_default();
            if !compact.is_empty() && compact != "null" {
                out.push_str(&format!("    详情: {compact}\n"));
            }
        }
        out.push('\n');
    }

    out.push_str("--- 导出结束 ---\n");
    out
}

fn format_timestamp(ms: i64) -> String {
    use chrono::{TimeZone, Utc};
    let secs = ms / 1000;
    Utc.timestamp_opt(secs, 0)
        .single()
        .map(|dt| dt.format("%Y-%m-%d %H:%M:%S").to_string())
        .unwrap_or_else(|| ms.to_string())
}
