export const FALLBACK_PUBLISH_TIME_OPTIONS = [
  { value: "unlimited", label: "不限" },
  { value: "1d", label: "1天内" },
  { value: "3d", label: "3天内" },
  { value: "7d", label: "1周内" },
  { value: "180d", label: "半年内" },
];

export const FALLBACK_COMMENT_DAYS_OPTIONS = [
  { value: "3", label: "3天" },
  { value: "5", label: "5天" },
  { value: "7", label: "7天" },
  { value: "0", label: "不限" },
];

export const REGION_PRESETS = [
  { code: "110100", name: "北京" },
  { code: "310100", name: "上海" },
  { code: "440100", name: "广州" },
  { code: "440300", name: "深圳" },
  { code: "330100", name: "杭州" },
  { code: "320100", name: "南京" },
  { code: "510100", name: "成都" },
  { code: "420100", name: "武汉" },
  { code: "610100", name: "西安" },
  { code: "500100", name: "重庆" },
  { code: "", name: "不限地区" },
];

const INTENT_BY_TASK_TYPE = {
  home_auto: "keyword_auto",
  video_manual: "single_video",
  home_manual: "account_home",
};

/** 采集完成后是否执行关注/私信/回复（与后端 should_run_auto_outreach 对齐；暂时关闭） */
export function computeAutoOutreach() {
  return false;
}

export function platformLabel(platform) {
  if (platform === "xiaohongshu") return "小红书";
  if (platform === "kuaishou") return "快手";
  return "抖音";
}

import { listExtensionCollectPlatforms } from "../config/extensionPlatformCapabilities";

export function listSupportedPlatforms(capabilities) {
  const allowed = new Set(listExtensionCollectPlatforms());
  const platforms = capabilities?.platforms;
  if (Array.isArray(platforms) && platforms.length) {
    return platforms.filter((item) => allowed.has(item));
  }
  return listExtensionCollectPlatforms();
}

export function getIntentSpecForTaskType(taskType, capabilities) {
  const intents = capabilities?.intents || [];
  return intents.find((item) => (item.lead_task_types || []).includes(taskType)) || null;
}

export function hasScopeField(taskType, fieldKey, capabilities) {
  const spec = getIntentSpecForTaskType(taskType, capabilities);
  const fields = spec?.scope_fields;
  if (!Array.isArray(fields) || !fields.length) return true;
  return fields.some((field) => field.key === fieldKey);
}

export function hasAutoScopeField(fieldKey, capabilities) {
  if (fieldKey === "publish_time_range") return true;
  return hasScopeField("home_auto", fieldKey, capabilities);
}

export function getFieldOptions(capabilities, fieldKey, fallback) {
  const rows = capabilities?.field_options?.[fieldKey];
  if (!Array.isArray(rows) || !rows.length) return fallback;
  return rows.map((item) => ({
    value: String(item.value),
    label: item.label || String(item.value),
  }));
}

export function getScopeFieldLabel(taskType, fieldKey, capabilities, fallback) {
  const spec = getIntentSpecForTaskType(taskType, capabilities);
  const field = (spec?.scope_fields || []).find((item) => item.key === fieldKey);
  return field?.label || fallback;
}

export function listManualModeOptions(capabilities) {
  const defaults = [
    { value: "account_home", label: "账号客户", description: "粘贴博主主页链接，扫描主页视频列表并抓取评论" },
    { value: "single_video", label: "单条视频获客", description: "从单条视频互动人群中提取线索" },
  ];
  const intents = capabilities?.intents || [];
  return defaults.map((row) => {
    const spec = intents.find((item) => item.intent === row.value);
    return {
      value: row.value,
      label: spec?.label || row.label,
      description: spec?.description || row.description,
    };
  });
}

export function applyDefaultCommentDays(taskType, capabilities) {
  const spec = getIntentSpecForTaskType(taskType, capabilities);
  const days = spec?.default_comment_days ?? 3;
  return String(days);
}

export function validateRequiredScopeFields(taskType, values, capabilities) {
  const spec = getIntentSpecForTaskType(taskType, capabilities);
  const fields = spec?.scope_fields || [];
  for (const field of fields) {
    if (!field.required) continue;
    const raw = values[field.key];
    if (raw === undefined || raw === null || String(raw).trim() === "") {
      return `请填写${field.label || field.key}`;
    }
  }
  const intent = INTENT_BY_TASK_TYPE[taskType];
  if (!intent && !spec) {
    return "当前获客方式暂不可用，请稍后重试";
  }
  return null;
}

export function buildEvaluationPayload({
  evalTemplateId,
  targetCustomer,
  acceptDescription,
  rejectSignals,
}) {
  const payload = {
    ...(evalTemplateId ? { template_id: evalTemplateId } : {}),
    ...(targetCustomer?.trim() ? { target_customer: targetCustomer.trim() } : {}),
    ...(acceptDescription?.trim() ? { accept_description: acceptDescription.trim() } : {}),
    ...(rejectSignals?.trim()
      ? {
          reject_signals: rejectSignals
            .split(/[,，\s]+/)
            .map((item) => item.trim())
            .filter(Boolean),
        }
      : {}),
  };
  return Object.keys(payload).length ? payload : undefined;
}

export function defaultEvaluation(keyword, evaluation) {
  if (evaluation && Object.keys(evaluation).length) return evaluation;
  const trimmed = String(keyword || "").trim();
  if (!trimmed) return undefined;
  return { product_or_service: trimmed };
}

export function browserModeToHeadless(mode) {
  return mode !== "headed";
}

const EXTENSION_AUTO_START_KEY = "huoke_extension_auto_start";

/** 插件获客：创建后是否立即执行（localStorage 记忆，默认开启） */
export function loadExtensionAutoStartPref(defaultValue = true) {
  try {
    const raw = localStorage.getItem(EXTENSION_AUTO_START_KEY);
    if (raw === "0") return false;
    if (raw === "1") return true;
  } catch {
    /* ignore */
  }
  return defaultValue;
}

export function saveExtensionAutoStartPref(value) {
  try {
    localStorage.setItem(EXTENSION_AUTO_START_KEY, value ? "1" : "0");
  } catch {
    /* ignore */
  }
}

/** 与后端 filters::composed_keyword 一致：地区拼入搜索词 */
export function composeSearchKeyword(keyword, regionName) {
  const kw = String(keyword ?? "").trim();
  const region = String(regionName ?? "").trim();
  if (!region || region === "不限地区" || region === "全国") {
    return kw;
  }
  if (kw.includes(region)) {
    return kw;
  }
  return `${region} ${kw}`;
}
