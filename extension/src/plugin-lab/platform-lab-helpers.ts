import {
  detectPlatformFromUrl,
  DM_UNSUPPORTED_PLATFORMS,
  FILTER_UNSUPPORTED_PLATFORMS,
  isDmSupportedPlatform,
  isFilterSupportedPlatform,
} from "./platform-hosts";
import { pollSearchApiCache } from "./search-api";
import { waitForKsSearchApiResults } from "./platforms/kuaishou/search-api";
import { waitForXhsSearchApiResults } from "./platforms/xiaohongshu/search-api";
import type { PlatformSearchItem } from "./platforms/shared/content-item";

export async function pollPlatformSearchCache(
  tabUrl: string | undefined,
  timeoutMs = 15_000,
  minItems = 1,
): Promise<{ items: PlatformSearchItem[]; captureMethod: "api" | "none" }> {
  const platform = detectPlatformFromUrl(tabUrl);
  if (platform === "xiaohongshu") {
    const items = await waitForXhsSearchApiResults(timeoutMs, minItems);
    return { items, captureMethod: items.length > 0 ? "api" : "none" };
  }
  if (platform === "kuaishou") {
    const items = await waitForKsSearchApiResults(timeoutMs, minItems);
    return { items, captureMethod: items.length > 0 ? "api" : "none" };
  }
  const cache = await pollSearchApiCache({ timeoutMs, minItems });
  const items = (cache?.items ?? []) as PlatformSearchItem[];
  return { items, captureMethod: items.length > 0 ? "api" : "none" };
}

export function isNonDouyinDetailPlatform(tabUrl: string | undefined): boolean {
  const platform = detectPlatformFromUrl(tabUrl);
  return platform === "xiaohongshu" || platform === "kuaishou";
}

export function dmUnsupportedMessage(platform: string | null | undefined): string {
  if (platform === "xiaohongshu") return "小红书不支持插件私信";
  if (platform === "kuaishou") return "快手不支持插件私信";
  return "当前平台不支持插件私信";
}

export function filterSkippedMessage(platform: string | null | undefined): string {
  if (platform === "xiaohongshu") return "小红书暂无筛选步骤，已跳过";
  if (platform === "kuaishou") return "快手暂无筛选步骤，已跳过";
  return "当前平台不支持筛选";
}

export {
  DM_UNSUPPORTED_PLATFORMS,
  FILTER_UNSUPPORTED_PLATFORMS,
  isDmSupportedPlatform,
  isFilterSupportedPlatform,
};
