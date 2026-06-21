import { getPortalBaseUrl } from "../config/cloudNav";

const API_PREFIX = "/api";

function portalApiUrl(path) {
  const base = getPortalBaseUrl();
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return `${base}${API_PREFIX}${normalized}`;
}

function formatApiError(payload, fallback) {
  const message = payload?.message;
  if (typeof message === "string" && message) return message;
  const detail = payload?.data?.detail;
  if (typeof detail === "string" && detail) return detail;
  return fallback;
}

export function mapPortalSmsError(payload) {
  const code = payload?.message ? String(payload.message) : "";
  if (code === "invalid_phone") return "手机号格式错误";
  if (code === "invalid_param") return "请输入手机号";
  if (code === "sms_not_configured") return "短信服务暂不可用";
  if (code === "account_not_found") return "账号未开通，请联系负责人在后台开通";
  if (code === "account_pending_approval") return "账号待管理员放行";
  if (code === "account_disabled") return "账号已被禁用，请联系管理员";
  if (code === "customer_login_forbidden") return "当前账号暂无客户后台权限";
  if (code === "sms_send_failed") {
    return payload?.data?.detail || "发送验证码失败";
  }
  if (code === "sms_rate_limited") return payload?.data?.detail || "短信发送过于频繁";
  return code || "发送验证码失败";
}

/** 发送客户后台登录短信验证码 */
export async function sendPortalSmsCode(phone) {
  const response = await fetch(portalApiUrl("/auth/send-sms-code"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ phone, scene: "customer" }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload.code !== 0) {
    throw new Error(mapPortalSmsError(payload));
  }
  return payload.data || {};
}

export { portalApiUrl, formatApiError };
