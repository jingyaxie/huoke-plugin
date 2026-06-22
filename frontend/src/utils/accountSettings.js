import { isPlatformMonitorEnabled } from "./accountMonitorPreference";

import { EXTENSION_UI_PLATFORM_IDS } from "../config/extensionPlatformCapabilities";

/** 本机获客账号绑定支持的渠道（与 EXTENSION_UI_PLATFORM_IDS 对齐） */
export const BINDABLE_PLATFORMS = [...EXTENSION_UI_PLATFORM_IDS];

export const DISPLAY_PLATFORMS = BINDABLE_PLATFORMS;

export const DEFAULT_PLATFORM_NICKNAME = {
  douyin: "抖音账号",
  xiaohongshu: "小红书账号",
  kuaishou: "快手账号",
};

export const PLATFORM_LABEL = {
  douyin: "抖音",
  xiaohongshu: "小红书",
  kuaishou: "快手",
};

export const PLATFORM_TAG_TYPE = {
  douyin: "",
  xiaohongshu: "danger",
  kuaishou: "warning",
};

function readLoginMessage(binding) {
  const msg = binding?.message;
  return typeof msg === "string" && msg.trim() ? msg.trim() : "";
}

export function isBindingActive(binding) {
  if (binding?.cookie_ready) return true;
  const status = String(binding?.status || "").trim().toLowerCase();
  return status === "ready" || status === "authenticated" || status === "incomplete";
}

export function formatAuthExpires(iso) {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  const yyyy = date.getFullYear();
  const mm = String(date.getMonth() + 1).padStart(2, "0");
  const dd = String(date.getDate()).padStart(2, "0");
  const hh = String(date.getHours()).padStart(2, "0");
  const mi = String(date.getMinutes()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd} ${hh}:${mi}`;
}

export function buildAccountSettingsRows(snapshots) {
  const rows = [];
  for (const snapshot of snapshots || []) {
    const accountId = snapshot.account_id;
    const accountLabel = snapshot.label || accountId;
    const bindingMap = new Map((snapshot.platforms || []).map((item) => [item.platform, item]));

    for (const platform of DISPLAY_PLATFORMS) {
      const binding = bindingMap.get(platform) || {
        platform,
        platform_label: PLATFORM_LABEL[platform],
        status: "missing",
        message: "",
      };
      const isBound = isBindingActive(binding);
      const nickname = String(binding.nickname || accountLabel || "").trim() || DEFAULT_PLATFORM_NICKNAME[platform];
      rows.push({
        key: `${accountId}:${platform}`,
        huoke_account_id: accountId,
        huoke_account_label: accountLabel,
        platform,
        nickname,
        account_id: binding.platform_user_id || null,
        avatar_url: binding.avatar_url || null,
        cookie_ready: !!binding.cookie_ready,
        status: isBound ? binding.status || "ready" : "unbound",
        message: binding.message || "",
        is_bound: isBound,
        auth_expires_at: null,
      });
    }
  }

  return rows.sort((a, b) => {
    const platformCmp = a.platform.localeCompare(b.platform);
    if (platformCmp !== 0) return platformCmp;
    if (a.is_bound !== b.is_bound) return a.is_bound ? -1 : 1;
    return a.nickname.localeCompare(b.nickname);
  });
}

function isLoginInvalid(binding) {
  if (binding.cookie_ready) return false;
  const status = String(binding.status || "").trim().toLowerCase();
  return ["expired", "guest", "incomplete", "error", "missing"].includes(status);
}

function hadPriorBinding(binding) {
  const status = String(binding.status || "").trim().toLowerCase();
  if (status && status !== "missing") return true;
  return Number(binding.cookie_count || 0) > 0;
}

export function collectAccountHealthIssues(snapshots) {
  const issues = [];
  for (const snapshot of snapshots || []) {
    for (const binding of snapshot.platforms || []) {
      if (!DISPLAY_PLATFORMS.includes(binding.platform)) continue;
      const platform = binding.platform;
      const platformLabel = PLATFORM_LABEL[platform] || platform;
      const nickname =
        String(binding.nickname || snapshot.label || "").trim() || DEFAULT_PLATFORM_NICKNAME[platform];
      const issueKey = `${snapshot.account_id}:${platform}`;
      const loginMsg = readLoginMessage(binding);
      const isBound = isBindingActive(binding);

      if (binding.cookie_ready && (loginMsg.includes("风控") || loginMsg.includes("验证码"))) {
        issues.push({
          issueKey,
          platform,
          platformLabel,
          nickname,
          kind: "risk_control",
          severity: "warning",
          title: `${platformLabel}触发平台风控`,
          message: loginMsg || `「${nickname}」可能触发平台风控，请在浏览器完成验证`,
        });
      }

      if (isBound && hadPriorBinding(binding) && isLoginInvalid(binding)) {
        issues.push({
          issueKey,
          platform,
          platformLabel,
          nickname,
          kind: "login_invalid",
          severity: "error",
          title: `${platformLabel}登录失效`,
          message: loginMsg || `「${nickname}」本机登录态无效，请重新绑定`,
        });
      }
    }
  }

  const byKey = new Map();
  const priority = ["risk_control", "login_invalid"];
  for (const issue of issues) {
    const existing = byKey.get(issue.issueKey);
    if (!existing) {
      byKey.set(issue.issueKey, issue);
      continue;
    }
    if (priority.indexOf(issue.kind) < priority.indexOf(existing.kind)) {
      byKey.set(issue.issueKey, issue);
    }
  }
  return Array.from(byKey.values());
}

export function issueBadgeLabel(issue) {
  if (issue.kind === "risk_control") return issue.severity === "error" ? "风控受限" : "风控关注";
  return "登录失效";
}

export function findHealthIssueForRow(issues, row) {
  return (issues || []).find((item) => item.issueKey === row.key);
}

export function avatarInitial(text) {
  const value = String(text || "?").trim();
  return value ? value.slice(0, 1) : "?";
}

export { isPlatformMonitorEnabled };
