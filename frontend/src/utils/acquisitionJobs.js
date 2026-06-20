const AUTO_INTENTS = new Set(["keyword_auto"]);
const MANUAL_INTENTS = new Set(["single_video", "account_home"]);

export const DEFAULT_ACQUISITION_FILTER = {
  keyword: "",
  platform: "",
  status: "",
  sort: "desc",
  dateRange: null,
};

export const ACQUISITION_STATUS_OPTIONS = [
  { value: "", label: "全部状态" },
  { value: "queued", label: "排队中" },
  { value: "running", label: "抓取中" },
  { value: "completed", label: "已完成" },
  { value: "failed", label: "失败" },
  { value: "cancelled", label: "已关闭" },
];

export const ACQUISITION_PLATFORM_OPTIONS = [
  { value: "", label: "全部平台" },
  { value: "douyin", label: "抖音" },
  { value: "xiaohongshu", label: "小红书" },
];

function parseJsonMessage(message) {
  const text = String(message || "").trim();
  if (!text.startsWith("{")) return null;
  try {
    const parsed = JSON.parse(text);
    return parsed && typeof parsed === "object" ? parsed : null;
  } catch {
    return null;
  }
}

function configFromTaskBrief(brief) {
  if (!brief || typeof brief !== "object") return null;
  const goals = brief.goals && typeof brief.goals === "object" ? brief.goals : {};
  const constraints = brief.constraints && typeof brief.constraints === "object" ? brief.constraints : {};
  const inputUrl = goals.input_url || goals.video_url || goals.profile_url || "";
  const acquisitionMode = String(goals.acquisition_mode || "").trim().toLowerCase();
  let intent = acquisitionMode;
  if (!intent) {
    if (goals.video_url || (inputUrl && !goals.profile_url && acquisitionMode !== "account_home")) {
      intent = "single_video";
    } else if (goals.profile_url) {
      intent = "account_home";
    } else if (brief.keyword) {
      intent = "keyword_auto";
    }
  }
  return {
    intent,
    acquisition_mode: acquisitionMode || intent,
    task_name: brief.title,
    keyword: brief.keyword,
    keywords: brief.keyword ? [brief.keyword] : [],
    platform: brief.platform,
    region: brief.region,
    target_count: goals.target_leads ?? goals.target_count,
    comment_days: goals.comment_days,
    input_url: inputUrl,
    video_url: goals.video_url,
    profile_url: goals.profile_url,
    constraints,
  };
}

function configFromMessagePayload(payload) {
  if (!payload || typeof payload !== "object") return null;
  const constraints = payload.constraints && typeof payload.constraints === "object" ? payload.constraints : {};
  const inputUrl = payload.input_url || payload.video_url || payload.profile_url || "";
  let intent = String(payload.intent || payload.acquisition_mode || "").trim().toLowerCase();
  if (!intent) {
    if (payload.video_url || inputUrl.includes("/video/")) {
      intent = "single_video";
    } else if (payload.profile_url || (inputUrl && !payload.keyword)) {
      intent = "account_home";
    } else if (payload.keyword) {
      intent = "keyword_auto";
    }
  }
  return {
    ...payload,
    intent,
    acquisition_mode: payload.acquisition_mode || intent,
    task_name: payload.task_name || payload.name,
    keywords: payload.keyword ? [payload.keyword] : payload.keywords,
    target_count: payload.target_count ?? payload.target_leads,
    constraints,
  };
}

export function getJobIntent(job) {
  const config = getJobConfig(job);
  const intent = String(config.intent || config.acquisition_mode || "").trim().toLowerCase();
  if (intent) return intent;

  const brief = job?.result?.orchestration?.task_brief;
  const briefConfig = configFromTaskBrief(brief);
  if (briefConfig?.intent) return briefConfig.intent;

  const message = String(job?.message || "");
  if (message.includes("单条视频")) return "single_video";
  if (message.includes("账号主页")) return "account_home";
  if (message.includes("关键词获客")) return "keyword_auto";
  return null;
}

