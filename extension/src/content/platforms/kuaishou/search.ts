export type KuaishouPageKind = "search" | "video" | "other";

export function buildSearchUrl(keyword: string): string {
  const q = encodeURIComponent(keyword.trim());
  return `https://www.kuaishou.com/search/video?searchKey=${q}`;
}

export function buildVideoUrl(photoId: string): string {
  return `https://www.kuaishou.com/short-video/${photoId}`;
}

export function detectPageKind(url: string): KuaishouPageKind {
  if (/\/search\//i.test(url)) return "search";
  if (/\/short-video\//i.test(url) || /\/video\//i.test(url)) return "video";
  return "other";
}

export { sleep } from "../douyin/search";
