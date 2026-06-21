export const PLATFORM_HOSTS = [
  "douyin.com",
  "xiaohongshu.com",
  "kuaishou.com",
] as const;

export function isPlatformUrl(url?: string | null): boolean {
  if (!url) return false;
  try {
    const host = new URL(url).hostname.toLowerCase();
    return PLATFORM_HOSTS.some((item) => host === item || host.endsWith(`.${item}`));
  } catch {
    return PLATFORM_HOSTS.some((item) => url.includes(item));
  }
}

export function detectPlatformFromUrl(url?: string | null): string | null {
  if (!url) return null;
  try {
    const host = new URL(url).hostname.toLowerCase();
    if (host.includes("douyin.com")) return "douyin";
    if (host.includes("xiaohongshu.com")) return "xiaohongshu";
    if (host.includes("kuaishou.com")) return "kuaishou";
  } catch {
    if (/douyin\.com/i.test(url)) return "douyin";
    if (/xiaohongshu\.com/i.test(url)) return "xiaohongshu";
    if (/kuaishou\.com/i.test(url)) return "kuaishou";
  }
  return null;
}

/** 小红书、快手不支持插件私信（火山/快手同属无私信能力） */
export const DM_UNSUPPORTED_PLATFORMS = new Set(["xiaohongshu", "kuaishou"]);

export function isDmSupportedPlatform(platform: string | null | undefined): boolean {
  if (!platform) return false;
  return !DM_UNSUPPORTED_PLATFORMS.has(platform);
}

/** 筛选步骤仅抖音可用 */
export const FILTER_UNSUPPORTED_PLATFORMS = new Set(["xiaohongshu", "kuaishou"]);

export function isFilterSupportedPlatform(platform: string | null | undefined): boolean {
  if (!platform) return false;
  return !FILTER_UNSUPPORTED_PLATFORMS.has(platform);
}
