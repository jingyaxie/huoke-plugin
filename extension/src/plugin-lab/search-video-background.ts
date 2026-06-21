import { humanPace } from "./search-input";
import { resolveLabTabForAction } from "./resolve-lab-tab";
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

/** 步骤 9：抖音优先 modal Feed；小红书/快手直接 DOM 打开详情页 */
export async function clickSearchVideoBackground(payload: Record<string, unknown> = {}) {
  const tab = await resolveLabTabForAction("plugin_lab.click_search_video");
  if (!tab.id) throw new Error("target tab has no id");
  const tabId = tab.id;
  const videoIndex = Math.max(1, Number(payload.video_index ?? payload.index ?? 1));

  if (isNonDouyinDetailPlatform(tab.url)) {
    await prepareSearchPage(tabId);
    const domResult = await domOpenFeed(tabId, {
      ...payload,
      video_index: videoIndex,
    });
    return {
      ok: Boolean(domResult.ok),
      feed_open: Boolean(domResult.ok),
      is_search_feed: false,
      is_content_detail: Boolean(domResult.ok),
      mode: "dom_detail",
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
