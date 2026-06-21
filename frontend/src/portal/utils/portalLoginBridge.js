/**
 * 通过隐藏 iframe 向盈小蚁提交登录表单，在 portal 域写入 session cookie，
 * 供 CloudEmbedView 内 H5 iframe 复用同一登录态。
 */
import { getPortalBaseUrl } from "../config/cloudNav";
import {
  buildPortalEmbedUrl,
  handlePortalMessage,
  isPortalAuthenticated,
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

function pingBridgeFrame(frame) {
  try {
    frame.contentWindow?.postMessage({ type: PORTAL_PING_MESSAGE }, "*");
  } catch {
    /* cross-origin */
  }
}

/**
 * 探测 portal 域是否已有有效 session（例如刷新后 sessionStorage 丢失但 cookie 仍在）。
 */
export function probePortalSession() {
  return new Promise((resolve) => {
    const frame = ensureBridgeFrame();
    let settled = false;

    const timeout = window.setTimeout(() => {
      finish(false);
    }, 10000);

    function finish(ok) {
      if (settled) return;
      settled = true;
      window.clearTimeout(timeout);
      window.removeEventListener("message", onMessage);
      frame.removeEventListener("load", onLoad);
      resolve(ok);
    }

    function onMessage(event) {
      const result = handlePortalMessage(event);
      if (!result || result.navigate) return;
      if (isPortalAuthenticated()) {
        finish(true);
      }
    }

    function onLoad() {
      pingBridgeFrame(frame);
      window.setTimeout(() => pingBridgeFrame(frame), 400);
    }

    window.addEventListener("message", onMessage);
    frame.addEventListener("load", onLoad);
    frame.src = buildPortalEmbedUrl(`${getPortalBaseUrl()}/customer/dashboard`);
  });
}

/**
 * 向 /customer/login 提交表单，成功后由 huoke_embed.js postMessage 通知壳层。
 * @param {Record<string, string>} fields
 */
export function submitPortalLoginForm(fields) {
  const action = `${getPortalBaseUrl()}/customer/login?huoke_embed=1`;
  ensureBridgeFrame();

  return new Promise((resolve, reject) => {
    let settled = false;

    const timeout = window.setTimeout(() => {
      finishReject(new Error("登录超时，请检查账号信息或网络连接"));
    }, 45000);

    function finishResolve(value) {
      if (settled) return;
      settled = true;
      window.clearTimeout(timeout);
      window.removeEventListener("message", onMessage);
      resolve(value);
    }

    function finishReject(error) {
      if (settled) return;
      settled = true;
      window.clearTimeout(timeout);
      window.removeEventListener("message", onMessage);
      reject(error instanceof Error ? error : new Error(String(error)));
    }

    function onMessage(event) {
      const result = handlePortalMessage(event);
      if (!result || result.navigate) return;
      if (isPortalAuthenticated()) {
        finishResolve(result);
      }
    }

    window.addEventListener("message", onMessage);

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
    form.submit();
    form.remove();
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
    frame.src = buildPortalEmbedUrl(`${getPortalBaseUrl()}/customer/dashboard`);
  });
}
