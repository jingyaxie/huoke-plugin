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
  hostPatterns: [/\.xiaohongshu\.com$/i, /^https:\/\/www\.xiaohongshu\.com/i],
  searchUrlRe: /search_result|\/search\//i,
  videoUrlRe: /\/explore\/|\/discovery\/item\/|\/note\//i,
  profileUrlRe: /\/user\/profile\//i,
} as const;

/** 小红书插件实验室适配器 */
export const xiaohongshuPluginLabAdapter: PluginLabPlatformAdapter = {
  id: "xiaohongshu" as PlatformId,
  label: "小红书",
  capabilities: {
    collect: true,
    outreach: false,
    intents: ["keyword_auto", "single_video", "account_home"],
  },
  pageContext: PAGE_CONTEXT,
  networkHookPatterns: ["/api/sns/web/", "edith.xiaohongshu.com"],

  detectPageContext(url: string): LabPageContext | null {
    return detectPageContextWithRules(url, PAGE_CONTEXT, isPlatformUrl);
  },

  isFeedOverlayUrl(_url?: string | null): boolean {
    return false;
  },

  contextMatchesUrl(required: LabPageContext, url?: string | null): boolean {
    return contextMatchesUrlWithRules(required, url, PAGE_CONTEXT, isPlatformUrl);
  },

  scoreTabForContext(tab: chrome.tabs.Tab, required: LabPageContext, sessionTabId?: number): number {
    return scoreTabForContextWithRules(tab, required, PAGE_CONTEXT, isPlatformUrl, sessionTabId);
  },
};
