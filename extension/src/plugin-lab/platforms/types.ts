import type { PlatformId } from "../../shared/protocol";
import type { LabPageContext } from "../lab-context";

/** 插件实验室单平台能力声明（与 local-service /api/collect/capabilities 对齐） */
export interface PlatformCollectCapabilities {
  collect: boolean;
  outreach: boolean;
  intents: Array<"keyword_auto" | "single_video" | "account_home">;
}

/** 各平台 URL → 页面上下文（search / video / profile）判定规则 */
export interface PlatformPageContextRules {
  hostPatterns: readonly RegExp[];
  searchUrlRe: RegExp;
  videoUrlRe: RegExp;
  profileUrlRe: RegExp;
  modalIdRe?: RegExp;
}

/**
 * 插件实验室平台适配器：各平台独立实现，通过 registry 切换。
 * DOM/步骤实现可放在 platforms/{id}/ 下，互不 import 对方文件。
 */
export interface PluginLabPlatformAdapter {
  readonly id: PlatformId;
  readonly label: string;
  readonly capabilities: PlatformCollectCapabilities;
  readonly pageContext: PlatformPageContextRules;
  readonly networkHookPatterns: string[];

  detectPageContext(url: string): LabPageContext | null;
  isFeedOverlayUrl(url?: string | null): boolean;
  contextMatchesUrl(required: LabPageContext, url?: string | null): boolean;
  scoreTabForContext(
    tab: chrome.tabs.Tab,
    required: LabPageContext,
    sessionTabId?: number,
  ): number;
}
