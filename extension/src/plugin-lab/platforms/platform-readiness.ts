import type { PlatformId } from "../../shared/protocol";
import { getCachedSearchApiResultsSync } from "../search-api";
import { collectSearchResultCards, isFeedOverlayOpen, isSearchResultsPage } from "../search-results-dom";
import { getKsSearchApiResults } from "./kuaishou/search-api";
import { collectKsVideoCards, isKsSearchResultsPage } from "./kuaishou/search-dom";
import { getXhsSearchApiResults } from "./xiaohongshu/search-api";
import { collectXhsNoteCards, isXhsSearchResultsPage } from "./xiaohongshu/search-dom";

export function isPlatformSearchResultsPage(platform: PlatformId, url = location.href): boolean {
  switch (platform) {
    case "xiaohongshu":
      return isXhsSearchResultsPage(url);
    case "kuaishou":
      return isKsSearchResultsPage(url);
    default:
      return isSearchResultsPage(url);
  }
}

export async function countPlatformSearchApiItems(platform: PlatformId): Promise<number> {
  switch (platform) {
    case "xiaohongshu":
      return (await getXhsSearchApiResults()).length;
    case "kuaishou":
      return (await getKsSearchApiResults()).length;
    default:
      return getCachedSearchApiResultsSync()?.length ?? 0;
  }
}

export function countPlatformSearchCards(platform: PlatformId): number {
  switch (platform) {
    case "xiaohongshu":
      return collectXhsNoteCards().length;
    case "kuaishou":
      return collectKsVideoCards().length;
    default:
      return collectSearchResultCards().length;
  }
}

export function isPlatformFeedOverlayOpen(platform: PlatformId): boolean {
  if (platform === "douyin") return isFeedOverlayOpen();
  return false;
}
