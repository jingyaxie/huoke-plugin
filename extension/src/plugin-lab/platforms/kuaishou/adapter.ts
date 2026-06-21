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
  hostPatterns: [/\.kuaishou\.com$/i, /^https:\/\/www\.kuaishou\.com/i],
  searchUrlRe: /\/search\/|search\.kuaishou\.com/i,
  videoUrlRe: /\/short-video\/|\/fw\/photo\//i,
  profileUrlRe: /\/profile\//i,
} as const;

/** 快手插件实验室适配器 */
export const kuaishouPluginLabAdapter: PluginLabPlatformAdapter = {
  id: "kuaishou" as PlatformId,
  label: "快手",
  capabilities: {
    collect: true,
    outreach: false,
    intents: ["keyword_auto", "single_video", "account_home"],
  },
  pageContext: PAGE_CONTEXT,
  networkHookPatterns: ["/graphql", "/rest/", "captcha"],

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