export function getJobConfig(job) {
  const orchConfig = job?.result?.orchestration?.config;
  if (orchConfig && typeof orchConfig === "object") return orchConfig;

  const briefConfig = configFromTaskBrief(job?.result?.orchestration?.task_brief);
  if (briefConfig) return briefConfig;

  const messageConfig = configFromMessagePayload(parseJsonMessage(job?.message));
  if (messageConfig) return messageConfig;

  const syncOrch = job?.sync?.summary?.orchestration;
  if (syncOrch?.config && typeof syncOrch.config === "object") return syncOrch.config;
  const syncBriefConfig = configFromTaskBrief(syncOrch?.task_brief);
  if (syncBriefConfig) return syncBriefConfig;
  if (job?.sync?.task?.config && typeof job.sync.task.config === "object") return job.sync.task.config;
  return {};
}

function isMeaningfulOutreachEvent(event) {
  if (String(event?.status || "").toLowerCase() === "ok") return true;
  if (String(event?.comment_id || "").trim()) return true;
  if (String(event?.target_user_id || "").trim()) return true;
  const nickname = String(event?.nickname || event?.user_nickname || event?.author_nickname || "").trim();
  const content = String(
    event?.reply_text || event?.message || event?.content || event?.comment_content || "",
  ).trim();
  return Boolean(nickname && content);
}

function isMeaningfulOutreachRow(row) {
  if (String(row?.outreach_status || "").toLowerCase() === "ok") return true;
  if (String(row?.comment_id || "").trim()) return true;
  if (row?.nickname && row.nickname !== "—") return true;
  return Boolean(row?.reply_content || row?.dm_content);
}

function getPersistedPreciseCount(job) {
  const supervisor =
    job?.result?.supervisor_state && typeof job.result.supervisor_state === "object"
      ? job.result.supervisor_state
      : {};
  const ids = supervisor.job_persisted_comment_ids;
  if (Array.isArray(ids) && ids.length) {
    return ids.filter((x) => String(x || "").trim()).length;
  }
  return 0;
}

function getLiveLeadsQualified(job) {
  const persisted = getPersistedPreciseCount(job);
  if (persisted > 0) return persisted;
  const progress = job?.sync?.progress && typeof job.sync.progress === "object" ? job.sync.progress : {};
  const supervisor =
    job?.result?.supervisor_state && typeof job.result.supervisor_state === "object"
      ? job.result.supervisor_state
      : {};
  const crawlLive =
    supervisor?.crawl_live && typeof supervisor.crawl_live === "object" ? supervisor.crawl_live : {};
  const committed = Number(progress.leads_qualified || supervisor.leads_qualified || 0);
  const sessionLive = Number(crawlLive.leads_qualified || 0);
  return Math.max(committed, sessionLive);
}

