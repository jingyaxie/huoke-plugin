import { defaultEvaluation } from "./huokeTaskForm";
import { resolveAgentStrategy } from "./acquisitionStrategy";

function agentStrategyForPlatform(platform, strategyId) {
  return resolveAgentStrategy(platform, strategyId);
}

export function buildConstraintsFromSettings({ settings, commentPresetIds, dmPresetIds }) {
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

export function buildAutoPreflightPayload(input) {
  const keyword = String(input.keywords?.[0] || "").trim();
  const region = String(input.regionName || "").trim();
  const scope = {
    keyword,
    target_count: Math.max(1, Number(input.target) || 1),
    comment_days: Math.max(0, Number(input.commentDays) || 3),
    publish_time_range: String(input.publishTime || "unlimited"),
  };
  if (region && region !== "不限地区" && region !== "全国") {
    scope.region = region;
  }
  const resolvedStrategy = agentStrategyForPlatform(input.platform, input.agentStrategy);
  if (
    resolvedStrategy === "standalone-browse-douyin"
    && input.crawlVideoLimit != null
    && Number(input.crawlVideoLimit) > 0
    && Number(input.crawlVideoLimit) !== Number(input.target)
  ) {
    scope.crawl_video_limit = Number(input.crawlVideoLimit);
  }
  const evaluation = defaultEvaluation(keyword, input.evaluation);
  return {
    intent: "keyword_auto",
    name: String(input.taskName || "").trim() || `关键词获客-${keyword}`,
    platform: input.platform,
    scope,
    crawl: { headless: input.headless !== false },
    ...(evaluation ? { evaluation } : {}),
    outreach: {
      constraints: buildConstraintsFromSettings(input),
    },
    correlation: {
      external_system: "huoke_local",
      external_task_id: `preflight-auto-${Date.now()}`,
    },
    auto_execute: false,
    agent_strategy: agentStrategyForPlatform(input.platform, input.agentStrategy),
  };
}

export function buildManualPreflightPayload(input) {
  const commentDays = parseInt(input.commentDays, 10);
  const intent = input.intent === "single_video" ? "single_video" : "account_home";
  const evaluation = input.evaluation && Object.keys(input.evaluation).length ? input.evaluation : undefined;
  const scope = {
    input_url: String(input.inputUrl || "").trim(),
    comment_days: Number.isFinite(commentDays) ? commentDays : 3,
    publish_time_range: String(input.publishTime || "unlimited"),
  };
  if (intent === "account_home" && input.crawlVideoLimit) {
    scope.crawl_video_limit = Number(input.crawlVideoLimit);
  }
  const resolvedStrategy = agentStrategyForPlatform(input.platform, input.agentStrategy);
  if (resolvedStrategy === "standalone-browse-douyin") {
    if (intent === "single_video" || intent === "account_home") {
      scope.target_count = Math.max(1, Number(input.targetCount) || 5);
    }
  }
  return {
    intent,
    name: String(input.name || "").trim() || "手动获客",
    platform: input.platform,
    scope,
    crawl: { headless: input.headless !== false },
    ...(evaluation ? { evaluation } : {}),
    outreach: {
      constraints: buildConstraintsFromSettings(input),
    },
    correlation: {
      external_system: "huoke_local",
      external_task_id: `preflight-manual-${Date.now()}`,
    },
    auto_execute: false,
    agent_strategy: resolvedStrategy,
  };
}

export function preflightSummary(result) {
  if (!result) return "预检未运行";
  if (result.ready && result.warning_count === 0) return "任务就绪，可正常执行";
  if (result.ready) return `可创建，但有 ${result.warning_count} 项提醒`;
  return `暂不可创建，${result.blocking_count} 项阻塞问题待解决`;
}
