import { getAccountId, getApiBaseUrl, getApiKey, getAccessToken, getPlatformId, getTenantId } from "./http";

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

export async function fetchSupportedBindPlatforms() {
  const resp = await fetch(`${baseURL}/accounts/platforms/supported`, { headers: headers() });
  if (!resp.ok) throw new Error("获取平台列表失败");
  return resp.json();
}

export async function fetchAccounts() {
  const resp = await fetch(`${baseURL}/accounts`, { headers: headers() });
  if (!resp.ok) throw new Error("获取账号列表失败");
  return resp.json();
}

export async function createAccount(id, label) {
  const resp = await fetch(`${baseURL}/accounts`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ id, label }),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || "创建账号失败");
  }
  return resp.json();
}

export async function setActiveAccount(accountId) {
  const resp = await fetch(`${baseURL}/accounts/active/${encodeURIComponent(accountId)}`, {
    method: "POST",
    headers: headers(),
  });
  if (!resp.ok) throw new Error("切换账号失败");
  return resp.json();
}

export async function deleteAccount(accountId) {
  const resp = await fetch(`${baseURL}/accounts/${encodeURIComponent(accountId)}`, {
    method: "DELETE",
    headers: headers(),
  });
  if (!resp.ok) throw new Error("删除账号失败");
  return resp.json();
}

export async function fetchAccountBindings(accountId) {
  const resp = await fetch(`${baseURL}/accounts/${encodeURIComponent(accountId)}/bindings`, {
    headers: headers(),
  });
  if (!resp.ok) throw new Error("获取绑定状态失败");
  return resp.json();
}

export async function triggerAccountPlatformLogin(accountId, platform, { restore = false } = {}) {
  const resp = await fetch(
    `${baseURL}/accounts/${encodeURIComponent(accountId)}/platforms/${encodeURIComponent(platform)}/server-login`,
    {
      method: "POST",
      headers: headers(),
      body: JSON.stringify({ restore: !!restore }),
    },
  );
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || "启动登录失败");
  }
  return resp.json();
}

export async function fetchAccountPlatformLoginStatus(accountId, platform) {
  const resp = await fetch(
    `${baseURL}/accounts/${encodeURIComponent(accountId)}/platforms/${encodeURIComponent(platform)}/login-status`,
    { headers: headers() }
  );
  if (!resp.ok) throw new Error("查询登录状态失败");
  return resp.json();
}

export async function createAccountPlatformQrLogin(accountId, platform, { refresh = true } = {}) {
  const resp = await fetch(
    `${baseURL}/accounts/${encodeURIComponent(accountId)}/platforms/${encodeURIComponent(platform)}/qr-login`,
    {
      method: "POST",
      headers: headers(),
      body: JSON.stringify({ refresh }),
    }
  );
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || "获取登录二维码失败");
  }
  return resp.json();
}

export async function fetchAccountPlatformQrLoginStatus(accountId, platform, sessionId) {
  const resp = await fetch(
    `${baseURL}/accounts/${encodeURIComponent(accountId)}/platforms/${encodeURIComponent(platform)}/qr-login/${encodeURIComponent(sessionId)}`,
    { headers: headers() }
  );
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || "查询二维码状态失败");
  }
  return resp.json();
}

export async function cancelAccountPlatformQrLogin(accountId, platform, sessionId) {
  const resp = await fetch(
    `${baseURL}/accounts/${encodeURIComponent(accountId)}/platforms/${encodeURIComponent(platform)}/qr-login/${encodeURIComponent(sessionId)}`,
    { method: "DELETE", headers: headers() }
  );
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || "取消二维码登录失败");
  }
  return resp.json();
}

export async function clearAccountPlatformLoginSession(accountId, platform) {
  const resp = await fetch(
    `${baseURL}/accounts/${encodeURIComponent(accountId)}/platforms/${encodeURIComponent(platform)}/login-session`,
    { method: "DELETE", headers: headers() }
  );
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || "清除登录记录失败");
  }
  return resp.json();
}

export async function confirmPlatformBinding(accountId, platform, { label } = {}) {
  const resp = await fetch(
    `${baseURL}/accounts/${encodeURIComponent(accountId)}/platforms/${encodeURIComponent(platform)}/confirm-binding`,
    {
      method: "POST",
      headers: headers(),
      body: JSON.stringify({ label: label || null }),
    },
  );
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || "确认绑定失败");
  }
  return resp.json();
}

export async function verifyPlatformLogin(accountId, platform, { refresh = true } = {}) {
  const resp = await fetch(
    `${baseURL}/accounts/${encodeURIComponent(accountId)}/platforms/${encodeURIComponent(platform)}/login-status/verify?refresh=${refresh ? "true" : "false"}`,
    { method: "POST", headers: headers() },
  );
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || "在线校验失败");
  }
  return resp.json();
}

export async function loadAllAccountBindingSnapshots() {
  const data = await fetchAccounts();
  const accounts = data.items || [];
  const snapshots = await Promise.all(
    accounts.map(async (account) => {
      try {
        const bindings = await fetchAccountBindings(account.id);
        return {
          account_id: account.id,
          label: account.label,
          platforms: bindings.platforms || [],
        };
      } catch {
        return { account_id: account.id, label: account.label, platforms: [] };
      }
    }),
  );
  return { accounts, activeAccountId: data.active_account_id, snapshots };
}

export async function enrichRowsWithAuthExpiry(rows) {
  return Promise.all(
    rows.map(async (row) => {
      if (!row.is_bound) return row;
      try {
        const status = await fetchAccountPlatformLoginStatus(row.huoke_account_id, row.platform);
        return {
          ...row,
          auth_expires_at: status.cookie_expires_at || status.expired_at || null,
          cookie_ready: !!status.cookie_ready,
        };
      } catch {
        return row;
      }
    }),
  );
}