export function getJobMetrics(job) {
  const config = getJobConfig(job);
  const sync = job?.sync && typeof job.sync === "object" ? job.sync : {};
  const progress = sync.progress && typeof sync.progress === "object" ? sync.progress : {};
  const ledger =
    (sync.summary?.task_ledger && typeof sync.summary.task_ledger === "object" ? sync.summary.task_ledger : null)
    || (job?.result?.task_ledger && typeof job.result.task_ledger === "object" ? job.result.task_ledger : null)
    || {};
  const stats = ledger.stats && typeof ledger.stats === "object" ? ledger.stats : {};
  const outreachEvents = Array.isArray(sync.outreach_events) ? sync.outreach_events : [];

  const countOkFromEvents = (action) =>
    outreachEvents.filter(
      (row) =>
        String(row?.action || row?.action_type || "").toLowerCase() === action
        && String(row?.status || "").toLowerCase() === "ok",
    ).length;

  const countMeaningfulFromEvents = (action) =>
    outreachEvents.filter(
      (row) =>
        String(row?.action || row?.action_type || "").toLowerCase() === action
        && isMeaningfulOutreachEvent(row),
    ).length;

  const statOutreachCount = (action) => {
    const bucket = stats[action];
    const meaningful = countMeaningfulFromEvents(action);
    if (bucket && bucket.ok != null && bucket.ok !== "" && Number(bucket.ok) > 0) {
      return Math.max(Number(bucket.ok), meaningful);
    }
    if (meaningful > 0) return meaningful;
    if (bucket && bucket.ok != null && bucket.ok !== "") {
      return Number(bucket.ok);
    }
    return countOkFromEvents(action);
  };

  const replyOk = statOutreachCount("reply");
  const dmOk = statOutreachCount("dm");
  const followOk = statOutreachCount("follow");
  const viewCounts = getMetricViewCounts(job);
  const hasRowData = viewCounts[OUTREACH_METRIC_VIEWS.ALL] > 0;

  const requestedTarget = Number(config.target_count || progress.target_leads || 0);
  const producedTotal = hasRowData
    ? viewCounts[OUTREACH_METRIC_VIEWS.ALL]
    : Number(
      progress.comments_evaluated
      || progress.comments_captured
      || progress.total_leads_collected
      || progress.leads_collected
      || sync.stats?.leads_total
      || (Array.isArray(sync.leads) ? sync.leads.length : 0)
      || 0,
    );
  const liveQualified = getLiveLeadsQualified(job);
  const persistedPrecise = getPersistedPreciseCount(job);
  const progressPrecise = hasRowData
    ? Math.max(viewCounts[OUTREACH_METRIC_VIEWS.PRECISE], persistedPrecise)
    : Math.max(persistedPrecise, liveQualified);
  const cappedPrecise = hasRowData
    ? Math.min(progressPrecise, viewCounts[OUTREACH_METRIC_VIEWS.ALL] || progressPrecise)
    : progressPrecise;

  return {
    requested_target: requestedTarget,
    produced_total: producedTotal,
    progress_precise: cappedPrecise,
    comment_count: hasRowData ? viewCounts[OUTREACH_METRIC_VIEWS.REPLY] : replyOk,
    dm_count: hasRowData ? viewCounts[OUTREACH_METRIC_VIEWS.DM] : dmOk,
    follow_count: hasRowData ? viewCounts[OUTREACH_METRIC_VIEWS.FOLLOW] : followOk,
  };
}

export function isJobSuspended(job) {
  const state = job?.result?.supervisor_state;
  return job?.status === "pending" && state?.suspended === true;
}

export function formatResumeAt(iso) {
  if (!iso) return null;
  try {
    const dt = new Date(iso);
    if (Number.isNaN(dt.getTime())) return String(iso).slice(0, 16);
    return `${dt.toLocaleString("zh-CN", {
      timeZone: "Asia/Shanghai",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    })}（北京时间）`;
  } catch {
    return String(iso).slice(0, 16);
  }
}

function _diagnosisExtras(source = {}) {
  return {
    screenshot_ref: source.screenshot_ref || null,
    diagnosis_source: source.diagnosis_source || source.source || null,
    user_summary: String(source.user_summary || "").trim(),
    issue_type: source.issue_type || null,
    evidence: Array.isArray(source.evidence) ? source.evidence : [],
  };
}

export function getJobDiagnosisScreenshotPath(jobId) {
  const id = String(jobId || "").trim();
  if (!id) return "";
  return `/agent/jobs/${id}/diagnosis/screenshot`;
}

export function getJobSuspendReason(job) {
  if (!isJobSuspended(job)) return "";
  const brief = getJobSuspendBrief(job);
  return brief?.reason || "";
}

