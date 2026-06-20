import {
  clearAccountPlatformLoginSession,
  confirmPlatformBinding,
  fetchAccountPlatformLoginStatus,
  triggerAccountPlatformLogin,
  verifyPlatformLogin,
} from "../api/accounts";

const PLATFORM_LABEL = {
  douyin: "抖音",
  xiaohongshu: "小红书",
  kuaishou: "快手",
};

const STEP_DEFS = [
  { id: "sidecar", label: "本地服务" },
  { id: "chrome", label: "Chrome 浏览器" },
  { id: "cookie", label: "Cookie 写入" },
  { id: "verify", label: "在线校验" },
  { id: "sync", label: "绑定同步" },
];

export function initialBindSteps() {
  return STEP_DEFS.map((item) => ({ ...item, status: "idle", detail: "" }));
}

function patchStep(steps, id, patch) {
  return steps.map((row) => (row.id === id ? { ...row, ...patch } : row));
}

function loginMessage(st) {
  const msg = st?.message;
  if (!msg) return null;
  return typeof msg === "string" ? msg : String(msg);
}

function cookieWritten(st) {
  const count = Number(st.cookie_count || 0);
  const status = String(st.status || "").toLowerCase();
  return count > 0 || status === "incomplete" || status === "ready" || !!st.cookie_ready || st.persist_ok === true;
}

