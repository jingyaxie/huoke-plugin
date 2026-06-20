import { getApiBaseUrl, getAccessToken, setAccessToken, setTenantId } from "./http";

const baseURL = getApiBaseUrl();

function formatApiError(data, fallback) {
  const detail = data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((item) => item?.msg || JSON.stringify(item)).join("；");
  }
  return fallback;
}

function authHeaders() {
  const headers = { "Content-Type": "application/json" };
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
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(formatApiError(data, "注册失败"));
  if (data.access_token) setAccessToken(data.access_token);
  if (data.user?.tenant_id) setTenantId(data.user.tenant_id);
  return data;
}

export async function loginUser(username, password) {
  const resp = await fetch(`${baseURL}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(formatApiError(data, "登录失败"));
  if (data.access_token) setAccessToken(data.access_token);
  if (data.user?.tenant_id) setTenantId(data.user.tenant_id);
  return data;
}

export async function fetchAuthMe() {
  const resp = await fetch(`${baseURL}/auth/me`, { headers: authHeaders() });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(formatApiError(data, "获取当前用户失败"));
  return data;
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