export function getJobSuspendBrief(job) {
  if (!isJobSuspended(job)) return null;

  const syncBrief = job?.sync?.suspend_brief;
  if (syncBrief && typeof syncBrief === "object" && syncBrief.reason) {
    return {
      reason: String(syncBrief.reason || "").trim(),
      resume_at: syncBrief.resume_at || null,
      resume_at_display: syncBrief.resume_at_display || formatResumeAt(syncBrief.resume_at),
      next_action: String(syncBrief.next_action || "").trim(),
      manual_resume: syncBrief.manual_resume || "您也可随时点击「继续执行」跳过等待，立即恢复运行",
      ..._diagnosisExtras(syncBrief),
    };
  }

  const orchestration =
    (job?.result?.orchestration && typeof job.result.orchestration === "object" ? job.result.orchestration : null)
    || (job?.sync?.summary?.orchestration && typeof job.sync.summary.orchestration === "object"
      ? job.sync.summary.orchestration
      : null);
  const orchBrief = orchestration?.suspend_brief;
  if (orchBrief && typeof orchBrief === "object" && orchBrief.reason) {
    return {
      reason: String(orchBrief.reason || "").trim(),
      resume_at: orchBrief.resume_at || null,
      resume_at_display: orchBrief.resume_at_display || formatResumeAt(orchBrief.resume_at),
      next_action: String(orchBrief.next_action || "").trim(),
      manual_resume: orchBrief.manual_resume || "您也可随时点击「继续执行」跳过等待，立即恢复运行",
      ..._diagnosisExtras(orchBrief),
    };
  }

  const state = job?.result?.supervisor_state || {};
  const pageDiag = state.page_diagnosis || job?.result?.page_diagnosis || {};
  const progress = job?.sync?.progress && typeof job.sync.progress === "object" ? job.sync.progress : {};
  const wake = String(
    state.wake_reason
    || progress.wake_reason
    || job?.result?.summary
    || job?.result?.orchestration?.execution_note
    || "任务已挂起，等待恢复",
  ).trim();
  let reason = wake;
  if (wake.includes("连续") && wake.includes("无进展")) {
    const stats = job?.result?.execution_stats || {};
    const comments = stats.comments_captured || stats.comments_persisted || 0;
    const qualified = stats.progress_precise || state.leads_qualified || progress.leads_qualified || 0;
    if (comments > 0 && qualified === 0) {
      reason = `${wake}。已抓取 ${comments} 条评论但暂无精准线索，请点击「继续执行」浏览更多视频，或放宽评估标准。`;
    }
  }
  const resumeAt = state.resume_at || progress.resume_at || null;
  const nextAction = String(state.next_action || progress.next_action || "").trim()
    || "点击「继续执行」从当前进度继续";
  return {
    reason: String(pageDiag.user_title || reason).trim(),
    resume_at: resumeAt,
    resume_at_display: formatResumeAt(resumeAt),
    next_action: nextAction,
    manual_resume: "您也可随时点击「继续执行」跳过等待，立即恢复运行",
    ..._diagnosisExtras({ ...pageDiag, user_summary: pageDiag.user_summary }),
  };
}

export function getJobDisplayStatus(job) {
  const status = job?.status || "";
  if (status === "retrying") return "retrying";
  if (status === "pending") {
    return isJobSuspended(job) ? "suspended" : "waiting_start";
  }
  return status;
}

export function getJobRowModel(job) {
  const config = getJobConfig(job);
  const metrics = getJobMetrics(job);
  const intent = getJobIntent(job);
  const keywords = Array.isArray(config.keywords)
    ? config.keywords
    : config.keyword
      ? [config.keyword]
      : [];
  const name = String(config.task_name || job?.message?.split("：")[0] || job?.job_id || "").trim();
  const accountLabel = String(
    config.constraints?.account_label
    || config.account_label
    || job?.account_id
    || "",
  ).trim();
  const inputUrl = config.input_url || config.video_url || config.profile_url || "";
  const displayStatus = getJobDisplayStatus(job);
  const suspendReason = getJobSuspendReason(job);
  return {
    job,
    config,
    metrics,
    intent,
    name,
    account_label: accountLabel,
    keywords,
    input_url: inputUrl,
    platform: job?.platform || config.platform || "",
    created_at: job?.created_at || job?.updated_at || null,
    status: job?.status || "",
    display_status: displayStatus,
    suspend_reason: suspendReason,
    error: job?.error || job?.dead_letter_reason || suspendReason,
  };
}

