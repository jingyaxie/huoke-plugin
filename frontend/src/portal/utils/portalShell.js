/** 盈小蚁 iframe 嵌入 Huoke 壳层时的 postMessage 协议 */
import { getPortalBaseUrl } from "../config/cloudNav";
import { isLocalAcquisitionPath } from "../config/authPaths";
import { setAccessToken, setTenantId } from "../../api/http";
import { syncBackendCredentialsFromLogin, ensureEvaluationCredentialsSynced } from "../../api/commentEvaluation";

export const PORTAL_AUTH_MESSAGE = "huoke:portal-authenticated";
export const PORTAL_PING_MESSAGE = "huoke:shell-ping";
export const PORTAL_PONG_MESSAGE = "huoke:shell-pong";
export const PORTAL_NAVIGATE_MESSAGE = "huoke:navigate";
export const PORTAL_AUTH_STORAGE_KEY = "huoke_portal_auth";
export const PORTAL_LOGOUT_FLAG_KEY = "huoke_portal_logout_pending";
export const PORTAL_SHELL_STORAGE_KEY = "huoke_shell_app";

const PORTAL_ORIGIN_SUFFIXES = ["tanjiyunai.com"];

export function isPortalEnabled() {
  const flag = import.meta.env.VITE_PORTAL_ENABLED;
  if (flag === "0" || flag === "false") return false;
  return true;
}

export function buildPortalEmbedUrl(baseUrl) {
  const resolved = baseUrl || `${getPortalBaseUrl()}/customer/dashboard`;
  try {
    const url = new URL(resolved);
    url.searchParams.set("huoke_embed", "1");
    return url.toString();
  } catch {
    const joiner = resolved.includes("?") ? "&" : "?";
    return `${resolved}${joiner}huoke_embed=1`;
  }
}

export function buildPortalLoginUrl() {
  return buildPortalEmbedUrl(`${getPortalBaseUrl()}/customer/login`);
}

export function isPortalMessageOrigin(origin) {
  if (!origin || typeof origin !== "string") return false;
  if (origin === "null") return false;
  try {
    const { hostname, protocol } = new URL(origin);
    if (protocol !== "https:" && protocol !== "http:") return false;
    return PORTAL_ORIGIN_SUFFIXES.some((suffix) => hostname === suffix || hostname.endsWith(`.${suffix}`));
  } catch {
    return false;
  }
}

export function isPortalAuthMessage(data) {
  if (!data || typeof data !== "object") return false;
  if (data.type === PORTAL_AUTH_MESSAGE || data.type === "yingxiaoyi:login-success") {
    return data.authenticated !== false;
  }
  return data.type === PORTAL_PONG_MESSAGE && data.authenticated === true;
}

export function readPortalAuth() {
  try {
    const raw = sessionStorage.getItem(PORTAL_AUTH_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || parsed.authenticated !== true) return null;
    return parsed;
  } catch {
    return null;
  }
}

export function isPortalAuthenticated() {
  return Boolean(readPortalAuth()?.authenticated);
}

export function setPortalAuthenticated(payload = {}) {
  const prev = readPortalAuth() || {};
  const displayName =
    String(payload.displayName || payload.userName || prev.displayName || prev.username || "").trim();
  const username = String(payload.username || prev.username || displayName || "").trim();
  const next = {
    authenticated: true,
    displayName,
    username,
    path: payload.path || prev.path || "",
    at: Date.now(),
  };
  sessionStorage.setItem(PORTAL_AUTH_STORAGE_KEY, JSON.stringify(next));

  const accessToken = String(payload.accessToken || payload.access_token || "").trim();
  const tenantId = String(payload.tenantId || payload.tenant_id || "").trim();
  if (accessToken) {
    setAccessToken(accessToken);
    if (tenantId) setTenantId(tenantId);
    void syncBackendCredentialsFromLogin({ accessToken, tenantId }).catch(() => {});
  } else {
    void ensureEvaluationCredentialsSynced().catch(() => {});
  }

  window.dispatchEvent(new CustomEvent("huoke-portal-auth-changed", { detail: next }));
  return next;
}

export function clearPortalAuth() {
  sessionStorage.removeItem(PORTAL_AUTH_STORAGE_KEY);
  window.dispatchEvent(new CustomEvent("huoke-portal-auth-changed", { detail: null }));
}

/** 主动退出后跳过登录页 session 探测，避免 cookie 尚未清完时被误判为仍在线 */
export function markPortalLogoutPending() {
  sessionStorage.setItem(PORTAL_LOGOUT_FLAG_KEY, String(Date.now()));
}

export function isPortalLogoutPending() {
  return Boolean(sessionStorage.getItem(PORTAL_LOGOUT_FLAG_KEY));
}

export function clearPortalLogoutPending() {
  sessionStorage.removeItem(PORTAL_LOGOUT_FLAG_KEY);
}

export function getPortalDisplayName() {
  const auth = readPortalAuth();
  if (!auth) return "";
  return String(auth.displayName || auth.username || "").trim();
}

/** Tauri 桌面（withGlobalTauri 可能为 false）或本地 FastAPI 托管的前端 */
export function detectNativeShell() {
  if (typeof window === "undefined") return false;
  if (window.__TAURI__ || window.__TAURI_INTERNALS__) return true;
  const { hostname, port } = window.location;
  return (hostname === "127.0.0.1" || hostname === "localhost") && (port === "8000" || port === "18765");
}

/** 云端 H5 与本地 AI 获客页需盈小蚁登录；设置等页面不拦截 */
export function requiresPortalAuth(path) {
  const normalized = String(path || "").trim();
  if (normalized === "/cloud" || normalized.startsWith("/cloud/")) return true;
  return isLocalAcquisitionPath(normalized);
}

export function handlePortalMessage(event) {
  if (!isPortalMessageOrigin(event.origin)) return null;
  const data = event.data;
  if (!data || typeof data !== "object") return null;

  if (isPortalAuthMessage(data)) {
    return setPortalAuthenticated({
      displayName: data.displayName || data.userName || "",
      username: data.userName || data.displayName || "",
      path: data.path || "",
      accessToken: data.accessToken || data.access_token || "",
      tenantId: data.tenantId || data.tenant_id || "",
    });
  }

  if (data.type === PORTAL_NAVIGATE_MESSAGE && typeof data.path === "string" && data.path.startsWith("/")) {
    if (data.path.startsWith("/customer/") && !data.path.startsWith("/customer/login")) {
      setPortalAuthenticated({
        displayName: data.displayName || data.userName || readPortalAuth()?.displayName || "",
        username: data.userName || readPortalAuth()?.username || readPortalAuth()?.displayName || "",
        path: data.path,
      });
    }
    return { navigate: data.path };
  }

  return null;
}
