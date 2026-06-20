export type XhsPageKind = "search" | "note" | "other";

export function buildSearchUrl(keyword: string): string {
  const q = encodeURIComponent(keyword.trim());
  return `https://www.xiaohongshu.com/search_result?keyword=${q}&source=web_search_result_notes`;
}

export function buildNoteUrl(noteId: string): string {
  return `https://www.xiaohongshu.com/explore/${noteId}`;
}

export function detectPageKind(url: string): XhsPageKind {
  if (/search_result/i.test(url)) return "search";
  if (/\/explore\//i.test(url) || /\/discovery\/item\//i.test(url) || /\/note\//i.test(url)) {
    return "note";
  }
  return "other";
}

export { sleep } from "../douyin/search";