export function filterJobsByIntent(jobs, intents) {
  const allowed = intents instanceof Set ? intents : new Set(intents);
  return (jobs || []).filter((job) => {
    const intent = getJobIntent(job);
    return intent && allowed.has(intent);
  });
}

export function filterAutoJobs(jobs) {
  return filterJobsByIntent(jobs, AUTO_INTENTS);
}

export function filterManualJobs(jobs) {
  return filterJobsByIntent(jobs, MANUAL_INTENTS);
}

export function mapStatusForFilter(status) {
  if (status === "completed") return "completed";
  if (status === "cancelled") return "cancelled";
  if (status === "dead_letter") return "failed";
  if (status === "suspended" || status === "waiting_start") return "queued";
  if (status === "pending") return "queued";
  return status;
}

export function jobStatusLabel(status) {
  const map = {
    queued: "排队中",
    pending: "待启动",
    waiting_start: "待启动",
    suspended: "已挂起",
    running: "抓取中",
    completed: "已完成",
    failed: "失败",
    cancelled: "已关闭",
    dead_letter: "失败",
    retrying: "重试中",
  };
  return map[status] || status || "未知";
}

export function jobStatusTagType(status) {
  if (status === "running" || status === "retrying") return "primary";
  if (status === "queued") return "warning";
  if (status === "suspended") return "suspended";
  if (status === "pending" || status === "waiting_start") return "waiting";
  if (status === "completed") return "success";
  if (status === "cancelled") return "info";
  if (status === "failed" || status === "dead_letter") return "danger";
  return "info";
}

export function platformLabel(platform) {
  if (platform === "xiaohongshu") return "小红书";
  if (platform === "kuaishou") return "快手";
  if (platform === "douyin") return "抖音";
  return platform || "—";
}

export function manualIntentLabel(intent) {
  if (intent === "single_video") return "单条视频获客";
  if (intent === "account_home") return "账号客户";
  return intent || "—";
}

export function manualAccountLabel(row) {
  if (row.name) return row.name;
  const url = row.input_url || row.keyword || "";
  if (!url) return "博主主页获客";
  try {
    const slug = decodeURIComponent(new URL(url).pathname.split("/").filter(Boolean).pop() || "").slice(0, 24);
    return slug ? `博主-${slug}` : "博主主页获客";
  } catch {
    return "博主主页获客";
  }
}

export function avatarInitial(text) {
  const value = String(text || "").trim();
  if (!value || value === "—") return "?";
  const match = value.match(/[\u4e00-\u9fffA-Za-z0-9]/);
  return match ? match[0] : value.slice(0, 1);
}

export function formatJobTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  const hour = String(date.getHours()).padStart(2, "0");
  const minute = String(date.getMinutes()).padStart(2, "0");
  return `${month}-${day} ${hour}:${minute}`;
}

export function jobSummaryLine(job) {
  const row = getJobRowModel(job);
  if (row.keywords.length) {
    const region = row.config.region ? ` · ${row.config.region}` : "";
    return `关键词：${row.keywords.join("、")}${region}`;
  }
  if (row.input_url) return row.input_url;
  return job?.message || job?.job_id || "";
}

