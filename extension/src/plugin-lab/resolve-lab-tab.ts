const PLATFORM_TAB_PATTERNS = [
  "https://www.douyin.com/*",
  "https://*.douyin.com/*",
  "https://www.xiaohongshu.com/*",
  "https://*.xiaohongshu.com/*",
  "https://www.kuaishou.com/*",
  "https://*.kuaishou.com/*",
];

async function focusTab(tab: chrome.tabs.Tab) {
  if (!tab.id || tab.windowId === undefined) return;
  await chrome.windows.update(tab.windowId, { focused: true });
  await chrome.tabs.update(tab.id, { active: true });
}

export async function resolveLabTargetTab(): Promise<chrome.tabs.Tab> {
  const tabs = await chrome.tabs.query({ url: PLATFORM_TAB_PATTERNS });
  if (tabs.length === 0) {
    throw new Error("no platform tab open — run step 1 open_browser first");
  }

  const tab = [...tabs].sort((a, b) => (b.lastAccessed ?? 0) - (a.lastAccessed ?? 0))[0];
  await focusTab(tab);
  return tab;
}
