/**
 * 抖音 Service Worker — 优先搜索 Feed 浮层，失败再开独立详情窗
 */
import { humanPace } from "../../search-input";
import { readLabSearchUrl, rememberLabSearchUrl } from "../../lab-context";
import { resolveLabTabForAction } from "../../resolve-lab-tab";
import {
  openVideoInDetailWindow,
  resolveSearchVideoUrl,
} from "../../detail-window";
import {
  withTabDebugger,
  clickMouse,
  dragMouse,
  moveMouse,
  pressKey,
} from "../../real-mouse";
import { sendContentPluginLabCommand } from "../../tab-command";
import { sleep, waitForTabLoad } from "../shared/tab-load";

const PLATFORM = "douyin";

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
  clicked?: boolean;
  click_by?: string;
  mode?: string;
  video_index?: number;
  available?: number;
  url?: string;
  message?: string;
  attempt?: number;
  aweme_id?: string;
}

async function probeVideo(tabId: number, payload: Record<string, unknown>): Promise<VideoProbe> {
  return (await sendContentPluginLabCommand(
    tabId,
    "plugin_lab.search_video_probe",
    { ...payload, platform: PLATFORM },
    { skipPreflight: true },
  )) as VideoProbe;
}

async function prepareSearchPage(tabId: number) {
  return (await sendContentPluginLabCommand(
    tabId,
    "plugin_lab.prepare_search_video",
    { skip_restore: true, platform: PLATFORM },
    { skipPreflight: true },
  )) as { ok?: boolean; card_count?: number; message?: string };
}

