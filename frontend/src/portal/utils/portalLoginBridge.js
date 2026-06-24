/**
 * 通过隐藏 iframe 向盈小蚁提交登录表单，在 portal 域写入 session cookie，
 * 供 CloudEmbedView 内 H5 iframe 复用同一登录态。
 */
import { getPortalBaseUrl } from "../config/cloudNav";
import { getAccessToken } from "../../api/http";
import {
  buildPortalEmbedUrl,
  clearPortalLogoutPending,
  getPortalDisplayName,
  handlePortalMessage,
  isPortalAuthenticated,
  isPortalMessageOrigin,
  PORTAL_AUTH_MESSAGE,
  PORTAL_NAVIGATE_MESSAGE,
  PORTAL_PING_MESSAGE,
  PORTAL_PONG_MESSAGE,
} from "./portalShell";

const BRIDGE_FRAME_ID = "huoke-portal-login-bridge";
const BRIDGE_FRAME_NAME = "huoke-portal-login-bridge";
const LOGIN_SUBMIT_TIMEOUT_MS = 45000;
const LOGIN_FAILURE_GRACE_MS = 2800;

function isPortalLoginPath(path) {
  const normalized = String(path || "").trim();
  return normalized === "/customer/login" || normalized === "/customer/login/";
}

function ensureBridgeFrame() {
  let frame = document.getElementById(BRIDGE_FRAME_ID);
  if (!frame) {
    frame = document.createElement("iframe");
    frame.id = BRIDGE_FRAME_ID;
    frame.name = BRIDGE_FRAME_NAME;
    frame.title = "portal-login-bridge";
    frame.setAttribute("hidden", "hidden");
    frame.setAttribute("referrerpolicy", "no-referrer-when-downgrade");
    frame.style.cssText = "position:absolute;width:0;height:0;border:0;visibility:hidden";
    document.body.appendChild(frame);
  }
  return frame;
}

function dashboardEmbedUrl() {
  return buildPortalEmbedUrl(`${getPortalBaseUrl()}/customer/dashboard`);
}

function pingBridgeFrame(frame) {
  try {
    frame.contentWindow?.postMessage({ type: PORTAL_PING_MESSAGE }, "*");
  } catch {
    /* cross-origin */
  }
}

function isPortalNavigateMessage(event) {
  if (!isPortalMessageOrigin(event.origin)) return false;
  const data = event.data;
  return Boolean(
    data &&
      typeof data === "object" &&
      data.type === PORTAL_NAVIGATE_MESSAGE &&
      typeof data.path === "string" &&
      data.path.startsWith("/"),
  );
}

function attachPortalSessionProbe(frame, options = {}) {
  const {
    timeoutMs = 10000,
    onAuthenticated,
    onTimeout,
    onFrameLoad,
    onPong,
  } = options;

  let settled = false;
  const probeTimers = [];

  const timeout = window.setTimeout(() => {
    finish(false);
  }, timeoutMs);

  function cleanup() {
    window.clearTimeout(timeout);
    window.removeEventListener("message", onMessage);
    frame.removeEventListener("load", onLoad);
    probeTimers.forEach((timer) => window.clearTimeout(timer));
  }

  function finish(ok) {
    if (settled) return;
    settled = true;
    cleanup();
    if (ok) {
      onAuthenticated?.();
    } else {
      onTimeout?.();
    }
  }

  function tryComplete() {
    if (isPortalAuthenticated()) {
      finish(true);
      return true;
    }
    return false;
  }

  function scheduleAction(delayMs, action) {
    probeTimers.push(
      window.setTimeout(() => {
        if (settled) return;
        action();
      }, delayMs),
    );
  }

  function queueDashboardProbe(delayMs = 0) {
    scheduleAction(delayMs, () => {
      frame.src = dashboardEmbedUrl();
    });
  }

  function onMessage(event) {
    if (isPortalMessageOrigin(event.origin)) {
      const data = event.data;
      if (data?.type === PORTAL_PONG_MESSAGE) {
        onPong?.(data);
      }
    }
    handlePortalMessage(event);
    if (tryComplete()) return;
    if (isPortalNavigateMessage(event)) {
      queueDashboardProbe(200);
    }
  }

  function onLoad() {
    pingBridgeFrame(frame);
    window.setTimeout(() => {
      pingBridgeFrame(frame);
      tryComplete();
    }, 400);
    onFrameLoad?.();
  }

  window.addEventListener("message", onMessage);
  frame.addEventListener("load", onLoad);

  return {
    queueDashboardProbe,
    scheduleAction,
    tryComplete,
    finish,
    cleanup,
    isSettled: () => settled,
  };
}

