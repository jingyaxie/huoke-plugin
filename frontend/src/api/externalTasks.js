import http from "./http";
import {
  resolveAgentStrategy,
} from "../utils/acquisitionStrategy";

export async function fetchExternalCapabilities(platform) {
  const resp = await http.get("/agent/external/capabilities", {
    params: platform ? { platform } : undefined,
  });
  return resp.data;
}

export async function preflightExternalTask(payload) {
  const resp = await http.post("/agent/external/preflight", payload);
  return resp.data;
}

export async function createExternalTask(payload) {
  const resp = await http.post("/agent/external/jobs", payload);
  return resp.data;
}

export function buildLocalCorrelation(taskId) {
  return {
    external_system: "huoke_local",
    external_task_id: taskId,
    idempotency_key: taskId,
  };
}

function buildConstraints(settings, commentPresetIds, dmPresetIds) {
  const constraints = {
    comment_dm_interval_seconds_min: settings.comment_dm_interval_seconds_min,
    comment_dm_interval_seconds_max: settings.comment_dm_interval_seconds_max,
    comment_dm_percentage: settings.comment_dm_percentage,
    follow_per_day: settings.follow_per_day,
    dm_per_day: settings.dm_per_day,
    batch_cooldown_minutes: settings.batch_cooldown_minutes,
  };
  if (commentPresetIds?.length) constraints.comment_preset_ids = commentPresetIds;
  if (dmPresetIds?.length) constraints.dm_preset_ids = dmPresetIds;
  return constraints;
}

function resolvePresetContents(presets, selectedIds) {
  if (!Array.isArray(presets) || !presets.length) return [];
  if (!selectedIds?.length) return presets.map((row) => row.content).filter(Boolean);
  const idSet = new Set(selectedIds);
  return presets.filter((row) => idSet.has(row.id)).map((row) => row.content).filter(Boolean);
}

function agentStrategyForPlatform(platform, strategyId) {
  return resolveAgentStrategy(platform, strategyId);
}

export function buildAutoTaskPayload({
  name,
  platform,
  keyword,
  regionName,
  targetCount,
  crawlVideoLimit,
  commentDays,
  publishTimeRange,
  headless = true,
  settings,
  commentPresetIds,
  dmPresetIds,
  commentPresets,
  dmPresets,
  evaluation,
  binding,
  agentStrategy,
}) {
  const taskId = `auto-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const scope = {
    keyword,
    target_count: targetCount,
    comment_days: commentDays,
    publish_time_range: publishTimeRange || "unlimited",
  };
  const resolvedStrategy = agentStrategyForPlatform(platform, agentStrategy);
  if (
    resolvedStrategy === "standalone-browse-douyin"
    && crawlVideoLimit != null
    && Number(crawlVideoLimit) > 0
    && Number(crawlVideoLimit) !== Number(targetCount)
  ) {
    scope.crawl_video_limit = Number(crawlVideoLimit);
  }
  const region = String(regionName || "").trim();
  if (region && region !== "不限地区" && region !== "全国") {
    scope.region = region;
  }
  const outreach = {
    constraints: buildConstraints(settings, commentPresetIds, dmPresetIds),
    reply_templates: resolvePresetContents(commentPresets, commentPresetIds),
    dm_templates: resolvePresetContents(dmPresets, dmPresetIds),
  };
  const payload = {
    intent: "keyword_auto",
    name,
    platform,
    scope,
    crawl: { headless: headless !== false },
    outreach,
    correlation: buildLocalCorrelation(taskId),
    auto_execute: true,
    auto_restart: true,
    agent_strategy: agentStrategyForPlatform(platform, agentStrategy),
  };
  if (evaluation && Object.keys(evaluation).length) {
    payload.evaluation = evaluation;
  }
  if (binding?.huoke_account_id) {
    payload.outreach.constraints = {
      ...payload.outreach.constraints,
      huoke_account_id: binding.huoke_account_id,
      huoke_tenant_id: binding.huoke_tenant_id,
      platform_user_id: binding.platform_user_id,
      account_label: binding.account_label,
    };
  }
  return payload;
}

export function buildManualTaskPayload({
  intent,
  name,
  platform,
  inputUrl,
  commentDays,
  publishTimeRange,
  crawlVideoLimit,
  headless = true,
  settings,
  commentPresetIds,
  dmPresetIds,
  commentPresets,
  dmPresets,
  evaluation,
  agentStrategy,
  targetCount,
}) {
  const taskId = `manual-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const scope = {
    input_url: inputUrl,
    comment_days: commentDays,
    publish_time_range: publishTimeRange || "unlimited",
  };
  if (intent === "account_home" && crawlVideoLimit) {
    scope.crawl_video_limit = crawlVideoLimit;
  }
  const resolvedStrategy = agentStrategyForPlatform(platform, agentStrategy);
  if (resolvedStrategy === "standalone-browse-douyin") {
    if (targetCount != null && Number(targetCount) > 0) {
      scope.target_count = Math.max(1, Number(targetCount));
    } else if (intent === "single_video") {
      scope.target_count = 5;
    }
  }
  const outreach = {
    constraints: buildConstraints(settings, commentPresetIds, dmPresetIds),
    reply_templates: resolvePresetContents(commentPresets, commentPresetIds),
    dm_templates: resolvePresetContents(dmPresets, dmPresetIds),
  };
  const payload = {
    intent,
    name,
    platform,
    scope,
    crawl: { headless: headless !== false },
    outreach,
    correlation: buildLocalCorrelation(taskId),
    auto_execute: true,
    auto_restart: true,
    agent_strategy: resolvedStrategy,
  };
  if (evaluation && Object.keys(evaluation).length) {
    payload.evaluation = evaluation;
  }
  return payload;
}
