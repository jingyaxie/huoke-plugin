import { getAccessToken, setAccessToken } from "./http";

export function isTokenExpiredError(err) {
  const status = err?.response?.status;
  const message = String(
    err?.response?.data?.message
      || err?.response?.data?.detail
      || err?.message
      || "",
  ).toLowerCase();
  return status === 401 && (
    message.includes("token_expired")
    || message.includes("登录令牌")
    || message.includes("登录用户无效")
    || message.includes("请先登录")
    || message.includes("unauthorized")
  );
}

export function clearAccessToken() {
  setAccessToken("");
}

export function hasAccessToken() {
  return Boolean(String(getAccessToken() || "").trim());
}
