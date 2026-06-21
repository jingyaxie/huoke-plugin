import { applyPlatformLabDefaults, PLATFORM_LAB_DEFAULTS } from "../api/pluginLab";

const STORAGE_KEY = "huoke_plugin_lab_params_v1";
const LAST_PLATFORM_KEY = "huoke_plugin_lab_last_platform";

const PERSIST_KEYS = [
  "reuseExisting",
  "waitPageLoad",
  "scrollDirection",
  "scrollDistance",
  "filterOption",
  "searchText",
  "videoIndex",
  "commentIndex",
  "replyText",
  "dmText",
  "scrollRounds",
  "maxComments",
];

function readStore() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function writeStore(store) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(store));
}

function pickPersisted(params) {
  const out = {};
  for (const key of PERSIST_KEYS) {
    if (params[key] !== undefined && params[key] !== null) {
      out[key] = params[key];
    }
  }
  return out;
}

/** 读取某平台已保存参数，并与平台默认值合并 */
export function loadPluginLabParams(platform = "douyin") {
  const store = readStore();
  const saved = store[platform] || {};
  return applyPlatformLabDefaults(platform, {
    platform,
    reuseExisting: false,
    waitPageLoad: false,
    scrollDirection: "down",
    ...saved,
  });
}

/** 保存当前平台参数到 localStorage */
export function savePluginLabParams(platform, params) {
  if (!platform) return;
  const store = readStore();
  store[platform] = pickPersisted(params);
  writeStore(store);
  localStorage.setItem(LAST_PLATFORM_KEY, platform);
}

export function loadLastPluginLabPlatform() {
  return localStorage.getItem(LAST_PLATFORM_KEY) || "douyin";
}

/** 取有效值：表单为空时回退到平台默认值 */
export function resolveLabField(platform, field, value) {
  const defaults = PLATFORM_LAB_DEFAULTS[platform] || PLATFORM_LAB_DEFAULTS.douyin;
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (trimmed) return trimmed;
    const fallback = defaults[field];
    return typeof fallback === "string" ? fallback : "";
  }
  if (value === null || value === undefined || value === "") {
    const fallback = defaults[field];
    return fallback ?? value;
  }
  return value;
}

export function platformDefaultHints(platform) {
  const d = PLATFORM_LAB_DEFAULTS[platform] || PLATFORM_LAB_DEFAULTS.douyin;
  return {
    searchText: d.searchText,
    filterOption: d.filterOption || "（该平台无筛选）",
    replyText: d.replyText,
    dmText: d.dmText || "（该平台不支持私信）",
    videoIndex: d.videoIndex,
    commentIndex: d.commentIndex,
    scrollRounds: d.scrollRounds,
    maxComments: d.maxComments,
    scrollDistance: d.scrollDistance,
  };
}
