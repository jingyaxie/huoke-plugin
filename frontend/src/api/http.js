import axios from "axios";

export function getApiBaseUrl() {
  const configured = import.meta.env.VITE_API_BASE_URL;
  if (configured) return configured;
  // 桌面安装包 / production 构建无本地 /api 代理，必须直连云端
  if (import.meta.env.PROD) return "https://www.tanjiyunai.com/api";
  return "/api";
}

/** 将 HTTP API base 转为 WebSocket base（支持相对路径 /api） */
export function getWsApiBaseUrl() {
  const base = getApiBaseUrl();
  if (base.startsWith("/")) {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${window.location.host}${base}`;
  }
  return base.replace(/^http/, "ws");
}

const baseURL = getApiBaseUrl();
export const TENANT_STORAGE_KEY = "huoke_tenant_id";
export const PLATFORM_STORAGE_KEY = "huoke_platform_id";
export const ACCOUNT_STORAGE_KEY = "huoke_account_id";
export const API_KEY_STORAGE_KEY = "huoke_api_key";
export const ACCESS_TOKEN_STORAGE_KEY = "huoke_access_token";

const http = axios.create({
  baseURL,
  timeout: 30000,
});

export function getTenantId() {
  return localStorage.getItem(TENANT_STORAGE_KEY) || "default";
}

export function setTenantId(tenantId) {
  localStorage.setItem(TENANT_STORAGE_KEY, (tenantId || "default").trim() || "default");
}

export function getPlatformId() {
  return localStorage.getItem(PLATFORM_STORAGE_KEY) || "douyin";
}

export function setPlatformId(platformId) {
  localStorage.setItem(PLATFORM_STORAGE_KEY, (platformId || "douyin").trim().toLowerCase() || "douyin");
}

export function getAccountId() {
  return localStorage.getItem(ACCOUNT_STORAGE_KEY) || "default";
}

export function setAccountId(accountId) {
  localStorage.setItem(ACCOUNT_STORAGE_KEY, (accountId || "default").trim() || "default");
}

export function getApiKey() {
  return localStorage.getItem(API_KEY_STORAGE_KEY) || "";
}

export function setApiKey(apiKey) {
  localStorage.setItem(API_KEY_STORAGE_KEY, (apiKey || "").trim());
}

export function getAccessToken() {
  return localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY) || "";
}

export function setAccessToken(token) {
  localStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, (token || "").trim());
}

http.interceptors.request.use((config) => {
  config.headers["X-Tenant-Id"] = getTenantId();
  config.headers["X-Platform-Id"] = getPlatformId();
  config.headers["X-Account-Id"] = getAccountId();
  const apiKey = getApiKey();
  if (apiKey) {
    config.headers["X-API-Key"] = apiKey;
  }
  const accessToken = getAccessToken();
  if (accessToken && !config._skipAuth) {
    config.headers.Authorization = `Bearer ${accessToken}`;
  }
  return config;
});

http.interceptors.response.use(
  (response) => response,
  async (error) => {
    const status = error.response?.status;
    const detail = String(error.response?.data?.detail || "");
    const hadToken = Boolean(getAccessToken());
    const message = String(error.response?.data?.message || "").toLowerCase();
    const tokenRejected =
      status === 401 &&
      hadToken &&
      (
        detail.includes("登录令牌")
        || detail.includes("登录用户无效")
        || detail.includes("请先登录")
        || message.includes("token_expired")
      );
    if (tokenRejected) {
      setAccessToken("");
      const config = error.config;
      if (config && !config._retriedWithoutAuth) {
        config._retriedWithoutAuth = true;
        config._skipAuth = true;
        delete config.headers.Authorization;
        return http.request(config);
      }
    }
    return Promise.reject(error);
  }
);

export default http;