function scheduleLoginVerification(probe, frame) {
  // 先 ping 当前 iframe，避免过早 frame.src 跳转打断验证码登录 POST/重定向
  [0, 500, 1000, 1600, 2300, 3200, 4200, 5500, 7000, 9000, 11500, 14500, 18000, 22000, 28000, 35000].forEach(
    (delay) => {
      probe.scheduleAction(delay, () => pingBridgeFrame(frame));
    },
  );
  // dashboard 探测仅作兜底，且必须晚于首次登录响应
  [2500, 6000, 11000, 18000, 28000, 38000].forEach((delay) => {
    probe.scheduleAction(delay, () => probe.queueDashboardProbe(0));
  });
}

function buildLoginFailureMessage(fields, sawLoginPage) {
  if (fields.login_method === "sms") {
    return sawLoginPage ? "验证码错误或已过期，请重新获取" : "登录失败，请检查手机号和验证码";
  }
  return sawLoginPage ? "账号或密码错误，请检查后重试" : "登录失败，请检查账号信息";
}

/**
 * Portal cookie 仍有效时，通过隐藏 iframe 读取 huoke-shell-access-token 并写入 localStorage。
 * 桌面 embed JWT 有效期 365 天，可替代已过期的 /auth/login token（默认 60 分钟）。
 */
export function refreshAccessTokenFromPortalSession(timeoutMs = 12000) {
  return new Promise((resolve) => {
    const frame = ensureBridgeFrame();
    const initialToken = String(getAccessToken() || "").trim();
    let settled = false;

    const timeout = window.setTimeout(() => finish(null), timeoutMs);

    function finish(token) {
      if (settled) return;
      settled = true;
      window.clearTimeout(timeout);
      window.removeEventListener("message", onMessage);
      frame.removeEventListener("load", onLoad);
      const resolved = String(token || getAccessToken() || "").trim();
      resolve(resolved || null);
    }

    function tryResolveFromMessage(data) {
      if (!data || typeof data !== "object") return;
      const authType = data.type;
      if (authType !== PORTAL_AUTH_MESSAGE && authType !== "yingxiaoyi:login-success") return;
      const token = String(data.accessToken || data.access_token || "").trim();
      if (token) {
        finish(token);
        return;
      }
      const current = String(getAccessToken() || "").trim();
      if (current && current !== initialToken) {
        finish(current);
      }
    }

    function onMessage(event) {
      handlePortalMessage(event);
      if (!isPortalMessageOrigin(event.origin)) return;
      tryResolveFromMessage(event.data);
    }

    function onLoad() {
      pingBridgeFrame(frame);
      window.setTimeout(() => pingBridgeFrame(frame), 400);
      window.setTimeout(() => {
        const current = String(getAccessToken() || "").trim();
        if (current && current !== initialToken) {
          finish(current);
        }
      }, 1200);
    }

    window.addEventListener("message", onMessage);
    frame.addEventListener("load", onLoad);
    frame.src = dashboardEmbedUrl();
  });
}

/**
 * 探测 portal 域是否已有有效 session（例如刷新后 sessionStorage 丢失但 cookie 仍在）。
 */
export function probePortalSession() {
  return new Promise((resolve) => {
    const frame = ensureBridgeFrame();
    const probe = attachPortalSessionProbe(frame, {
      timeoutMs: 10000,
      onAuthenticated: () => resolve(true),
      onTimeout: () => resolve(false),
    });
    probe.queueDashboardProbe(0);
  });
}

/**
 * 向 /customer/login 提交表单，成功后由 huoke_embed.js postMessage 通知壳层。
 * 若仅返回 navigate 或 postMessage 丢失，则回退为 dashboard 探测（与重启后 probe 相同）。
 * @param {Record<string, string>} fields
 */
