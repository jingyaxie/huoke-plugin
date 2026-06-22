import { resolveLabTabForAction } from "./resolve-lab-tab";
import {
  withTabDebugger,
  clickMouse,
  moveMouse,
} from "./real-mouse";
import { humanPace } from "./search-input";
import { sendContentPluginLabCommand } from "./tab-command";

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

interface SidebarProbe {
  sidebar_ready?: boolean;
  feed_open?: boolean;
  is_search_feed?: boolean;
  comment_item_count?: number;
  has_comments_header?: boolean;
  icon_targets?: Array<{ selector: string; center: { x: number; y: number }; priority?: number }>;
  url?: string;
  message?: string;
}

function sidebarReady(probe: SidebarProbe): boolean {
  if (probe.sidebar_ready === true) return true;
  return (probe.comment_item_count ?? 0) > 0;
}

async function probeFeed(tabId: number): Promise<SidebarProbe> {
  return (await sendContentPluginLabCommand(
    tabId,
    "plugin_lab.comment_sidebar_probe",
    { playback_mode: "feed" },
    { skipPreflight: true },
  )) as SidebarProbe;
}

async function activateFeedViaContent(tabId: number) {
  return (await sendContentPluginLabCommand(
    tabId,
    "plugin_lab.activate_comment_sidebar",
    { playback_mode: "feed" },
    { skipPreflight: true },
  )) as { ok?: boolean; method?: string; message?: string };
}

function buildFeedSuccessResult(
  tab: chrome.tabs.Tab,
  status: SidebarProbe,
  extra: { already_open?: boolean; mode: string; method?: string; message?: string },
) {
  return {
    ok: true,
    playback_mode: "feed",
    already_open: extra.already_open ?? false,
    mode: extra.mode,
    method: extra.method,
    is_search_feed: status.is_search_feed,
    is_standalone_video: false,
    comment_item_count: status.comment_item_count ?? 0,
    url: status.url ?? tab.url,
    message: extra.message ?? status.message ?? "Feed 评论区已展开",
  };
}

async function tryCdpCommentClick(
  tabId: number,
  status: SidebarProbe,
  targets: Array<{ selector: string; center: { x: number; y: number }; priority?: number }>,
): Promise<{ status: SidebarProbe; method: string }> {
  let method = "none";
  if (targets.length === 0) {
    return { status, method };
  }

  await withTabDebugger(tabId, async () => {
    for (let attempt = 0; attempt < 6 && !sidebarReady(status); attempt += 1) {
      const primary = (status.icon_targets ?? targets)[0];
      if (!primary) break;

      await moveMouse(tabId, primary.center.x, primary.center.y);
      await sleep(humanPace.mouseHover());
      await clickMouse(tabId, primary.center.x, primary.center.y);
      method = primary.selector;
      await sleep(humanPace.afterCommentClick());

      status = await probeFeed(tabId);
      if (sidebarReady(status)) break;
      await sleep(humanPace.beforeCommentAction());
    }
  });

  return { status, method };
}

/** 搜索/主页 Feed 浮层：点评论按钮 */
export async function clickFeedCommentButtonBackground(payload: Record<string, unknown> = {}) {
  const platformHint = String(payload.platform ?? "").trim() || undefined;
  const tab = await resolveLabTabForAction("plugin_lab.click_comment_btn", platformHint);
  if (!tab.id) throw new Error("target tab has no id");
  const tabId = tab.id;

  let status: SidebarProbe | null = null;
  for (let attempt = 0; attempt < 8; attempt += 1) {
    status = await probeFeed(tabId);
    if (status.is_search_feed || status.feed_open) break;
    await sleep(900 + attempt * 400);
  }
  if (!status) {
    throw new Error("feed comment sidebar probe failed");
  }

  if (sidebarReady(status)) {
    return buildFeedSuccessResult(tab, status, {
      already_open: true,
      mode: "cdp_real_mouse",
    });
  }

  if (!status.is_search_feed && !status.feed_open) {
    const onProfileFeed = Boolean(
      status.url && /\/user\//.test(status.url) && /modal_id=\d{8,22}/i.test(status.url),
    );
    if (!onProfileFeed) {
      return {
        ok: false,
        playback_mode: "feed",
        mode: "cdp_real_mouse",
        feed_open: false,
        is_search_feed: false,
        url: status.url ?? tab.url,
        message: "视频 Feed 浮层未打开，请先打开搜索结果或主页作品视频",
      };
    }
  }

  const domResult = await activateFeedViaContent(tabId);
  status = await probeFeed(tabId);
  if (domResult.ok || sidebarReady(status)) {
    return buildFeedSuccessResult(tab, status, {
      mode: "content_dom",
      method: domResult.method,
      message: domResult.message ?? "已通过 DOM 展开搜索 Feed 评论区",
    });
  }

  const targets = status.icon_targets ?? [];
  const cdp = await tryCdpCommentClick(tabId, status, targets);
  status = cdp.status;
  let method = cdp.method;

  if (!sidebarReady(status)) {
    const retryDom = await activateFeedViaContent(tabId);
    status = await probeFeed(tabId);
    if (retryDom.ok || sidebarReady(status)) {
      return buildFeedSuccessResult(tab, status, {
        mode: "content_dom",
        method: retryDom.method ?? method,
        message: retryDom.message ?? "已通过 DOM 展开 Feed 评论区",
      });
    }
  }

  const ok = sidebarReady(status);
  return {
    ok,
    playback_mode: "feed",
    already_open: false,
    mode: ok ? "cdp_real_mouse" : targets.length > 0 ? "cdp_real_mouse" : "content_dom",
    method,
    comment_item_count: status.comment_item_count ?? 0,
    has_comments_header: status.has_comments_header,
    is_search_feed: status.is_search_feed,
    icon_targets_tried: targets.length,
    url: status.url ?? tab.url,
    message: ok
      ? status.message ?? "已打开 Feed 评论区"
      : "未能展开 Feed 评论区，请确认步骤 9 已打开视频 Feed，或刷新页面后重试",
  };
}
