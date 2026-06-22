import { getAccountId, getApiKey, getAccessToken, getPlatformId, getTenantId, getApiBaseUrl } from "./http";

const baseURL = getApiBaseUrl();

function headers() {
  const h = {
    "Content-Type": "application/json",
    "X-Tenant-Id": getTenantId(),
    "X-Platform-Id": getPlatformId(),
    "X-Account-Id": getAccountId(),
  };
  const apiKey = getApiKey();
  if (apiKey) h["X-API-Key"] = apiKey;
  const token = getAccessToken();
  if (token) h.Authorization = `Bearer ${token}`;
  return h;
}

export async function listPresets(kind) {
  const resp = await fetch(`${baseURL}/presets?kind=${encodeURIComponent(kind)}`, { headers: headers() });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || "加载预设失败");
  }
  return resp.json();
}

export async function createPreset(kind, payload) {
  const resp = await fetch(`${baseURL}/presets?kind=${encodeURIComponent(kind)}`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify(payload),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || "创建预设失败");
  }
  return resp.json();
}

export async function updatePreset(kind, presetId, payload) {
  const resp = await fetch(`${baseURL}/presets/${encodeURIComponent(presetId)}?kind=${encodeURIComponent(kind)}`, {
    method: "PATCH",
    headers: headers(),
    body: JSON.stringify(payload),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || "更新预设失败");
  }
  return resp.json();
}

export async function deletePreset(kind, presetId) {
  const resp = await fetch(`${baseURL}/presets/${encodeURIComponent(presetId)}?kind=${encodeURIComponent(kind)}`, {
    method: "DELETE",
    headers: headers(),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || "删除预设失败");
  }
  return resp.json();
}

export async function loadAllPresetContents() {
  const [comments, dmOpeners] = await Promise.all([listPresets("comments"), listPresets("dm-openers")]);
  return {
    replyTemplates: (comments.items || []).map((row) => row.content).filter(Boolean),
    dmTemplates: (dmOpeners.items || []).map((row) => row.content).filter(Boolean),
  };
}

export const DEFAULT_INTERACTION_SETTINGS = {
  comment_dm_interval_seconds_min: 10,
  comment_dm_interval_seconds_max: 30,
  comment_dm_percentage: 0,
  follow_per_day: 30,
  dm_per_day: 30,
  batch_cooldown_minutes: 8,
};

export async function getInteractionSettings() {
  const resp = await fetch(`${baseURL}/settings/interaction`, { headers: headers() });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || "加载互动设置失败");
  }
  return resp.json();
}

export async function putInteractionSettings(patch) {
  const resp = await fetch(`${baseURL}/settings/interaction`, {
    method: "PUT",
    headers: headers(),
    body: JSON.stringify(patch),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || "保存互动设置失败");
  }
  return resp.json();
}

export async function listPlatformPresets() {
  const [comments, dmOpeners] = await Promise.all([listPresets("comments"), listPresets("dm-openers")]);
  return {
    comments: comments.items || [],
    dmOpeners: dmOpeners.items || [],
  };
}
