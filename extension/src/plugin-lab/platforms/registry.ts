import type { PlatformId } from "../../shared/protocol";
import type { LabPageContext } from "../lab-context";
import { douyinPluginLabAdapter } from "./douyin/adapter";
import { kuaishouPluginLabAdapter } from "./kuaishou/adapter";
import type { PlatformCollectCapabilities, PluginLabPlatformAdapter } from "./types";
import { xiaohongshuPluginLabAdapter } from "./xiaohongshu/adapter";

const ADAPTERS: PluginLabPlatformAdapter[] = [
  douyinPluginLabAdapter,
  xiaohongshuPluginLabAdapter,
  kuaishouPluginLabAdapter,
];

const ADAPTER_BY_ID = new Map<PlatformId, PluginLabPlatformAdapter>(
  ADAPTERS.map((adapter) => [adapter.id, adapter]),
);

export function normalizePlatformId(raw?: string | null): PlatformId {
  const value = String(raw ?? "douyin").trim().toLowerCase();
  if (value === "xhs" || value === "xiaohongshu" || value === "redbook") return "xiaohongshu";
  if (value === "kuaishou" || value === "ks") return "kuaishou";
  if (value === "douyin" || value === "dy") return "douyin";
  return "douyin";
}

export const PLATFORM_TAB_QUERY_PATTERNS: Record<Exclude<PlatformId, "unknown">, string[]> = {
  douyin: ["https://www.douyin.com/*", "https://*.douyin.com/*"],
  xiaohongshu: ["https://www.xiaohongshu.com/*", "https://*.xiaohongshu.com/*"],
  kuaishou: ["https://www.kuaishou.com/*", "https://*.kuaishou.com/*"],
};

export function tabQueryPatternsForPlatform(platform?: string | null): string[] {
  const id = normalizePlatformId(platform);
  if (id === "unknown") return PLATFORM_TAB_QUERY_PATTERNS.douyin;
  return PLATFORM_TAB_QUERY_PATTERNS[id];
}

export function getPluginLabAdapter(platform?: string | null): PluginLabPlatformAdapter {
  const id = normalizePlatformId(platform);
  return ADAPTER_BY_ID.get(id) ?? douyinPluginLabAdapter;
}

export function getPluginLabAdapterForUrl(url?: string | null): PluginLabPlatformAdapter {
  if (!url) return douyinPluginLabAdapter;
  for (const adapter of ADAPTERS) {
    if (adapter.pageContext.hostPatterns.some((pattern) => pattern.test(url))) {
      return adapter;
    }
  }
  return douyinPluginLabAdapter;
}

export function listPluginLabCapabilities(): Array<{
  id: PlatformId;
  label: string;
  capabilities: PlatformCollectCapabilities;
  network_hook_patterns: string[];
}> {
  return ADAPTERS.map((adapter) => ({
    id: adapter.id,
    label: adapter.label,
    capabilities: adapter.capabilities,
    network_hook_patterns: adapter.networkHookPatterns,
  }));
}

export function detectPageContextForPlatform(
  url: string | null | undefined,
  platform?: string | null,
): LabPageContext | null {
  return getPluginLabAdapter(platform).detectPageContext(url ?? "");
}

export function assertCollectSupported(platform?: string | null): void {
  const adapter = getPluginLabAdapter(platform);
  if (!adapter.capabilities.collect) {
    throw new Error(
      `${adapter.label}（${adapter.id}）插件采集尚未实现，请先在 platforms/${adapter.id}/ 下完成适配`,
    );
  }
}

export { ADAPTERS };
