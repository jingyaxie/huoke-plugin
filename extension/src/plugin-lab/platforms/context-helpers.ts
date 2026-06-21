import type { LabPageContext } from "../lab-context";
import type { PlatformPageContextRules } from "./types";

export function hostMatches(url: string, patterns: readonly RegExp[]): boolean {
  return patterns.some((pattern) => pattern.test(url));
}

export function detectPageContextWithRules(
  url: string | null | undefined,
  rules: PlatformPageContextRules,
  isPlatformUrl: (url?: string | null) => boolean,
): LabPageContext | null {
  if (!url || !isPlatformUrl(url) || !hostMatches(url, rules.hostPatterns)) {
    return null;
  }
  if (rules.profileUrlRe.test(url)) return "profile";
  if (rules.videoUrlRe.test(url)) return "video";
  if (rules.searchUrlRe.test(url)) return "search";
  return "platform";
}

export function isFeedOverlayUrlWithRules(
  url: string | null | undefined,
  rules: PlatformPageContextRules,
): boolean {
  if (!url || !rules.modalIdRe?.test(url)) return false;
  if (rules.videoUrlRe.test(url) && /\/video\/\d{8,22}/i.test(url)) return false;
  return rules.profileUrlRe.test(url) || rules.searchUrlRe.test(url);
}

export function contextMatchesUrlWithRules(
  required: LabPageContext,
  url: string | null | undefined,
  rules: PlatformPageContextRules,
  isPlatformUrl: (url?: string | null) => boolean,
): boolean {
  const detected = detectPageContextWithRules(url, rules, isPlatformUrl);
  if (!detected) return false;
  const feedOverlay = isFeedOverlayUrlWithRules(url, rules);
  if (required === "platform") return true;
  if (required === "search") {
    return detected === "search" || detected === "video" || feedOverlay;
  }
  if (required === "video") {
    return detected === "video" || detected === "search" || feedOverlay;
  }
  if (required === "profile") {
    return detected === "profile" && !feedOverlay;
  }
  return false;
}

export function scoreTabForContextWithRules(
  tab: chrome.tabs.Tab,
  required: LabPageContext,
  rules: PlatformPageContextRules,
  isPlatformUrl: (url?: string | null) => boolean,
  sessionTabId?: number,
): number {
  const url = tab.url ?? "";
  if (!isPlatformUrl(url) || !hostMatches(url, rules.hostPatterns)) return -1;

  let score = 0;
  const detected = detectPageContextWithRules(url, rules, isPlatformUrl);

  if (tab.id !== undefined && tab.id === sessionTabId) {
    if (required === "platform" || contextMatchesUrlWithRules(required, url, rules, isPlatformUrl)) {
      score += 10_000;
    } else {
      score += 300;
    }
  }

  if (required === "platform") {
    score += 100;
  } else if (required === "search") {
    if (detected === "search") score += 5_000;
    else if (detected === "video") score += 3_000;
    else if (detected === "platform") score += 200;
    else score -= 500;
  } else if (required === "video") {
    if (detected === "video") score += 5_000;
    else if (isFeedOverlayUrlWithRules(url, rules)) score += 4_500;
    else if (detected === "search") score += 2_000;
    else score -= 500;
  } else if (required === "profile") {
    if (detected === "profile" && !isFeedOverlayUrlWithRules(url, rules)) score += 5_000;
    else if (detected === "profile") score += 500;
    else score -= 500;
  }

  score += (tab.lastAccessed ?? 0) / 1_000_000_000;
  return score;
}
