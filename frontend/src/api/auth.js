import { getApiBaseUrl, getAccessToken, setAccessToken, setTenantId } from "./http";

const baseURL = getApiBaseUrl();

function formatApiError(data, fallback) {
  const detail = data?.detail || data?.message;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((item) => item?.msg || JSON.stringify(item)).join("；");
  }
  return fallback;
}

function unwrapApiData(payload) {
  if (payload && typeof payload === "object" && payload.data != null && payload.code === 0) {
    return payload.data;
  }
  return payload;
}

function authHeaders() {
  const headers = {
    "Content-Type": "application/json",
    "X-Client-Type": "pc",
  };
  const token = getAccessToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  return headers;
}

export async function registerUser(payload) {
  const resp = await fetch(`${baseURL}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const raw = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(formatApiError(raw, "注册失败"));
  const data = unwrapApiData(raw);
  if (data.access_token) setAccessToken(data.access_token);
  if (data.user?.tenant_id) setTenantId(data.user.tenant_id);
  return data;
}

export async function loginUser(username, password) {
  const resp = await fetch(`${baseURL}/auth/login`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify({ identifier: username, password }),
  });
  const raw = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(formatApiError(raw, "登录失败"));
  const data = unwrapApiData(raw);
  if (data.access_token) setAccessToken(data.access_token);
  if (data.user?.tenant_id) setTenantId(data.user.tenant_id);
  return data;
}

export async function loginUserSms(phone, code) {
  const resp = await fetch(`${baseURL}/auth/login-sms`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify({ phone, code }),
  });
  const raw = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(formatApiError(raw, "登录失败"));
  const data = unwrapApiData(raw);
  if (data.access_token) setAccessToken(data.access_token);
  if (data.user?.tenant_id) setTenantId(data.user.tenant_id);
  return data;
}

export async function fetchAuthMe() {
  const resp = await fetch(`${baseURL}/auth/me`, { headers: authHeaders() });
  const raw = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(formatApiError(raw, "获取当前用户失败"));
  return unwrapApiData(raw);
}

export async function fetchUsers() {
  const resp = await fetch(`${baseURL}/users`, { headers: authHeaders() });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data.detail || "获取用户列表失败");
  return data;
}

export async function fetchUserById(userId) {
  const resp = await fetch(`${baseURL}/users/${userId}`, { headers: authHeaders() });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data.detail || "获取用户失败");
  return data;
}

export async function fetchCurrentTenant() {
  const resp = await fetch(`${baseURL}/tenants/me`, { headers: authHeaders() });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data.detail || "获取租户失败");
  return data;
}

export function logoutUser() {
  setAccessToken("");
}
