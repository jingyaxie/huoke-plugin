import { hostMatches, type PlatformAdapter } from "../types";
import { detectPageKind } from "./search";

const HOST_PATTERNS = [/\.douyin\.com$/i, /^https:\/\/www\.douyin\.com/i];

let hookEnabled = false;
let hookPatterns: string[] = [];

export const douyinAdapter: PlatformAdapter = {
  id: "douyin",
  hostPatterns: HOST_PATTERNS,

  matches(url: string) {
    return hostMatches(url, HOST_PATTERNS);
  },

  getPageInfo(url: string, title: string) {
    return {
      url,
      title,
      platform: "douyin" as const,
      pageKind: detectPageKind(url),
    };
  },

  async handleCommand(action: string, payload: unknown) {
    switch (action) {
      case "platform.detect":
        return {
          platform: "douyin",
          url: location.href,
          pageKind: detectPageKind(location.href),
        };
      case "get_page_info":
        return this.getPageInfo(location.href, document.title);
      case "douyin.page.detect":
        return {
          platform: "douyin",
          pageKind: detectPageKind(location.href),
          url: location.href,
        };
      case "network.hook.enable": {
        hookEnabled = true;
        hookPatterns = (payload as { patterns?: string[] })?.patterns ?? [];
        window.postMessage(
          {
            channel: "huoke:injected:config",
            enabled: true,
            patterns: hookPatterns,
          },
          "*",
        );
        return { enabled: true, patterns: hookPatterns };
      }
      case "network.hook.disable":
        hookEnabled = false;
        hookPatterns = [];
        window.postMessage({ channel: "huoke:injected:config", enabled: false, patterns: [] }, "*");
        return { enabled: false };
      case "network.hook.status":
        return { enabled: hookEnabled, patterns: hookPatterns };
      default:
        throw new Error(
          `douyin adapter: unknown action ${action} — UI 自动化请使用 plugin_lab.*（插件实验室步骤）`,
        );
    }
  },
};

export function isDouyinHookEnabled() {
  return hookEnabled;
}
