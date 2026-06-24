import { resolveLabTabForAction } from "./resolve-lab-tab";
import {
  withTabDebugger,
  clickMouse,
  moveMouse,
} from "./real-mouse";
import { COMMENT_SIDEBAR_TIMING } from "./comment-sidebar-shared";
import { humanPace } from "./search-input";
import { sendContentPluginLabCommand } from "./tab-command";

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

interface SidebarProbe {
  sidebar_ready?: boolean;
  sidebar_active?: boolean;
  active?: boolean;
  is_standalone_video?: boolean;
  is_video_detail_side_panel?: boolean;
  comment_item_count?: number;
  has_comments_header?: boolean;
  icon_targets?: Array<{ selector: string; center: { x: number; y: number }; priority?: number }>;
  url?: string;
  message?: string;
}

function sidebarPanelOpen(probe: SidebarProbe): boolean {
  if (probe.sidebar_ready === true) return true;
  if (probe.sidebar_active === true || probe.active === true) return true;
  if (probe.has_comments_header === true) return true;
  return (probe.comment_item_count ?? 0) > 0;
}

async function probeVideoDetail(tabId: number): Promise<SidebarProbe> {
  return (await sendContentPluginLabCommand(
    tabId,
    "plugin_lab.comment_sidebar_probe",
    { playback_mode: "video_detail" },
    { skipPreflight: true },
  )) as SidebarProbe;
}

async function activateVideoDetailViaContent(tabId: number) {
  return (await sendContentPluginLabCommand(
    tabId,
    "plugin_lab.activate_comment_sidebar",
    { playback_mode: "video_detail" },
    { skipPreflight: true },
  )) as { ok?: boolean; method?: string; message?: string };
}

function buildVideoDetailSuccessResult(
  tab: chrome.tabs.Tab,
  status: SidebarProbe,
  extra: { already_open?: boolean; mode: string; method?: string; message?: string },
) {
  return {
    ok: true,
    playback_mode: "video_detail",
    already_open: extra.already_open ?? false,
    mode: extra.mode,
    method: extra.method,
    sidebar_active: status.sidebar_active ?? status.active ?? true,
    has_comments_header: status.has_comments_header ?? false,
    is_search_feed: false,
    is_standalone_video: true,
    comment_item_count: status.comment_item_count ?? 0,
    url: status.url ?? tab.url,
    message: extra.message ?? status.message ?? "视频详情页评论区已展开",
  };
}

async function waitForSidebarPanel(tabId: number, maxMs = COMMENT_SIDEBAR_TIMING.panelPollMs) {
  const deadline = Date.now() + maxMs;
  let status = await probeVideoDetail(tabId);
  while (Date.now() < deadline) {
    if (sidebarPanelOpen(status)) return status;
    await sleep(COMMENT_SIDEBAR_TIMING.pollIntervalMs);
    status = await probeVideoDetail(tabId);
  }
  return status;
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
    for (let attempt = 0; attempt < COMMENT_SIDEBAR_TIMING.maxCdpClicks; attempt += 1) {
      if (sidebarPanelOpen(status)) break;

      const primary = (status.icon_targets ?? targets)[0];
      if (!primary) break;

      await moveMouse(tabId, primary.center.x, primary.center.y);
      await sleep(humanPace.mouseHover());
      await clickMouse(tabId, primary.center.x, primary.center.y);
      method = primary.selector;
      await sleep(humanPace.afterCommentClick());

      status = await probeVideoDetail(tabId);
      if (sidebarPanelOpen(status)) break;
      await sleep(humanPace.beforeCommentAction());
    }
  });

  return { status, method };
}

async function activateVideoDetailComments(tabId: number, tab: chrome.tabs.Tab) {
  let status = await probeVideoDetail(tabId);

  if (sidebarPanelOpen(status)) {
    status = await waitForSidebarPanel(tabId);
    return buildVideoDetailSuccessResult(tab, status, {
      already_open: true,
      mode: "content_dom",
    });
  }

  const domResult = await activateVideoDetailViaContent(tabId);
  status = await waitForSidebarPanel(tabId);
  if (domResult.ok || sidebarPanelOpen(status)) {
    return buildVideoDetailSuccessResult(tab, status, {
      mode: "content_dom",
      method: domResult.method,
      message: domResult.message ?? "已通过 DOM 展开视频详情页评论区",
    });
  }

  const targets = status.icon_targets ?? [];
  if (targets.length > 0) {
    const cdp = await tryCdpCommentClick(tabId, status, targets);
    status = await waitForSidebarPanel(tabId);
    if (sidebarPanelOpen(status)) {
      return buildVideoDetailSuccessResult(tab, status, {
        mode: "cdp_real_mouse",
        method: cdp.method,
        message: status.message ?? "已通过 CDP 展开视频详情页评论区",
      });
    }
  }

  const ok = sidebarPanelOpen(status);
  return {
    ok,
    playback_mode: "video_detail",
    already_open: false,
    mode: ok ? "content_dom" : targets.length > 0 ? "cdp_real_mouse" : "content_dom",
    method: domResult.method,
    sidebar_active: status.sidebar_active ?? status.active ?? false,
    has_comments_header: status.has_comments_header ?? false,
    is_standalone_video: true,
    is_search_feed: false,
    comment_item_count: status.comment_item_count ?? 0,
    icon_targets_tried: targets.length,
    url: status.url ?? tab.url,
    message: ok
      ? status.message ?? "已打开视频详情页评论区"
      : status.is_video_detail_side_panel
        ? "未能展开视频详情页右侧评论区，请确认评论图标可见"
        : "未能展开视频详情页评论区，请确认「评论」Tab 可见",
  };
}

/** /video/ 详情页：点评论按钮 */
export async function clickVideoDetailCommentButtonBackground(payload: Record<string, unknown> = {}) {
  const platformHint = String(payload.platform ?? "").trim() || undefined;
  const tab = await resolveLabTabForAction("plugin_lab.click_comment_btn", platformHint);
  if (!tab.id) throw new Error("target tab has no id");
  const tabId = tab.id;

  let status: SidebarProbe | null = null;
  for (let attempt = 0; attempt < 8; attempt += 1) {
    status = await probeVideoDetail(tabId);
    if (status.is_standalone_video || status.is_video_detail_side_panel) break;
    await sleep(900 + attempt * 400);
  }
  if (!status) {
    throw new Error("video detail comment sidebar probe failed");
  }

  return activateVideoDetailComments(tabId, tab);
}
