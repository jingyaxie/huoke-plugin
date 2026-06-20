import type { PageInfo, PlatformId } from "../../shared/protocol";
import type { PlatformAdapter } from "./types";
import { douyinAdapter } from "./douyin";
import { xiaohongshuAdapter } from "./xiaohongshu";
import { kuaishouAdapter } from "./kuaishou";

const adapters: PlatformAdapter[] = [douyinAdapter, xiaohongshuAdapter, kuaishouAdapter];

export function resolveAdapter(url: string): PlatformAdapter | null {
  for (const adapter of adapters) {
    if (adapter.matches(url)) {
      return adapter;
    }
  }
  return null;
}

export function detectPlatform(url: string): PlatformId {
  return resolveAdapter(url)?.id ?? "unknown";
}

export async function dispatchCommand(
  action: string,
  payload: unknown,
  url: string,
): Promise<unknown> {
  const adapter = resolveAdapter(url);
  if (!adapter) {
    throw new Error(`unsupported platform for url: ${url}`);
  }
  return adapter.handleCommand(action, payload);
}

export function getPageInfo(url: string, title: string): PageInfo {
  const platform = detectPlatform(url);
  const adapter = resolveAdapter(url);
  if (adapter) {
    return adapter.getPageInfo(url, title);
  }
  return { url, title, platform };
}

export function listAdapters() {
  return adapters.map((item) => ({ id: item.id, hostPatterns: item.hostPatterns }));
}
