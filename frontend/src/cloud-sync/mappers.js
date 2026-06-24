import { CONFIG_KEY } from "./api";
import { buildAgentJobFromCollectJob } from "../utils/extensionCollectJobs";

const PRECISE_STATUSES = new Set([
  "precise",
  "precise_customer",
  "qualified",
  "1",
  "true",
  "精准客户",
]);

export function isDesktopCloudTask(task) {
  if (!task || typeof task !== "object") return false;
  const config = task.config && typeof task.config === "object" ? task.config : {};
  const desktop = config[CONFIG_KEY];
  if (!desktop || typeof desktop !== "object") return false;
  const execSource = String(config.execution_source || task.execution_source || "").toLowerCase();
  if (execSource === "local_huoke") return true;
  return config.execution === "local_sidecar" && Boolean(desktop.local_job_id);
}

export function mapCloudStatusToLocal(status) {
  const normalized = String(status || "").trim().toLowerCase();
  if (normalized === "running" || normalized === "queued" || normalized === "retrying") {
    return normalized === "running" ? "running" : "pending";
  }
  if (normalized === "paused_timeout" || normalized === "pending") return "paused";
  if (normalized === "completed" || normalized === "stopped") return "completed";
  if (normalized === "failed" || normalized === "dead_letter" || normalized === "error") {
    return "failed";
  }
  if (normalized === "created") return "pending";
  return normalized || "pending";
}

function parseCloudTimestamp(value) {
  if (value == null || value === "") return null;
  if (typeof value === "number" && Number.isFinite(value)) {
    return value > 1e12 ? value : value * 1000;
  }
  const text = String(value).trim();
  if (!text) return null;
  const ms = Date.parse(text);
  return Number.isFinite(ms) ? ms : null;
}

function cloudTaskKeyword(task) {
  const config = task?.config && typeof task.config === "object" ? task.config : {};
  const keyword = String(config.keyword || config.keywords?.[0] || task.category_name || "").trim();
  return keyword;
}

function cloudTaskIntent(taskType) {
  if (taskType === "video_manual") return "single_video";
  if (taskType === "home_manual") return "account_home";
  return "keyword_auto";
}

function cloudTaskJobType(taskType) {
  if (taskType === "home_manual" || taskType === "video_manual") return "manual";
  return "keyword";
}

export function isAutoCloudTask(task) {
  return String(task?.type || "").trim() === "home_auto";
}

export function isManualCloudTask(task) {
  const type = String(task?.type || "").trim();
  return type === "home_manual" || type === "video_manual";
}

export function cloudTaskToCollectJobRow(task) {
  const config = task?.config && typeof task.config === "object" ? { ...task.config } : {};
  const desktop = config[CONFIG_KEY] && typeof config[CONFIG_KEY] === "object" ? config[CONFIG_KEY] : {};
  const taskType = String(task?.type || "home_auto").trim();
  const commentCount = Number(task.progress_total ?? task.produced_total ?? task.leads ?? 0);
  const preciseCount = Number(task.progress_precise ?? 0);
  const targetCount = Number(config.target_count ?? task.accepted_target ?? task.requested_target ?? 0);
  const keyword = cloudTaskKeyword(task);

  return {
    id: `cloud:${task.id}`,
    cloud_task_id: task.id,
    _cloud_only: true,
    _source: "cloud",
    platform: task.platform || "douyin",
    keyword,
    name: task.name || keyword || "云端任务",
    job_type: cloudTaskJobType(taskType),
    input_url: task.input_url || "",
    status: mapCloudStatusToLocal(task.status),
    limit_videos: targetCount,
    max_comments_per_video: 0,
    comment_count: commentCount,
    precise_count: preciseCount,
    reply_count: 0,
    dm_count: 0,
    follow_count: 0,
    video_count: 0,
    created_at: parseCloudTimestamp(task.created_at),
    updated_at: parseCloudTimestamp(task.updated_at),
    error_message: task.error_message || "",
    config: {
      ...config,
      intent: cloudTaskIntent(taskType),
      target_count: targetCount,
      [CONFIG_KEY]: desktop,
    },
  };
}

export function isCloudLeadPrecise(lead) {
  const status = String(lead?.status || "").trim().toLowerCase();
  if (PRECISE_STATUSES.has(status) || status.includes("precise")) return true;
  const score = Number(lead?.precise_score);
  return Number.isFinite(score) && score > 0 && status !== "raw";
}

function cloudLeadCommentId(lead) {
  const raw = lead?.raw_json && typeof lead.raw_json === "object" ? lead.raw_json : {};
  const nested = raw.lead && typeof raw.lead === "object" ? raw.lead : {};
  return String(nested.comment_id || lead.comment_id || lead.id || "").trim();
}

export function cloudLeadToCapturedComment(lead) {
  const raw = lead?.raw_json && typeof lead.raw_json === "object" ? lead.raw_json : {};
  const nested = raw.lead && typeof raw.lead === "object" ? raw.lead : {};
  const commentId = cloudLeadCommentId(lead);
  const videoId = String(lead.video_id || nested.content_id || "").trim();
  const ts = parseCloudTimestamp(lead.time || lead.comment_at || nested.created_at);

  return {
    id: lead.id || commentId,
    comment_id: commentId,
    aweme_id: videoId,
    username: lead.author_nickname || lead.name || nested.nickname || "—",
    avatar_url: lead.author_avatar_url || nested.avatar_url || "",
    content: lead.comment || nested.comment_text || "",
    create_time: ts,
    is_precise: isCloudLeadPrecise(lead),
    evaluation_reason: lead.precise_reason || nested.evaluation?.reason || "",
    evaluation_score: lead.precise_score ?? nested.evaluation?.score ?? null,
    sec_uid: lead.author_sec_uid || nested.sec_uid || "",
    user_id: lead.author_id || nested.target_user_id || "",
  };
}

export function cloudLeadsToInteractions(leads) {
  const interactions = [];
  for (const lead of leads || []) {
    const summary = lead.outreach_summary && typeof lead.outreach_summary === "object"
      ? lead.outreach_summary
      : {};
    const commentId = cloudLeadCommentId(lead);
    for (const [action, detail] of Object.entries(summary)) {
      if (!detail || typeof detail !== "object") continue;
      const status = String(detail.status || "").toLowerCase();
      if (status && !["ok", "success", "completed"].includes(status)) continue;
      interactions.push({
        id: detail.action_log_id || `${commentId}-${action}`,
        action,
        comment_id: commentId,
        user_id: lead.author_id || "",
        created_at: parseCloudTimestamp(detail.executed_at || detail.updated_at),
      });
    }
  }
  return interactions;
}

export function buildAgentJobFromCloudCollectJob(collectJobRow, leads) {
  const comments = (leads || []).map(cloudLeadToCapturedComment);
  const interactions = cloudLeadsToInteractions(leads);
  return buildAgentJobFromCollectJob(collectJobRow, { comments, videos: [], interactions });
}