async function domOpenFeed(tabId: number, payload: Record<string, unknown>): Promise<ClickResult> {
  return (await sendContentPluginLabCommand(
    tabId,
    "plugin_lab.search_video_dom_click",
    { ...payload, platform: PLATFORM },
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
  return Boolean((await probeVideo(tabId, { video_index: videoIndex, status_only: true })).is_search_feed);
}

async function cdpClickAt(tabId: number, x: number, y: number): Promise<void> {
  await withTabDebugger(tabId, async () => {
    await moveMouse(tabId, x, y);
    await sleep(humanPace.mouseHover());
    await clickMouse(tabId, x, y);
    await sleep(humanPace.posterClick());
  });
}

function searchFeedSuccess(result: ClickResult): boolean {
  return Boolean(result.ok && result.is_search_feed);
}

function isRealAwemeId(raw: unknown): boolean {
  return /^\d{8,22}$/.test(String(raw ?? "").trim());
}

function isDouyinVideoPageUrl(url: string): boolean {
  return /\/video\/\d{8,22}/i.test(url);
}

async function enrichSearchVideoPayload(
  tabId: number,
  videoIndex: number,
  payload: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const next = { ...payload };
  const existing = String(next.aweme_id ?? next.aweme_hint ?? "").trim();
  if (isRealAwemeId(existing) && next.rect) {
    return next;
  }

  try {
    const data = (await sendContentPluginLabCommand(
      tabId,
      "plugin_lab.fetch_search_results",
      { limit: Math.max(videoIndex, 20), platform: PLATFORM },
      { skipPreflight: true },
    )) as {
      items?: Array<{ aweme_id?: string; url?: string; rect?: unknown }>;
    };
    const item = data.items?.[videoIndex - 1];
    if (item) {
      const itemAweme = String(item.aweme_id ?? "").trim();
      if (isRealAwemeId(itemAweme)) {
        next.aweme_id = itemAweme;
        next.aweme_hint = itemAweme;
      }
      if (!next.rect && item.rect && typeof item.rect === "object") {
        next.rect = item.rect;
      }
      if (!next.video_url && item.url) {
        next.video_url = item.url;
      }
    }
  } catch {
    // keep original payload
  }

  return next;
}

async function tryOpenKnownAweme(
  tabId: number,
  videoIndex: number,
  payload: Record<string, unknown>,
  awemeId: string,
): Promise<ClickResult | null> {
  await prepareSearchPage(tabId);
  const modal = await domOpenFeed(tabId, {
    ...payload,
    video_index: videoIndex,
    aweme_id: awemeId,
    strategy: "modal_only",
  });
  if (searchFeedSuccess(modal)) {
    return { ...modal, mode: "modal_aweme", aweme_id: awemeId };
  }
  return null;
}

async function runFeedOpenAttempts(
  tabId: number,
  videoIndex: number,
  payload: Record<string, unknown>,
  initialUrl: string,
): Promise<ClickResult> {
  let lastMessage = "未打开搜索 Feed 浮层";
  let lastUrl = initialUrl;
  let awemeHint = String(payload.aweme_id ?? payload.aweme_hint ?? "").trim();

  for (let attempt = 1; attempt <= 4; attempt += 1) {
    const prep = await prepareSearchPage(tabId);
    if (!prep.ok) {
      lastMessage = prep.message ?? "搜索列表未就绪";
      await sleep(800 + attempt * 350);
      continue;
    }

    const probeAweme = await probeVideo(tabId, { ...payload, video_index: videoIndex, aweme_id: awemeHint });
    if (!awemeHint && probeAweme.aweme_id && isRealAwemeId(probeAweme.aweme_id)) {
      awemeHint = probeAweme.aweme_id;
    }

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

    const hadAwemeBeforeProbe = Boolean(awemeHint);
    const probe = await probeVideo(tabId, { ...payload, video_index: videoIndex, aweme_id: awemeHint });
    lastUrl = probe.url ?? lastUrl;
    if (!awemeHint && probe.aweme_id && isRealAwemeId(probe.aweme_id)) {
      awemeHint = probe.aweme_id;
    }

    if (!hadAwemeBeforeProbe && awemeHint) {
      const modalAfterProbe = await domOpenFeed(tabId, {
        ...payload,
        video_index: videoIndex,
        aweme_id: awemeHint,
        strategy: "modal_only",
      });
      lastUrl = modalAfterProbe.url ?? lastUrl;
      if (searchFeedSuccess(modalAfterProbe)) {
        return { ...modalAfterProbe, attempt, aweme_id: awemeHint };
      }
      lastMessage = modalAfterProbe.message ?? lastMessage;
    }

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
      return { ...domFallback, attempt, aweme_id: awemeHint || domFallback.aweme_id };
    }

    lastMessage = domFallback.message ?? lastMessage;
    await sleep(1000 + attempt * 400);
  }

  return {
    ok: false,
    feed_open: false,
    is_search_feed: false,
    mode: "feed_attempts",
    video_index: videoIndex,
    aweme_id: awemeHint,
    url: lastUrl,
    message: lastMessage,
  };
}

export async function clickSearchVideoBackground(payload: Record<string, unknown> = {}) {
  const tab = await resolveLabTabForAction("plugin_lab.click_search_video", PLATFORM);
  if (!tab.id) throw new Error("target tab has no id");
  const tabId = tab.id;
  const videoIndex = Math.max(1, Number(payload.video_index ?? payload.index ?? 1));
  const openStrategy = String(payload.open_strategy ?? "auto").trim().toLowerCase();
  const detailOnly = openStrategy === "detail";
  const feedOnly = openStrategy === "feed" || payload.use_detail_window === false;
  const enrichedPayload = await enrichSearchVideoPayload(tabId, videoIndex, payload);

  let feedResult: ClickResult | null = null;

  if (!detailOnly) {
    const awemeHint = String(enrichedPayload.aweme_id ?? enrichedPayload.aweme_hint ?? "").trim();
    if (isRealAwemeId(awemeHint)) {
      const fast = await tryOpenKnownAweme(tabId, videoIndex, enrichedPayload, awemeHint);
      if (fast?.ok) return fast;
    }

    feedResult = await runFeedOpenAttempts(tabId, videoIndex, enrichedPayload, tab.url ?? "");
    if (searchFeedSuccess(feedResult)) {
      return feedResult;
    }
    if (feedOnly) {
      return feedResult;
    }
  }

  const resolved = await resolveSearchVideoUrl(tabId, videoIndex, {
    ...enrichedPayload,
    platform: PLATFORM,
  });
  if (resolved.url && isDouyinVideoPageUrl(resolved.url)) {
    const detailResult = await openVideoInDetailWindow({
      platform: PLATFORM,
      url: resolved.url,
      listTabId: tabId,
      aweme_id: resolved.aweme_id,
      video_index: videoIndex,
    });
    if (detailResult.ok) {
      return detailResult;
    }
  }

  if (feedResult) {
    return {
      ...feedResult,
      message:
        feedResult.message
        || "搜索 Feed 未打开，且无法通过独立窗口打开视频",
    };
  }

  return runFeedOpenAttempts(tabId, videoIndex, enrichedPayload, tab.url ?? "");
}

function isDouyinSearchUrl(url?: string | null): boolean {
  if (!url) return false;
  return /\/search\/|\/jingxuan\/search\/|\/root\/search\//i.test(url) || /modal_id=\d/i.test(url);
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
  const onSearchPage = isDouyinSearchUrl(current.url);
  if (onSearchPage && current.url) {
    await rememberLabSearchUrl(PLATFORM, current.url);
  }

  const storedSearch = await readLabSearchUrl(PLATFORM);
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

interface SwipeFeedResult {
  ok?: boolean;
  is_search_feed?: boolean;
  aweme_id?: string;
  previous_aweme_id?: string | null;
  method?: string;
  url?: string;
  message?: string;
}

async function probeFeedAweme(tabId: number): Promise<VideoProbe> {
  return (await sendContentPluginLabCommand(
    tabId,
    "plugin_lab.search_video_probe",
    { status_only: true, platform: PLATFORM },
    { skipPreflight: true },
  )) as VideoProbe;
}

/** 搜索 Feed 内切下一个视频：DOM 手势优先，失败再用 CDP 拖拽 */
export async function swipeSearchFeedNextBackground(
  payload: Record<string, unknown> = {},
): Promise<SwipeFeedResult> {
  const tab = await resolveLabTabForAction("plugin_lab.swipe_search_feed_next", PLATFORM);
  if (!tab.id) throw new Error("lab tab has no id");
  const tabId = tab.id;

  const status = await probeFeedAweme(tabId);
  if (!status.is_search_feed) {
    return {
      ok: false,
      is_search_feed: false,
      url: tab.url ?? "",
      message: "不在搜索 Feed 浮层，无法 Feed 内切下一个视频",
    };
  }

  const before = String(status.aweme_id ?? "").trim() || null;

  const contentResult = (await sendContentPluginLabCommand(
    tabId,
    "plugin_lab.swipe_search_feed_next",
    { ...payload, platform: PLATFORM },
    { skipPreflight: true },
  )) as SwipeFeedResult;
  if (contentResult.ok) {
    return { ...contentResult, method: contentResult.method ?? "content_dom" };
  }

  const sidebar = (await sendContentPluginLabCommand(
    tabId,
    "plugin_lab.comment_sidebar_probe",
    { platform: PLATFORM },
    { skipPreflight: true },
  )) as { video_player_center?: { x: number; y: number } | null };

  const center = sidebar.video_player_center;
  if (!center || typeof center.x !== "number" || typeof center.y !== "number") {
    return contentResult;
  }

  await withTabDebugger(tabId, async () => {
    await pressKey(tabId, "Escape", { code: "Escape" });
    await sleep(180);
    await pressKey(tabId, "Escape", { code: "Escape" });
    await sleep(humanPace.listPrepare());
    await clickMouse(tabId, center.x, center.y);
    await sleep(humanPace.posterClick());
    await dragMouse(tabId, center.x, center.y + 150, center.x, center.y - 240, 12);
    await sleep(humanPace.posterClick());
    await pressKey(tabId, "ArrowDown", { code: "ArrowDown" });
  });

  for (let i = 0; i < 14; i += 1) {
    await sleep(260);
    const afterStatus = await probeFeedAweme(tabId);
    const after = String(afterStatus.aweme_id ?? "").trim();
    if (after && after !== before) {
      return {
        ok: true,
        is_search_feed: true,
        aweme_id: after,
        previous_aweme_id: before,
        method: "cdp_drag",
        url: afterStatus.url ?? tab.url ?? "",
        message: "已通过 CDP 拖拽在搜索 Feed 内切换到下一个视频",
      };
    }
  }

  return {
    ...contentResult,
    message: contentResult.message ?? "Feed 内未能切换到下一个视频（DOM+CDP）",
  };
}
