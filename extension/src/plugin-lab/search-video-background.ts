import { humanPace } from "./search-input";
import { readLabSearchUrl, rememberLabSearchUrl } from "./lab-context";
import { resolveLabTabForAction } from "./resolve-lab-tab";
import { detectPlatformFromUrl } from "./platform-hosts";
import { normalizePlatformId } from "./platforms/registry";
import {
  openVideoInDetailWindow,
  resolveSearchVideoUrl,
} from "./detail-window";
import { isNonDouyinDetailPlatform } from "./platform-lab-helpers";
import {
  attachDebugger,
  clickMouse,
  detachDebugger,
  moveMouse,
} from "./real-mouse";
import { sendContentPluginLabCommand } from "./tab-command";

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitForTabLoad(tabId: number, timeoutMs = 8_000): Promise<void> {
  try {
    const tab = await chrome.tabs.get(tabId);
    if (tab.status === "complete") return;
  } catch {
    return;
  }

  await new Promise<void>((resolve) => {
    const timer = setTimeout(() => {
      chrome.tabs.onUpdated.removeListener(listener);
      resolve();
    }, timeoutMs);

    function listener(updatedId: number, info: chrome.tabs.TabChangeInfo) {
      if (updatedId !== tabId || info.status !== "complete") return;
      clearTimeout(timer);
      chrome.tabs.onUpdated.removeListener(listener);
      resolve();
    }

    chrome.tabs.onUpdated.addListener(listener);
  });
}

interface VideoProbe {
  ok?: boolean;
  center?: { x: number; y: number };
  video_index?: number;
  available?: number;
  feed_open?: boolean;
  is_search_feed?: boolean;
  is_standalone_video?: boolean;
  aweme_id?: string;
  url?: string;
  message?: string;
  click_by?: string;
}

interface ClickResult {
  ok?: boolean;
  feed_open?: boolean;
  is_search_feed?: boolean;
  mode?: string;
  video_index?: number;
  available?: number;
  url?: string;
  message?: string;
  attempt?: number;
  aweme_id?: string;
}

async function probeVideo(
  tabId: number,
  payload: Record<string, unknown>,
): Promise<VideoProbe> {
  return (await sendContentPluginLabCommand(
    tabId,
    "plugin_lab.search_video_probe",
    payload,
    { skipPreflight: true },
  )) as VideoProbe;
}

async function prepareSearchPage(tabId: number): Promise<{ ok?: boolean; card_count?: number; message?: string }> {
  return (await sendContentPluginLabCommand(
    tabId,
    "plugin_lab.prepare_search_video",
    {},
    { skipPreflight: true },
  )) as { ok?: boolean; card_count?: number; message?: string };
}

async function domOpenFeed(
  tabId: number,
  payload: Record<string, unknown>,
): Promise<ClickResult> {
  return (await sendContentPluginLabCommand(
    tabId,
    "plugin_lab.search_video_dom_click",
    payload,
    { skipPreflight: true },
  )) as ClickResult;
}

async function waitSearchFeedOpen(tabId: number, videoIndex: number, maxPolls = 36): Promise<boolean> {
  for (let i = 0; i < maxPolls; i += 1) {
    await sleep(220 + i * 45);
    const status = await probeVideo(tabId, { video_index: videoIndex, status_only: true });
    if (status.is_search_feed) return true;
    if (status.is_standalone_video) return false;
  }
  const status = await probeVideo(tabId, { video_index: videoIndex, status_only: true });
  return Boolean(status.is_search_feed);
}

async function cdpClickAt(tabId: number, x: number, y: number): Promise<void> {
  await attachDebugger(tabId);
  try {
    await moveMouse(tabId, x, y);
    await sleep(humanPace.mouseHover());
    await clickMouse(tabId, x, y);
    await sleep(humanPace.posterClick());
  } finally {
    await detachDebugger(tabId);
  }
}

function searchFeedSuccess(result: ClickResult): boolean {
  return Boolean(result.ok && result.is_search_feed);
}

