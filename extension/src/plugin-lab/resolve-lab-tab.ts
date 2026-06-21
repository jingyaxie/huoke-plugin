import {
  contextLabel,
  contextMatchesUrl,
  contextRequirementForAction,
  detectPageContext,
  isPlatformUrl,
  pinLabSession,
  readLabSession,
  scoreTabForContext,
  touchLabSession,
  type LabPageContext,
} from "./lab-context";

const PLATFORM_TAB_PATTERNS = [
  "https://www.douyin.com/*",
  "https://*.douyin.com/*",
  "https://www.xiaohongshu.com/*",
  "https://*.xiaohongshu.com/*",
  "https://www.kuaishou.com/*",
  "https://*.kuaishou.com/*",
];

export interface ResolveLabTabOptions {
  action?: string;
  /** @deprecated 使用 action 映射的上下文 */
  preferSearchPage?: boolean;
}

async function focusTab(tab: chrome.tabs.Tab) {
  if (!tab.id || tab.windowId === undefined) return;
  await chrome.windows.update(tab.windowId, { focused: true });
  await chrome.tabs.update(tab.id, { active: true });
}

async function listPlatformTabs(): Promise<chrome.tabs.Tab[]> {
  const tabs = await chrome.tabs.query({ url: PLATFORM_TAB_PATTERNS });
  return tabs.filter((tab) => isPlatformUrl(tab.url));
}

function resolveRequiredContext(options: ResolveLabTabOptions): {
  context: LabPageContext;
  strict: boolean;
} {
  if (options.action) {
    return contextRequirementForAction(options.action);
  }
  if (options.preferSearchPage) {
    return { context: "search", strict: false };
  }
  return { context: "platform", strict: false };
}

function formatTabHint(tab: chrome.tabs.Tab): string {
  const ctx = detectPageContext(tab.url) ?? "unknown";
  return `#${tab.id} ${ctx} ${tab.url ?? ""}`;
}

function buildContextMismatchError(
  action: string | undefined,
  required: LabPageContext,
  tabs: chrome.tabs.Tab[],
): string {
  const hints = tabs.slice(0, 5).map(formatTabHint).join("; ");
  const actionHint = action ? `（${action}）` : "";
  return (
    `无匹配${contextLabel(required)}的标签${actionHint}。` +
    `请先执行前置步骤（搜索：1→7→9；手动获客：打开主页→点击作品视频，或粘贴单条视频链接打开详情页）。` +
    `当前平台标签：${hints || "无"}`
  );
}

async function pickBestTab(
  tabs: chrome.tabs.Tab[],
  required: LabPageContext,
  strict: boolean,
  action?: string,
): Promise<chrome.tabs.Tab> {
  const session = await readLabSession();
  const sessionTabId = session?.tabId;

  let best: chrome.tabs.Tab | null = null;
  let bestScore = Number.NEGATIVE_INFINITY;

  for (const tab of tabs) {
    const score = scoreTabForContext(tab, required, sessionTabId, session?.platform);
    if (score > bestScore) {
      bestScore = score;
      best = tab;
    }
  }

  if (!best?.id) {
    throw new Error("no platform tab open — run step 1 open_browser first");
  }

  const minScore = strict ? 1_000 : 0;
  if (strict && bestScore < minScore) {
    throw new Error(buildContextMismatchError(action, required, tabs));
  }

  if (strict && !contextMatchesUrl(required, best.url, session?.platform)) {
    throw new Error(buildContextMismatchError(action, required, tabs));
  }

  await focusTab(best);
  await touchLabSession(best.id, best.url);
  return best;
}

/** 根据命令所需页面上下文，选择并聚焦正确的平台标签 */
export async function resolveLabTargetTab(
  options: ResolveLabTabOptions = {},
): Promise<chrome.tabs.Tab> {
  const { context, strict } = resolveRequiredContext(options);
  const tabs = await listPlatformTabs();
  if (tabs.length === 0) {
    throw new Error("no platform tab open — run step 1 open_browser first");
  }
  return pickBestTab(tabs, context, strict, options.action);
}

/** 单入口：按 plugin_lab action 解析目标标签 */
export async function resolveLabTabForAction(action: string): Promise<chrome.tabs.Tab> {
  return resolveLabTargetTab({ action });
}

export { pinLabSession };
