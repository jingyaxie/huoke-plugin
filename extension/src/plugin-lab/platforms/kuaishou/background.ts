/**
 * 快手 Service Worker — URL 搜索 + DOM / URL 打开短视频详情
 */
import { buildSearchUrl } from "../../../content/platforms/kuaishou/search";
import { readLabSearchUrl, rememberLabSearchUrl } from "../../lab-context";
import { resolveLabTabForAction } from "../../resolve-lab-tab";
import { sendContentPluginLabCommand } from "../../tab-command";
import { sleep, waitForTabLoad } from "../shared/tab-load";

const PLATFORM = "kuaishou";

interface ClickResult {
  ok?: boolean;
  feed_open?: boolean;
  is_search_feed?: boolean;
  is_content_detail?: boolean;
  mode?: string;
  video_index?: number;
  aweme_id?: string;
  url?: string;
  message?: string;
}

async function probeVideo(tabId: number, payload: Record<string, unknown>) {
  return (await sendContentPluginLabCommand(
    tabId,
    "plugin_lab.search_video_probe",
    { ...payload, platform: PLATFORM },
    { skipPreflight: true },
  )) as { ok?: boolean; aweme_id?: string; url?: string };
}

async function domOpenDetail(tabId: number, payload: Record<string, unknown>): Promise<ClickResult> {
  return (await sendContentPluginLabCommand(
    tabId,
    "plugin_lab.search_video_dom_click",
    { ...payload, platform: PLATFORM },
    { skipPreflight: true },
  )) as ClickResult;
}

function isKsSearchUrl(url?: string | null): boolean {
  if (!url) return false;
  return /\/search\/|searchKey=/i.test(url);
}

export async function clickSearchVideoBackground(payload: Record<string, unknown> = {}) {
  const tab = await resolveLabTabForAction("plugin_lab.click_search_video", PLATFORM);
  if (!tab.id) throw new Error("target tab has no id");
  const tabId = tab.id;
  const videoIndex = Math.max(1, Number(payload.video_index ?? payload.index ?? 1));

  await sendContentPluginLabCommand(
    tabId,
    "plugin_lab.prepare_search_video",
    { skip_restore: true, platform: PLATFORM },
    { skipPreflight: true },
  );

  let domResult = await domOpenDetail(tabId, { ...payload, video_index: videoIndex });

  if (!domResult.ok) {
    const apiResult = (await sendContentPluginLabCommand(
      tabId,
      "plugin_lab.fetch_search_results",
      { limit: 20, platform: PLATFORM },
      { skipPreflight: true },
    )) as { items?: Array<{ url?: string; aweme_id?: string }> };
    const item = apiResult.items?.[videoIndex - 1];
    const targetUrl = String(item?.url ?? "").trim();
    if (targetUrl) {
      await chrome.tabs.update(tabId, { url: targetUrl });
      await waitForTabLoad(tabId, 12_000);
      await sleep(900);
      const probe = await probeVideo(tabId, { video_index: videoIndex });
      domResult = {
        ok: Boolean(probe.ok) || /\/short-video\/|\/fw\/photo\//i.test(targetUrl),
        aweme_id: item?.aweme_id ?? probe.aweme_id,
        url: targetUrl,
        message: `已通过 URL 打开第 ${videoIndex} 条视频`,
      };
    }
  }

  return {
    ok: Boolean(domResult.ok),
    feed_open: Boolean(domResult.ok),
    is_search_feed: false,
    is_content_detail: Boolean(domResult.ok),
    mode: domResult.ok && domResult.url ? "url_navigate" : "dom_detail",
    video_index: videoIndex,
    aweme_id: String(domResult.aweme_id ?? payload.aweme_id ?? "").trim() || undefined,
    url: domResult.url ?? tab.url,
    message:
      domResult.message
      ?? (domResult.ok ? `已打开第 ${videoIndex} 条内容详情` : "未能打开内容详情"),
  };
}

export async function prepareSearchForVideoBackground(payload: Record<string, unknown> = {}) {
  const tab = await resolveLabTabForAction("plugin_lab.prepare_search_video", PLATFORM);
  if (!tab.id) throw new Error("lab tab has no id");
  const tabId = tab.id;

  try {
    await sendContentPluginLabCommand(
      tabId,
      "plugin_lab.close_video_detail",
      { ...payload, platform: PLATFORM },
      { skipPreflight: true },
    );
  } catch {
    // already closed
  }
  await sleep(400);

  const current = await chrome.tabs.get(tabId);
  const onSearchPage = isKsSearchUrl(current.url);
  if (onSearchPage && current.url) {
    await rememberLabSearchUrl(PLATFORM, current.url);
  }

  let storedSearch = await readLabSearchUrl(PLATFORM);
  if (!storedSearch) {
    const keyword = String(payload.search_key ?? payload.keyword ?? "").trim();
    if (keyword) {
      storedSearch = buildSearchUrl(keyword);
    }
  }

  if (!onSearchPage && storedSearch) {
    await chrome.tabs.update(tabId, { url: storedSearch });
    await waitForTabLoad(tabId, 12_000);
    await sleep(800);
  }

  return sendContentPluginLabCommand(
    tabId,
    "plugin_lab.prepare_search_video",
    { ...payload, skip_restore: true, platform: PLATFORM },
    { skipPreflight: true },
  );
}

export async function closeVideoDetailBackground(payload: Record<string, unknown> = {}) {
  const tab = await resolveLabTabForAction("plugin_lab.close_video_detail", PLATFORM);
  if (!tab.id) throw new Error("lab tab has no id");
  return sendContentPluginLabCommand(
    tab.id,
    "plugin_lab.close_video_detail",
    { ...payload, platform: PLATFORM },
    { skipPreflight: true },
  );
}
