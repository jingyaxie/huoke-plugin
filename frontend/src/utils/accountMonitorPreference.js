const STORAGE_KEY = "huoke-platform-monitor";

export function isPlatformMonitorEnabled(accountId, platform) {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return false;
    const data = JSON.parse(raw);
    return !!data?.[`${accountId}:${platform}`];
  } catch {
    return false;
  }
}

export function setPlatformMonitorEnabled(accountId, platform, enabled) {
  let data = {};
  try {
    data = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}") || {};
  } catch {
    data = {};
  }
  const key = `${accountId}:${platform}`;
  if (enabled) data[key] = true;
  else delete data[key];
  localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
}
