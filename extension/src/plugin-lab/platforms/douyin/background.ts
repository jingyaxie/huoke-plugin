/**
 * 抖音 Service Worker — 仅搜索 Feed 浮层，不走独立窗 /video/
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
  moveMouse,
} from "../../real-mouse";
import { sendContentPluginLabCommand } from "../../tab-command";
import { buildSearchResultPayload } from "../../click-search-btn";
import { getSearchApiDebug, pollSearchApiCache } from "../../search-api";
import { withSearchNetworkCapture } from "../../search-network-debugger";
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
  return /^\d{10,22}$/.test(String(raw ?? "").trim());
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
  const useDetailWindow = payload.use_detail_window !== false && openStrategy !== "feed";

  if (useDetailWindow) {
    const resolved = await resolveSearchVideoUrl(tabId, videoIndex, {
      ...payload,
      platform: PLATFORM,
    });
    if (resolved.url) {
      return openVideoInDetailWindow({
        platform: PLATFORM,
        url: resolved.url,
        listTabId: tabId,
        aweme_id: resolved.aweme_id,
        video_index: videoIndex,
      });
    }
  }

  const awemeHint = String(payload.aweme_id ?? payload.aweme_hint ?? "").trim();
  if (isRealAwemeId(awemeHint)) {
    const fast = await tryOpenKnownAweme(tabId, videoIndex, payload, awemeHint);
    if (fast?.ok) return fast;
  }

  return runFeedOpenAttempts(tabId, videoIndex, payload, tab.url ?? "");
}

export async function clickSearchButtonBackground(payload: Record<string, unknown> = {}) {
  const tab = await resolveLabTabForAction("plugin_lab.click_search_btn", PLATFORM);
  if (!tab.id) throw new Error("lab tab has no id");
  const tabId = tab.id;

  return withSearchNetworkCapture(tabId, async () => {
    await sendContentPluginLabCommand(
      tabId,
      "plugin_lab.search_prepare",
      { platform: PLATFORM },
      { skipPreflight: true },
    );

    const clickResult = (await sendContentPluginLabCommand(
      tabId,
      "plugin_lab.search_submit",
      {
        platform: PLATFORM,
        search_text: payload.search_text ?? payload.keyword,
      },
      { skipPreflight: true },
    )) as Record<string, unknown>;

    const polled = await pollSearchApiCache({ timeoutMs: 12_000, minItems: 1 });
    let items = polled?.items ?? [];
    let captureMethod: "api" | "dom" | "none" = items.length > 0 ? "api" : "none";

    if (!items.length) {
      const domResult = (await sendContentPluginLabCommand(
        tabId,
        "plugin_lab.fetch_search_results",
        { limit: 20, platform: PLATFORM },
        { skipPreflight: true },
      )) as Record<string, unknown>;
      const domItems = domResult.items ?? domResult.results;
      if (Array.isArray(domItems) && domItems.length > 0) {
        items = domItems as typeof items;
        captureMethod = (domResult.capture_method as typeof captureMethod) ?? "dom";
      }
    }

    const debug = await getSearchApiDebug().catch(() => null);
    const hasResults = items.length > 0;
    const activeTab = await chrome.tabs.get(tabId);
    const onSearchPage = /\/search\/|\/jingxuan\/search\/|\/root\/search\//i.test(activeTab.url ?? "");
    const ok = Boolean(clickResult.ok) || hasResults || onSearchPage;

    return {
      ...clickResult,
      ok,
      ...buildSearchResultPayload(items, captureMethod),
      api_events_seen: debug?.eventsSeen ?? 0,
      last_api_url: debug?.lastApiUrl ?? "",
      last_api_status: debug?.lastStatus,
      last_body_kind: debug?.lastBodyKind ?? "",
      message: hasResults
        ? captureMethod === "api"
          ? `已触发搜索，从接口获取 ${items.length} 条结果`
          : `已进入搜索页，接口未解析到数据，已用 DOM 兜底 ${items.length} 条`
        : ok
          ? "已进入搜索页，但接口暂无数据"
          : "已点击搜索，但未进入搜索结果页，也未截获搜索接口",
    };
  });
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