export function matchesJobFilter(job, filter) {
  const row = getJobRowModel(job);
  if (filter.platform && row.platform !== filter.platform) return false;
  if (filter.status) {
    const mapped = mapStatusForFilter(row.display_status || job.status);
    if (mapped !== filter.status && (row.display_status || job.status) !== filter.status) return false;
  }
  if (filter.keyword?.trim()) {
    const kw = filter.keyword.trim().toLowerCase();
    const haystack = [
      row.name,
      row.account_label,
      ...(row.keywords || []),
      row.input_url,
      job?.message,
      job?.job_id,
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    if (!haystack.includes(kw)) return false;
  }
  if (Array.isArray(filter.dateRange) && filter.dateRange.length === 2) {
    const [start, end] = filter.dateRange;
    const created = new Date(job.created_at || job.updated_at || 0).getTime();
    if (!Number.isFinite(created)) return false;
    const startMs = new Date(start).setHours(0, 0, 0, 0);
    const endMs = new Date(end).setHours(23, 59, 59, 999);
    if (created < startMs || created > endMs) return false;
  }
  return true;
}

export function sortJobsByCreated(jobs, sort = "desc") {
  return [...(jobs || [])].sort((a, b) => {
    const ta = new Date(a.created_at || a.updated_at || 0).getTime();
    const tb = new Date(b.created_at || b.updated_at || 0).getTime();
    return sort === "asc" ? ta - tb : tb - ta;
  });
}

export function computeDashboardFromJobs(jobs) {
  const rows = (jobs || []).map((job) => getJobRowModel(job));
  return {
    running_tasks: rows.filter((row) => ["running", "retrying"].includes(row.status)).length,
    queued_tasks: rows.filter((row) => ["queued", "waiting_start"].includes(row.display_status)).length,
    precise_customers: rows.reduce((sum, row) => sum + Number(row.metrics.progress_precise || 0), 0),
    total_leads: rows.reduce((sum, row) => sum + Number(row.metrics.produced_total || 0), 0),
    dm_count: rows.reduce((sum, row) => sum + Number(row.metrics.dm_count || 0), 0),
    follow_count: rows.reduce((sum, row) => sum + Number(row.metrics.follow_count || 0), 0),
  };
}

export function getOutreachRows(job) {
  const sync = job?.sync && typeof job.sync === "object" ? job.sync : {};
  const captured = Array.isArray(sync.captured_comments) ? sync.captured_comments : [];
  if (captured.length) {
    return captured.map((row) => ({
      id: row.id || row.comment_id || Math.random().toString(36).slice(2),
      comment_id: row.comment_id || row.id || "",
      nickname: row.nickname || row.user_nickname || row.author_nickname || "—",
      avatar: row.avatar_url || row.avatar || row.author_avatar || "",
      comment_at: row.comment_at || row.source_comment_at || "",
      video_title: row.video_title || "",
      comment_content: row.comment_content || row.source_comment || row.comment_text || "",
      is_precise: row.is_precise ?? row.precise ?? false,
      evaluation_score: row.evaluation_score ?? null,
      evaluation_reason: row.evaluation_reason || "",
      reply_content: row.reply_content || "",
      dm_content: row.dm_content || "",
      location_text: row.location_text || row.location || "",
      executed_at: row.executed_at || row.created_at || "",
      profile_url: row.profile_url || row.user_profile_url || "",
      video_url: row.video_url || row.content_url || "",
      evaluation_reason: row.evaluation_reason || "",
    }));
  }

  const leads = Array.isArray(sync.leads) ? sync.leads : [];
  const events = Array.isArray(sync.outreach_events) ? sync.outreach_events : [];

  const outreachByComment = {};
  for (const event of events) {
    const commentId = String(event?.comment_id || "").trim();
    if (!commentId) continue;
    const bucket = outreachByComment[commentId] || {};
    const action = String(event?.action || event?.action_type || "").toLowerCase();
    if (action === "reply" && event.reply_text) bucket.reply_content = event.reply_text;
    if (action === "dm" && event.reply_text) bucket.dm_content = event.reply_text;
    if (String(event?.status || "").toLowerCase() === "ok") {
      bucket.executed_at = event.executed_at || event.created_at || bucket.executed_at;
    }
    outreachByComment[commentId] = bucket;
  }

  if (leads.length) {
    return leads.map((lead) => {
      const commentId = String(lead.comment_id || lead.id || "").trim();
      const outreach = commentId ? outreachByComment[commentId] || {} : {};
      return {
        id: lead.id || lead.lead_id || lead.comment_id || Math.random().toString(36).slice(2),
        nickname: lead.nickname || lead.user_nickname || lead.author_nickname || "—",
        avatar: lead.avatar_url || lead.avatar || lead.author_avatar || "",
        comment_at: lead.comment_at || lead.created_at || "",
        video_title: lead.video_title || "",
        comment_content: lead.comment_content || lead.comment_text || lead.comment || "",
        is_precise: lead.is_precise ?? lead.qualified ?? false,
        reply_content: outreach.reply_content || lead.reply_content || "",
        dm_content: outreach.dm_content || lead.dm_content || "",
        location_text: lead.location_text || lead.location || "",
        executed_at: outreach.executed_at || lead.outreach_at || "",
        profile_url: lead.profile_url || lead.user_profile_url || "",
        video_url: lead.video_url || lead.content_url || "",
      };
    });
  }

  const displayableEvents = events.filter((event) => {
    const hasIdentity = Boolean(
      event?.nickname || event?.user_nickname || event?.author_nickname || event?.comment_id,
    );
    const hasContent = Boolean(
      event?.comment_content || event?.source_comment || event?.reply_text || event?.content,
    );
    const succeeded = String(event?.status || "").toLowerCase() === "ok";
    return hasIdentity && (hasContent || succeeded);
  });

  if (displayableEvents.length) {
    return displayableEvents.map((event) => ({
      id: event.id || `${event.lead_id || ""}-${event.executed_at || ""}`,
      nickname: event.nickname || event.user_nickname || event.author_nickname || "—",
      avatar: event.avatar_url || event.avatar || event.author_avatar || "",
      comment_at: event.comment_at || event.source_comment_at || "",
      video_title: event.video_title || "",
      comment_content: event.comment_content || event.source_comment || "",
      is_precise: event.is_precise ?? event.precise ?? false,
      reply_content: event.reply_content || (event.action === "reply" ? event.content || event.reply_text : ""),
      dm_content: event.dm_content || (event.action === "dm" ? event.content || event.reply_text : ""),
      location_text: event.location_text || event.location || "",
      executed_at: event.executed_at || event.created_at || "",
      profile_url: event.profile_url || event.user_profile_url || "",
      video_url: event.video_url || "",
    }));
  }

  return [];
}

export const OUTREACH_METRIC_VIEWS = {
  ALL: "all",
  PRECISE: "precise",
  REPLY: "reply",
  DM: "dm",
  FOLLOW: "follow",
};

export const OUTREACH_METRIC_VIEW_LABELS = {
  [OUTREACH_METRIC_VIEWS.ALL]: "全部采集",
  [OUTREACH_METRIC_VIEWS.PRECISE]: "精准线索",
  [OUTREACH_METRIC_VIEWS.REPLY]: "评论触达",
  [OUTREACH_METRIC_VIEWS.DM]: "私信触达",
  [OUTREACH_METRIC_VIEWS.FOLLOW]: "关注记录",
};

function mapOutreachEventRow(event) {
  const action = String(event?.action || event?.action_type || "").toLowerCase();
  const errorText = String(event?.error_message || event?.error || "").trim();
  return {
    id: `event-${event.id || event.created_at || Math.random().toString(36).slice(2)}`,
    comment_id: String(event?.comment_id || ""),
    nickname: event.nickname || event.user_nickname || event.author_nickname || event.target_user_id || "—",
    avatar: event.avatar_url || event.avatar || event.author_avatar || "",
    comment_at: event.comment_at || event.source_comment_at || "",
    video_title: event.video_title || "",
    comment_content: event.comment_content || event.source_comment || "",
    is_precise: event.is_precise ?? event.precise ?? false,
    reply_content: action === "reply" ? (event.reply_text || event.content || "") : "",
    dm_content: action === "dm" ? (event.reply_text || event.message || event.content || "") : "",
    location_text: event.location_text || event.location || "",
    executed_at: event.executed_at || event.created_at || "",
    profile_url: event.profile_url || event.user_profile_url || "",
    video_url: event.video_url || "",
    outreach_action: action,
    outreach_status: String(event?.status || ""),
    outreach_error: errorText,
  };
}

export function getOutreachEventRows(job, action, { okOnly = false } = {}) {
  const sync = job?.sync && typeof job.sync === "object" ? job.sync : {};
  const events = Array.isArray(sync.outreach_events) ? sync.outreach_events : [];
  const normalized = String(action || "").toLowerCase();
  return events
    .filter((event) => String(event?.action || event?.action_type || "").toLowerCase() === normalized)
    .filter((event) => !okOnly || String(event?.status || "").toLowerCase() === "ok")
    .map(mapOutreachEventRow);
}

function enrichOutreachRowsWithCaptured(eventRows, capturedRows) {
  const byCommentId = new Map();
  for (const row of capturedRows) {
    const commentId = String(row.comment_id || row.id || "").trim();
    if (commentId) byCommentId.set(commentId, row);
  }
  return eventRows.map((event) => {
    const commentId = String(event.comment_id || "").trim();
    const captured = commentId ? byCommentId.get(commentId) : null;
    if (!captured) return event;
    return {
      ...event,
      nickname: captured.nickname && captured.nickname !== "—" ? captured.nickname : event.nickname,
      comment_content: captured.comment_content || event.comment_content,
      comment_at: captured.comment_at || event.comment_at,
      video_title: captured.video_title || event.video_title,
      video_url: captured.video_url || event.video_url,
      profile_url: captured.profile_url || event.profile_url,
      is_precise: captured.is_precise ?? event.is_precise,
    };
  });
}

export function getRowsForMetricView(job, view = OUTREACH_METRIC_VIEWS.ALL) {
  const allRows = getOutreachRows(job);
  switch (view) {
    case OUTREACH_METRIC_VIEWS.PRECISE:
      return allRows.filter((row) => Boolean(row.is_precise));
    case OUTREACH_METRIC_VIEWS.REPLY: {
      const events = getOutreachEventRows(job, "reply").filter(isMeaningfulOutreachRow);
      if (events.length) return enrichOutreachRowsWithCaptured(events, allRows);
      return allRows.filter((row) => row.reply_content);
    }
    case OUTREACH_METRIC_VIEWS.DM: {
      const events = getOutreachEventRows(job, "dm").filter(isMeaningfulOutreachRow);
      if (events.length) return enrichOutreachRowsWithCaptured(events, allRows);
      return allRows.filter((row) => row.dm_content);
    }
    case OUTREACH_METRIC_VIEWS.FOLLOW:
      return getOutreachEventRows(job, "follow").filter(isMeaningfulOutreachRow);
    default:
      return allRows;
  }
}

export function getMetricViewCounts(job) {
  return {
    [OUTREACH_METRIC_VIEWS.ALL]: getRowsForMetricView(job, OUTREACH_METRIC_VIEWS.ALL).length,
    [OUTREACH_METRIC_VIEWS.PRECISE]: getRowsForMetricView(job, OUTREACH_METRIC_VIEWS.PRECISE).length,
    [OUTREACH_METRIC_VIEWS.REPLY]: getRowsForMetricView(job, OUTREACH_METRIC_VIEWS.REPLY).length,
    [OUTREACH_METRIC_VIEWS.DM]: getRowsForMetricView(job, OUTREACH_METRIC_VIEWS.DM).length,
    [OUTREACH_METRIC_VIEWS.FOLLOW]: getRowsForMetricView(job, OUTREACH_METRIC_VIEWS.FOLLOW).length,
  };
}

export function filterOutreachRows(rows, { keyword = "", actionType = "all" } = {}) {
  const kw = keyword.trim().toLowerCase();
  return (rows || []).filter((row) => {
    if (actionType !== "all") {
      if (actionType === "comment" && !row.reply_content) return false;
      if (actionType === "dm" && !row.dm_content) return false;
      if (actionType === "follow" && !row.executed_at) return false;
    }
    if (!kw) return true;
    const haystack = [row.nickname, row.comment_content, row.reply_content, row.dm_content, row.video_title]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return haystack.includes(kw);
  });
}
