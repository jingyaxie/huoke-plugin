/**
 * 按 platform 路由 Service Worker 层命令，各平台实现互不引用
 */
import { detectPlatformFromUrl } from "../platform-hosts";
import { resolveLabTabForAction } from "../resolve-lab-tab";
import { normalizePlatformId } from "./registry";
import * as douyinBackground from "./douyin/background";
import * as xiaohongshuBackground from "./xiaohongshu/background";
import * as kuaishouBackground from "./kuaishou/background";

type LabPlatform = "douyin" | "xiaohongshu" | "kuaishou";

interface PlatformBackgroundModule {
  clickSearchVideoBackground(payload: Record<string, unknown>): Promise<unknown>;
  prepareSearchForVideoBackground(payload: Record<string, unknown>): Promise<unknown>;
  closeVideoDetailBackground(payload: Record<string, unknown>): Promise<unknown>;
}

const BACKGROUND_BY_PLATFORM: Record<LabPlatform, PlatformBackgroundModule> = {
  douyin: douyinBackground,
  xiaohongshu: xiaohongshuBackground,
  kuaishou: kuaishouBackground,
};

function resolvePlatform(payload: Record<string, unknown>, tabUrl?: string | null): LabPlatform {
  const hint = String(payload.platform ?? "").trim();
  if (hint) {
    const fromHint = normalizePlatformId(hint);
    if (fromHint !== "unknown") return fromHint as LabPlatform;
  }
  const fromUrl = normalizePlatformId(detectPlatformFromUrl(tabUrl ?? String(payload.url ?? "")) ?? "douyin");
  return fromUrl === "unknown" ? "douyin" : (fromUrl as LabPlatform);
}

function getBackground(platform: LabPlatform): PlatformBackgroundModule {
  return BACKGROUND_BY_PLATFORM[platform];
}

async function routeByLabTab(
  labAction: string,
  payload: Record<string, unknown>,
  run: (mod: PlatformBackgroundModule, enriched: Record<string, unknown>) => Promise<unknown>,
) {
  const hint = String(payload.platform ?? "").trim();
  const tab = await resolveLabTabForAction(labAction, hint || undefined);
  const platform = resolvePlatform({ ...payload, url: tab.url }, tab.url);
  return run(getBackground(platform), { ...payload, platform });
}

export async function clickSearchVideoBackground(payload: Record<string, unknown> = {}) {
  return routeByLabTab("plugin_lab.click_search_video", payload, (mod, enriched) =>
    mod.clickSearchVideoBackground(enriched),
  );
}

export async function prepareSearchForVideoBackground(payload: Record<string, unknown> = {}) {
  return routeByLabTab("plugin_lab.prepare_search_video", payload, (mod, enriched) =>
    mod.prepareSearchForVideoBackground(enriched),
  );
}

export async function closeVideoDetailBackground(payload: Record<string, unknown> = {}) {
  return routeByLabTab("plugin_lab.close_video_detail", payload, (mod, enriched) =>
    mod.closeVideoDetailBackground(enriched),
  );
}
