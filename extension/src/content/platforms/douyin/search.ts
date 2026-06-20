export type DouyinPageKind = "search" | "video" | "profile" | "other";

export function buildSearchUrl(keyword: string): string {
  const q = encodeURIComponent(keyword.trim());
  return `https://www.douyin.com/search/${q}?type=video`;
}

export function buildVideoUrl(awemeId: string): string {
  return `https://www.douyin.com/video/${awemeId}`;
}

export function detectPageKind(url: string): DouyinPageKind {
  if (/\/search\//i.test(url)) return "search";
  if (/\/video\/\d+/i.test(url) || /modal_id=\d+/i.test(url)) return "video";
  if (/\/user\//i.test(url)) return "profile";
  return "other";
}

export function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
