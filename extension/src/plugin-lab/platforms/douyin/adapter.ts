import type { PlatformId } from "../../../shared/protocol";
import type { LabPageContext } from "../../lab-context";
import { isPlatformUrl } from "../../platform-hosts";
import {
  contextMatchesUrlWithRules,
  detectPageContextWithRules,
  isFeedOverlayUrlWithRules,
  scoreTabForContextWithRules,
} from "../context-helpers";
import type { PluginLabPlatformAdapter } from "../types";

const PAGE_CONTEXT = {
  hostPatterns: [/\.douyin\.com$/i, /^https:\/\/www\.douyin\.com/i],
  searchUrlRe: /\/search\/|\/jingxuan\/search\/|\/root\/search\//i,
  videoUrlRe: /\/video\/\d+|modal_id=\d+/i,
  profileUrlRe: /\/user\//i,
  modalIdRe: /modal_id=\d{8,22}/i,
} as const;

export const douyinPluginLabAdapter: PluginLabPlatformAdapter = {
  id: "douyin" as PlatformId,
  label: "抖音",
  capabilities: {
    collect: true,
    outreach: true,
    intents: ["keyword_auto", "single_video", "account_home"],
  },
  pageContext: PAGE_CONTEXT,
  networkHookPatterns: ["/aweme/", "/comment/", "/search/"],

  detectPageContext(url: string): LabPageContext | null {
    return detectPageContextWithRules(url, PAGE_CONTEXT, isPlatformUrl);
  },

  isFeedOverlayUrl(url?: string | null): boolean {
    return isFeedOverlayUrlWithRules(url, PAGE_CONTEXT);
  },

  contextMatchesUrl(required: LabPageContext, url?: string | null): boolean {
    return contextMatchesUrlWithRules(required, url, PAGE_CONTEXT, isPlatformUrl);
  },

  scoreTabForContext(tab: chrome.tabs.Tab, required: LabPageContext, sessionTabId?: number): number {
    return scoreTabForContextWithRules(tab, required, PAGE_CONTEXT, isPlatformUrl, sessionTabId);
  },
};