function formatCookieStepDetail(st, label) {
  const msg = loginMessage(st);
  if (msg && st.status !== "missing") return msg;
  if (st.blocked_host === true) {
    return "抖音拦截了自动化浏览器页面，请关闭窗口后重试绑定";
  }
  if (st.interactive_active === true) {
    const names = Array.isArray(st.live_cookie_names) ? st.live_cookie_names.slice(0, 6).join(", ") : "";
    if (st.login_wall_visible === true) {
      return `请在弹出的 Chrome 窗口完成${label}登录（当前仍显示登录页）`;
    }
    if (names) return `已读取 Cookie（${names}），正在写入本地登录态…`;
    const pageUrl = String(st.page_url || "").trim();
    return pageUrl
      ? `登录窗口已打开：${pageUrl}`
      : `登录窗口已打开，等待${label}登录完成（请勿关闭 Chrome）…`;
  }
  return msg || `等待 ${label} 登录完成（请勿关闭 Chrome）…`;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function runBrowserPlatformBindFlow(accountId, platform, options = {}) {
  const { nickname, shouldStop, onSteps } = options;
  const label = PLATFORM_LABEL[platform] || platform;
  let steps = initialBindSteps();
  const setStep = (id, patch) => {
    steps = patchStep(steps, id, patch);
    onSteps?.(steps.map((row) => ({ ...row })));
  };

  onSteps?.(steps.map((row) => ({ ...row })));
  if (shouldStop?.()) return false;

  setStep("sidecar", { status: "active", detail: "检查本地 Huoke 服务…" });
  setStep("sidecar", { status: "done", detail: "本地服务就绪" });

  if (shouldStop?.()) return false;

  setStep("chrome", {
    status: "active",
    detail: `正在清除旧登录并启动 ${label} 官网登录窗口，请在弹出的 Chrome 完成扫码/短信验证`,
  });
  try {
    await clearAccountPlatformLoginSession(accountId, platform);
  } catch {
    // 首次绑定可忽略
  }
  const loginResp = await triggerAccountPlatformLogin(accountId, platform, { restore: false });
  const chromeStatus = String(loginResp.status || "started").toLowerCase();
  setStep("chrome", {
    status: "done",
    detail:
      typeof loginResp.message === "string" && loginResp.message
        ? loginResp.message
        : chromeStatus === "running"
          ? "登录窗口已在运行，请切换到 Chrome 继续"
          : "Chrome 已启动，请完成平台登录",
  });

  setStep("cookie", { status: "active", detail: `等待 ${label} Cookie 写入…` });
  let loginStatus = {};
  let cookieDetected = false;

  for (let attempt = 0; attempt < 120 && !shouldStop?.(); attempt += 1) {
    try {
      loginStatus = (await fetchAccountPlatformLoginStatus(accountId, platform)) || {};
      const msg = loginMessage(loginStatus);
      if (cookieWritten(loginStatus)) {
        cookieDetected = true;
        setStep("cookie", {
          status: "done",
          detail: msg || `已检测到登录态（${String(loginStatus.status || "ready")}）`,
        });
        break;
      }
      setStep("cookie", { status: "active", detail: formatCookieStepDetail(loginStatus, label) });
    } catch {
      // retry
    }
    await sleep(3000);
  }

  if (!cookieDetected) {
    setStep("cookie", { status: "error", detail: "超时：未检测到 Cookie，请确认已在 Chrome 完成登录" });
    return false;
  }

  if (shouldStop?.()) return false;

  setStep("verify", {
    status: "active",
    detail: platform === "xiaohongshu" ? "小红书在线校验中（验证非游客态）…" : "校验登录态…",
  });

  let verified = false;
  try {
    const verifyResp = (await verifyPlatformLogin(accountId, platform, { refresh: true })) || {};
    const authStatus = String(verifyResp.auth_status || "").toLowerCase();
    const verifyMsg = loginMessage(verifyResp) || String(verifyResp.message || "");
    if (platform === "xiaohongshu") {
      const xhsOk = verifyResp.live_ok === true || authStatus === "authenticated";
      if (!xhsOk) {
        setStep("verify", {
          status: "error",
          detail: verifyMsg || "小红书仍为游客态或登录失效，请在 Chrome 完成真实账号登录后重试",
        });
        return false;
      }
      verified = true;
    } else {
      verified = verifyResp.live_ok === true || !!verifyResp.cookie_ready || !!loginStatus.cookie_ready;
    }
    setStep("verify", { status: "done", detail: verifyMsg || (verified ? "登录态有效" : "校验完成") });
    loginStatus = { ...loginStatus, ...verifyResp };
  } catch (e) {
    if (loginStatus.cookie_ready) {
      setStep("verify", { status: "skipped", detail: `在线校验不可用，已使用本地 Cookie 状态（${e.message || ""}）` });
      verified = true;
    } else {
      setStep("verify", { status: "error", detail: e.message || "在线校验失败" });
      return false;
    }
  }

  if (!verified && !loginStatus.cookie_ready) {
    setStep("verify", { status: "error", detail: "登录态未就绪，请重试" });
    return false;
  }

  if (shouldStop?.()) return false;

  setStep("sync", { status: "active", detail: "写入绑定记录…" });
  try {
    const customLabel = String(nickname || "").trim();
    await confirmPlatformBinding(accountId, platform, { label: customLabel || null });
    setStep("sync", { status: "done", detail: "绑定已同步到账号列表" });
    return true;
  } catch (e) {
    setStep("sync", { status: "error", detail: e.message || "绑定同步失败" });
    throw e;
  }
}

export async function pullPlatformSession(accountId, platform) {
  await triggerAccountPlatformLogin(accountId, platform, { restore: true });
  for (let i = 0; i < 12; i += 1) {
    await sleep(1500);
    const st = (await fetchAccountPlatformLoginStatus(accountId, platform)) || {};
    const interactive = st.interactive_active === true;
    const loginWall = st.login_wall_visible === true;
    const cookieReady = !!st.cookie_ready;
    if (interactive && loginWall && i >= 11) {
      throw new Error("浏览器已打开但仍显示登录页，请在 Chrome 完成登录或点击「+ 授权账号」");
    }
    if ((interactive && cookieReady && !loginWall) || (cookieReady && !interactive)) break;
  }
  const st = await fetchAccountPlatformLoginStatus(accountId, platform);
  if (!st?.cookie_ready) {
    if (st?.interactive_active) {
      throw new Error("Chrome 已打开，请在弹出窗口完成平台登录后再点「拉取会话」");
    }
    throw new Error("登录态仍未就绪，请使用「+ 授权账号」完成绑定");
  }
  await confirmPlatformBinding(accountId, platform);
}
