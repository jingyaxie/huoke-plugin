import { getAccessToken, getApiBaseUrl, getTenantId, setAccessToken, setTenantId } from "./http";
import { fetchLlmSettings, saveLlmSettings } from "./llmSettings";
import { loginUser, loginUserSms } from "./auth";

export function isEvaluationReady(settings) {
  if (!settings) return false;
  if (typeof settings.evaluation_ready === "boolean") return settings.evaluation_ready;
  return !!settings.backend?.configured;
}

export async function loadEvaluationSettings() {
  return fetchLlmSettings();
}

export async function saveEvaluationSettings({ backendBaseUrl, backendAccessToken } = {}) {
  const payload = {};
  if (backendBaseUrl != null) {
    payload.backend_base_url = String(backendBaseUrl).trim();
  }
  const token = backendAccessToken ?? getAccessToken();
  if (token?.trim()) {
    payload.backend_access_token = token.trim();
  } else if (backendAccessToken === "") {
    payload.backend_access_token = "";
  }
  return saveLlmSettings(payload);
}

export function defaultBackendBaseUrl() {
  const base = getApiBaseUrl();
  if (base.startsWith("/")) {
    return `${window.location.origin}${base}`;
  }
  return base;
}

/** 登录成功后把后台 API 地址与 token 写入本机 Sidecar */
export async function syncBackendCredentialsFromLogin({
  accessToken,
  tenantId,
  backendBaseUrl,
} = {}) {
  const token = String(accessToken ?? getAccessToken() ?? "").trim();
  if (!token) {
    return { ok: false, skipped: true, reason: "no_token" };
  }
  setAccessToken(token);
  const resolvedTenant = String(tenantId ?? getTenantId() ?? "default").trim() || "default";
  setTenantId(resolvedTenant);
  const result = await saveLlmSettings({
    backend_base_url: String(backendBaseUrl ?? defaultBackendBaseUrl()).trim(),
    backend_access_token: token,
  });
  return { ok: true, ...result };
}

let ensureSyncInFlight = null;

/**
 * 已有登录态时把 token 同步到 Sidecar（无需重新登录）。
 * Sidecar 重启、首次启用后台评估、或登录时 Sidecar 不可达后恢复，都会用到。
 */
export async function ensureEvaluationCredentialsSynced({ force = false } = {}) {
  const token = String(getAccessToken() ?? "").trim();
  if (!token) {
    return { ok: false, skipped: true, reason: "no_token" };
  }

  if (!force) {
    try {
      const settings = await fetchLlmSettings();
      if (isEvaluationReady(settings)) {
        return { ok: true, skipped: true, reason: "already_ready" };
      }
    } catch {
      /* Sidecar 暂不可达，仍尝试写入 */
    }
  }

  if (ensureSyncInFlight) return ensureSyncInFlight;
  ensureSyncInFlight = syncBackendCredentialsFromLogin({ accessToken: token })
    .finally(() => {
      ensureSyncInFlight = null;
    });
  return ensureSyncInFlight;
}

/** Portal 登录成功后，用同一套账号换取 API token 并自动同步到 Sidecar */
export async function syncPortalCredentialsAfterLogin({ loginMethod, fields } = {}) {
  const method = String(loginMethod || "password").trim().toLowerCase();
  const form = fields || {};
  let data;
  if (method === "sms") {
    data = await loginUserSms(form.sms_phone, form.code);
  } else {
    data = await loginUser(form.username, form.password);
  }
  return syncBackendCredentialsFromLogin({
    accessToken: data.access_token,
    tenantId: data.user?.tenant_id || data.tenant?.id,
  });
}

export async function clearBackendCredentialsOnLogout() {
  setAccessToken("");
  try {
    await saveLlmSettings({ backend_access_token: "" });
  } catch {
    /* sidecar 不可达时忽略 */
  }
}
