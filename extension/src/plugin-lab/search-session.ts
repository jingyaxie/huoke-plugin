import { detectPlatformFromUrl } from "./platform-hosts";
import { rememberLabSearchUrl, readLabSearchUrl } from "./lab-context";
import { isSearchResultsPage as isDouyinSearchPage } from "./search-results-dom";
import { isXhsSearchResultsPage } from "./platforms/xiaohongshu/search-dom";
import { isKsSearchResultsPage } from "./platforms/kuaishou/search-dom";
import { randDelay, sleep } from "./search-input";

export function isPlatformSearchResultsPage(url = location.href, platform?: string): boolean {
  const p = platform ?? detectPlatformFromUrl(url) ?? "douyin";
  if (p === "xiaohongshu") return isXhsSearchResultsPage(url);
  if (p === "kuaishou") return isKsSearchResultsPage(url);
  return isDouyinSearchPage(url);
}

/** 进入/停留在搜索结果页时调用，双写 sessionStorage + 扩展 lab session */
export async function rememberPlatformSearchUrl(url = location.href, platform?: string): Promise<void> {
  const p = platform ?? detectPlatformFromUrl(url) ?? "douyin";
  if (!isPlatformSearchResultsPage(url, p)) return;
  const clean = url.split("#")[0];
  await rememberLabSearchUrl(p, clean);
}

export async function readPlatformSearchUrl(platform?: string): Promise<string> {
  const p = platform ?? detectPlatformFromUrl(location.href) ?? "douyin";
  const fromSession = await readLabSearchUrl(p);
  if (fromSession && isPlatformSearchResultsPage(fromSession, p)) return fromSession;
  return "";
}

/** 关闭详情/浮层后回到搜索结果列表 */
export async function restorePlatformSearchList(platform?: string): Promise<{
  ok: boolean;
  restored: boolean;
  url: string;
  message: string;
}> {
  const p = platform ?? detectPlatformFromUrl(location.href) ?? "douyin";
  if (isPlatformSearchResultsPage(location.href, p)) {
    await rememberPlatformSearchUrl(location.href, p);
    return {
      ok: true,
      restored: false,
      url: location.href,
      message: "已在搜索结果页",
    };
  }

  const stored = await readPlatformSearchUrl(p);

  window.history.back();
  await sleep(randDelay(600, 900));
  if (isPlatformSearchResultsPage(location.href, p)) {
    await rememberPlatformSearchUrl(location.href, p);
    return {
      ok: true,
      restored: true,
      url: location.href,
      message: "已通过 history.back 回到搜索结果页",
    };
  }

  if (stored) {
    location.assign(stored);
    await sleep(randDelay(700, 1100));
    if (isPlatformSearchResultsPage(location.href, p)) {
      await rememberPlatformSearchUrl(location.href, p);
      return {
        ok: true,
        restored: true,
        url: location.href,
        message: "已从 lab session 恢复搜索结果页",
      };
    }
  }

  return {
    ok: false,
    restored: false,
    url: location.href,
    message: "无法恢复搜索结果页，请重新执行搜索",
  };
}
