import { isPortalEnabled, readPortalAuth } from "../portal";

/** 可访问「设置」的云端登录账号（手机号） */
export const SETTINGS_ADMIN_PHONE = "18550031362";

export function normalizeLoginAccount(value) {
  const digits = String(value || "").replace(/\D/g, "");
  if (digits.length >= 11) {
    return digits.slice(-11);
  }
  return digits;
}

export function getPortalLoginAccount() {
  const auth = readPortalAuth();
  if (!auth) return "";
  return normalizeLoginAccount(auth.username || auth.displayName);
}

/** 仅指定手机号登录后可见/可进入设置 */
export function canAccessSettings() {
  if (!isPortalEnabled()) return false;
  return getPortalLoginAccount() === SETTINGS_ADMIN_PHONE;
}