export function submitPortalLoginForm(fields) {
  const action = `${getPortalBaseUrl()}/customer/login?huoke_embed=1`;
  const frame = ensureBridgeFrame();

  return new Promise((resolve, reject) => {
    let settled = false;
    let formSubmitted = false;
    let loginResponseAt = 0;
    let sawLoginPage = false;
    let failureTimer = null;
    let verificationScheduled = false;

    const probe = attachPortalSessionProbe(frame, {
      timeoutMs: LOGIN_SUBMIT_TIMEOUT_MS,
      onAuthenticated: () => finishResolve({ authenticated: true }),
      onTimeout: () =>
        finishReject(new Error(buildLoginFailureMessage(fields, sawLoginPage) || "登录超时，请检查账号信息或网络连接")),
      onFrameLoad: () => {
        if (!formSubmitted || settled) return;
        loginResponseAt = Date.now();
        pingBridgeFrame(frame);
        if (verificationScheduled) return;
        verificationScheduled = true;
        scheduleLoginVerification(probe, frame);
        failureTimer = window.setTimeout(() => {
          if (settled || !sawLoginPage) return;
          finishReject(new Error(buildLoginFailureMessage(fields, true)));
        }, LOGIN_FAILURE_GRACE_MS);
      },
      onPong: (data) => {
        if (!formSubmitted || settled || !loginResponseAt) return;
        if (isPortalLoginPath(data?.path) && data?.authenticated === false) {
          sawLoginPage = true;
        }
      },
    });

    function finishResolve(value) {
      if (settled) return;
      settled = true;
      if (failureTimer) window.clearTimeout(failureTimer);
      probe.cleanup();
      resolve(value);
    }

    function finishReject(error) {
      if (settled) return;
      settled = true;
      if (failureTimer) window.clearTimeout(failureTimer);
      probe.cleanup();
      reject(error instanceof Error ? error : new Error(String(error)));
    }

    const form = document.createElement("form");
    form.method = "POST";
    form.action = action;
    form.target = BRIDGE_FRAME_NAME;
    form.style.display = "none";

    const entries = { huoke_embed: "1", ...fields };
    for (const [key, value] of Object.entries(entries)) {
      if (value == null || value === "") continue;
      const input = document.createElement("input");
      input.type = "hidden";
      input.name = key;
      input.value = String(value);
      form.appendChild(input);
    }

    document.body.appendChild(form);
    formSubmitted = true;
    form.submit();
    form.remove();
  });
}

/** 清除 portal 域 session cookie，返回 Promise 便于退出流程等待服务端 logout 完成 */
export function logoutPortalSession(timeoutMs = 8000) {
  const frame = ensureBridgeFrame();

  return new Promise((resolve) => {
    let settled = false;

    function finish() {
      if (settled) return;
      settled = true;
      window.clearTimeout(timeout);
      frame.removeEventListener("load", onLoad);
      clearPortalLogoutPending();
      resolve();
    }

    function onLoad() {
      finish();
    }

    const timeout = window.setTimeout(finish, timeoutMs);
    frame.addEventListener("load", onLoad);
    frame.src = `${getPortalBaseUrl()}/customer/logout`;
  });
}

/** 从 H5 页面 meta 同步展示名（原生登录后 displayName 可能尚未写入） */
export function syncPortalDisplayName(timeoutMs = 8000) {
  return new Promise((resolve) => {
    if (getPortalDisplayName()) {
      resolve(getPortalDisplayName());
      return;
    }

    const frame = ensureBridgeFrame();
    let settled = false;

    const timeout = window.setTimeout(() => {
      finish(getPortalDisplayName());
    }, timeoutMs);

    function finish(name) {
      if (settled) return;
      settled = true;
      window.clearTimeout(timeout);
      window.removeEventListener("message", onMessage);
      frame.removeEventListener("load", onLoad);
      resolve(name || "");
    }

    function onMessage(event) {
      handlePortalMessage(event);
      if (getPortalDisplayName()) {
        finish(getPortalDisplayName());
      }
    }

    function onLoad() {
      pingBridgeFrame(frame);
      window.setTimeout(() => pingBridgeFrame(frame), 400);
    }

    window.addEventListener("message", onMessage);
    frame.addEventListener("load", onLoad);
    frame.src = dashboardEmbedUrl();
  });
}
