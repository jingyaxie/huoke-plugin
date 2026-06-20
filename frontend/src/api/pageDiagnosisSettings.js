import { getAccountId, getApiKey, getAccessToken, getPlatformId, getTenantId, getApiBaseUrl } from "./http";

const baseURL = getApiBaseUrl();

function settingsHeaders() {
  const headers = {
    "Content-Type": "application/json",
    "X-Tenant-Id": getTenantId(),
    "X-Platform-Id": getPlatformId(),
    "X-Account-Id": getAccountId(),
  };
  const apiKey = getApiKey();
  if (apiKey) {
    headers["X-API-Key"] = apiKey;
  }
  const token = getAccessToken();
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  return headers;
}

export async function fetchPageDiagnosisSettings() {
  const resp = await fetch(`${baseURL}/settings/page-diagnosis`, { headers: settingsHeaders() });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || "读取页面诊断设置失败");
  }
  return resp.json();
}

export async function savePageDiagnosisSettings(payload) {
  const resp = await fetch(`${baseURL}/settings/page-diagnosis`, {
    method: "PUT",
    headers: settingsHeaders(),
    body: JSON.stringify(payload),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || "保存页面诊断设置失败");
  }
  return resp.json();
}