/** 步骤 9：优先在独立窗口打开视频，列表页保持不变 */
export async function clickSearchVideoBackground(payload: Record<string, unknown> = {}) {
  const platformHint = String(payload.platform ?? "").trim();
  const tab = await resolveLabTabForAction(
    "plugin_lab.click_search_video",
    platformHint || undefined,
  );
  if (!tab.id) throw new Error("target tab has no id");
  const tabId = tab.id;
  const videoIndex = Math.max(1, Number(payload.video_index ?? payload.index ?? 1));
  const useDetailWindow = payload.use_detail_window !== false;

  if (useDetailWindow) {
    const resolved = await resolveSearchVideoUrl(tabId, videoIndex, payload);
    if (resolved.url) {
      const platform = normalizePlatformId(
        platformHint || detectPlatformFromUrl(tab.url) || "douyin",
      );
      return openVideoInDetailWindow({
        platform,
        url: resolved.url,
        listTabId: tabId,
        aweme_id: resolved.aweme_id,
        video_index: videoIndex,
      });
    }
  }

  if (isNonDouyinDetailPlatform(tab.url)) {
    await prepareSearchPage(tabId);
    let domResult = await domOpenFeed(tabId, {
      ...payload,
      video_index: videoIndex,
    });

    if (!domResult.ok) {
      const apiResult = (await sendContentPluginLabCommand(
        tabId,
        "plugin_lab.fetch_search_results",
        { limit: 20 },
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
      aweme_id: domResult.aweme_id ?? payload.aweme_id,
      url: domResult.url ?? tab.url,
      message:
        domResult.message
        ?? (domResult.ok ? `已打开第 ${videoIndex} 条内容详情` : "未能打开内容详情"),
    };
  }

  let lastMessage = "未打开搜索 Feed 浮层";
  let lastUrl = tab.url ?? "";
  let awemeHint = String(payload.aweme_id ?? payload.aweme_hint ?? "").trim();

  for (let attempt = 1; attempt <= 4; attempt += 1) {
    const prep = await prepareSearchPage(tabId);
    if (!prep.ok) {
      lastMessage = prep.message ?? "搜索列表未就绪";
      await sleep(800 + attempt * 350);
      continue;
    }

    const probeAweme = await probeVideo(tabId, { ...payload, video_index: videoIndex, aweme_id: awemeHint });
    if (!awemeHint && probeAweme.aweme_id) awemeHint = probeAweme.aweme_id;

    if (probeAweme.is_search_feed) {
      return {
        ok: true,
        feed_open: true,
        is_search_feed: true,
        mode: "already_open",
        video_index: videoIndex,
        aweme_id: awemeHint || probeAweme.aweme_id,
        url: probeAweme.url ?? lastUrl,
        attempt,
        message: "搜索 Feed 浮层已打开",
      };
    }

    if (awemeHint) {
      const modalResult = await domOpenFeed(tabId, {
        ...payload,
        video_index: videoIndex,
        aweme_id: awemeHint,
        strategy: "modal_only",
      });
      lastUrl = modalResult.url ?? lastUrl;
      if (searchFeedSuccess(modalResult)) {
        return { ...modalResult, attempt, aweme_id: awemeHint };
      }
      lastMessage = modalResult.message ?? lastMessage;
    }

    if (probeAweme.is_standalone_video && awemeHint) {
      const recovered = await domOpenFeed(tabId, {
        ...payload,
        video_index: videoIndex,
        aweme_id: awemeHint,
        strategy: "modal_only",
      });
      if (searchFeedSuccess(recovered)) {
        return { ...recovered, attempt, mode: "modal_recover", aweme_id: awemeHint };
      }
      lastMessage = recovered.message ?? "误入独立详情页且 modal 恢复失败";
      continue;
    }

    const probe = await probeVideo(tabId, { ...payload, video_index: videoIndex, aweme_id: awemeHint });
    lastUrl = probe.url ?? lastUrl;
    if (!awemeHint && probe.aweme_id) awemeHint = probe.aweme_id;

    if (probe.ok && probe.center) {
      const { x, y } = probe.center;
      await cdpClickAt(tabId, x, y);
      if (await waitSearchFeedOpen(tabId, videoIndex)) {
        return {
          ok: true,
          clicked: true,
          feed_open: true,
          is_search_feed: true,
          mode: "cdp_real_mouse",
          click_by: probe.click_by ?? "cdp",
          video_index: probe.video_index ?? videoIndex,
          available: probe.available,
          aweme_id: awemeHint || probe.aweme_id,
          url: lastUrl,
          attempt,
          message: `已点击第 ${probe.video_index ?? videoIndex} 个搜索结果并打开 Feed 浮层（CDP）`,
        };
      }
      lastMessage = "CDP 点击后未进入搜索 Feed 浮层";
    } else {
      lastMessage = probe.message ?? "未找到搜索结果视频卡片";
    }

    const domFallback = await domOpenFeed(tabId, {
      ...payload,
      video_index: videoIndex,
      aweme_id: awemeHint,
      strategy: "full",
    });
    lastUrl = domFallback.url ?? lastUrl;
    if (searchFeedSuccess(domFallback)) {
      return {
        ...domFallback,
        attempt,
        aweme_id: awemeHint || domFallback.aweme_id,
      };
    }

    lastMessage = domFallback.message ?? lastMessage;
    await sleep(1000 + attempt * 400);
  }

  return {
    ok: false,
    feed_open: false,
    is_search_feed: false,
    mode: "multi_strategy",
    video_index: videoIndex,
    aweme_id: awemeHint,
    url: lastUrl,
    message: lastMessage,
  };
}

function isLikelySearchUrl(platform: string, url?: string | null): boolean {
  if (!url) return false;
  if (platform === "douyin") return /\/search\/|\/jingxuan\/search\/|\/root\/search\//i.test(url);
  if (platform === "xiaohongshu") {
    return /search_result/i.test(url) || /\/explore\/?(?:\?|$)/i.test(url.split("#")[0]);
  }
  if (platform === "kuaishou") return /\/search\/|searchKey=/i.test(url);
  return false;
}

export async function prepareSearchForVideoBackground(payload: Record<string, unknown> = {}) {
  const platform = String(payload.platform ?? "douyin");
  const tab = await resolveLabTabForAction("plugin_lab.prepare_search_video", platform);
  if (!tab.id) throw new Error("lab tab has no id");
  const tabId = tab.id;

  try {
    await sendContentPluginLabCommand(tabId, "plugin_lab.close_video_detail", payload, {
      skipPreflight: true,
    });
  } catch {
    // already closed
  }
  await sleep(400);

  let current = await chrome.tabs.get(tabId);
  if (isLikelySearchUrl(platform, current.url) && current.url) {
    await rememberLabSearchUrl(platform, current.url);
  }

  let storedSearch = await readLabSearchUrl(platform);
  if (!storedSearch && platform === "kuaishou") {
    const keyword = String(payload.search_key ?? payload.keyword ?? "").trim();
    if (keyword) {
      storedSearch = `https://www.kuaishou.com/search/video?searchKey=${encodeURIComponent(keyword)}`;
    }
  }

  if (storedSearch && !isLikelySearchUrl(platform, current.url)) {
    await chrome.tabs.update(tabId, { url: storedSearch });
    await waitForTabLoad(tabId, 12_000);
    await sleep(800);
  } else if (!isLikelySearchUrl(platform, current.url)) {
    await chrome.tabs.goBack(tabId).catch(() => undefined);
    await waitForTabLoad(tabId, 8_000);
    await sleep(600);
    current = await chrome.tabs.get(tabId);
    if (!isLikelySearchUrl(platform, current.url) && storedSearch) {
      await chrome.tabs.update(tabId, { url: storedSearch });
      await waitForTabLoad(tabId, 12_000);
      await sleep(800);
    }
  }

  return sendContentPluginLabCommand(
    tabId,
    "plugin_lab.prepare_search_video",
    { ...payload, skip_restore: true },
    { skipPreflight: true },
  );
}
