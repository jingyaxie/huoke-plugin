/**
 * 通过隐藏 iframe 向盈小蚁提交登录表单，在 portal 域写入 session cookie，
 * 供 CloudEmbedView 内 H5 iframe 复用同一登录态。
 */
import { getPortalBaseUrl } from "../config/cloudNav";
import {
  buildPortalEmbedUrl,
  getPortalDisplayName,
  handlePortalMessage,
  isPortalAuthenticated,
  isPortalMessageOrigin,
  PORTAL_NAVIGATE_MESSAGE,
  PORTAL_PING_MESSAGE,
} from "./portalShell";

const BRIDGE_FRAME_ID = "huoke-portal-login-bridge";
const BRIDGE_FRAME_NAME = "huoke-portal-login-bridge";

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

  function queueDashboardProbe(delayMs = 0) {
    probeTimers.push(
      window.setTimeout(() => {
        if (settled) return;
        frame.src = dashboardEmbedUrl();
      }, delayMs),
    );
  }

  function onMessage(event) {
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
    tryComplete,
    finish,
    cleanup,
  };
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

    const probe = attachPortalSessionProbe(frame, {
      timeoutMs: 30000,
      onAuthenticated: () => finishResolve({ authenticated: true }),
      onTimeout: () => finishReject(new Error("登录超时，请检查账号信息或网络连接")),
      onFrameLoad: () => {
        if (!formSubmitted || settled) return;
        probe.queueDashboardProbe(300);
        probe.queueDashboardProbe(1200);
      },
    });

    function finishResolve(value) {
      if (settled) return;
      settled = true;
      probe.cleanup();
      resolve(value);
    }

    function finishReject(error) {
      if (settled) return;
      settled = true;
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

    [800, 1800, 3500, 6000].forEach((delay) => probe.queueDashboardProbe(delay));
  });
}

/** 清除 portal 域 session cookie */
export function logoutPortalSession() {
  const frame = ensureBridgeFrame();
  frame.src = `${getPortalBaseUrl()}/customer/logout`;
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
