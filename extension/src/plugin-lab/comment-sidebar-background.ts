import { resolveLabTabForAction } from "./resolve-lab-tab";
import {
  attachDebugger,
  clickMouse,
  detachDebugger,
  moveMouse,
} from "./real-mouse";
import { humanPace } from "./search-input";
import { sendContentPluginLabCommand } from "./tab-command";

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

interface SidebarProbe {
  active?: boolean;
  sidebar_active?: boolean;
  sidebar_ready?: boolean;
  feed_open?: boolean;
  is_search_feed?: boolean;
  is_standalone_video?: boolean;
  comment_item_count?: number;
  has_visible_comments?: boolean;
  has_comments_header?: boolean;
  icon_targets?: Array<{ selector: string; center: { x: number; y: number }; priority?: number }>;
  video_player_center?: { x: number; y: number } | null;
  url?: string;
  message?: string;
}

function sidebarReady(probe: SidebarProbe): boolean {
  if (probe.sidebar_ready === true) return true;
  return (probe.comment_item_count ?? 0) > 0;
}

async function probe(tabId: number): Promise<SidebarProbe> {
  return (await sendContentPluginLabCommand(tabId, "plugin_lab.comment_sidebar_probe", {})) as SidebarProbe;
}

async function activateViaContent(tabId: number): Promise<{
  ok?: boolean;
  method?: string;
  comment_item_count?: number;
  message?: string;
}> {
  return (await sendContentPluginLabCommand(
    tabId,
    "plugin_lab.activate_comment_sidebar",
    {},
    { skipPreflight: true },
  )) as {
    ok?: boolean;
    method?: string;
    comment_item_count?: number;
    message?: string;
  };
}

/** 步骤 10：CDP 真实鼠标打开评论区，失败则 content DOM 兜底 */
export async function clickCommentButtonBackground() {
  const tab = await resolveLabTabForAction("plugin_lab.click_comment_btn");
  if (!tab.id) throw new Error("target tab has no id");
  const tabId = tab.id;

  let status = await probe(tabId);

  if (status.is_standalone_video) {
    return {
      ok: false,
      mode: "cdp_real_mouse",
      is_standalone_video: true,
      url: status.url ?? tab.url,
      message: "误入独立视频详情页，请先通过 modal_id 打开搜索 Feed 浮层",
    };
  }

  if (sidebarReady(status)) {
    return {
      ok: true,
      already_open: true,
      mode: "cdp_real_mouse",
      is_search_feed: status.is_search_feed,
      comment_item_count: status.comment_item_count ?? 0,
      url: status.url ?? tab.url,
      message: status.message ?? "评论区已展开",
    };
  }

  if (!status.is_search_feed && !status.feed_open) {
    const onProfileFeed = Boolean(
      status.url && /\/user\//.test(status.url) && /modal_id=\d{8,22}/i.test(status.url),
    );
    if (!onProfileFeed) {
      return {
        ok: false,
        mode: "cdp_real_mouse",
        feed_open: false,
        is_search_feed: false,
        url: status.url ?? tab.url,
        message: "视频 Feed 浮层未打开，请先打开搜索结果或主页作品视频",
      };
    }
  }

  const targets = status.icon_targets ?? [];
  let method = "none";

  if (targets.length > 0) {
    await attachDebugger(tabId);
    try {
      // 搜索/主页 Feed 浮层：勿点视频区域（易误触点赞/收藏），只点评论图标
      for (let attempt = 0; attempt < 6 && !sidebarReady(status); attempt += 1) {
        const primary = (status.icon_targets ?? targets)[0];
        if (!primary) break;

        await moveMouse(tabId, primary.center.x, primary.center.y);
        await sleep(humanPace.mouseHover());
        await clickMouse(tabId, primary.center.x, primary.center.y);
        method = primary.selector;
        await sleep(humanPace.afterCommentClick());

        status = await probe(tabId);
        if (sidebarReady(status)) break;
        await sleep(humanPace.beforeCommentAction());
      }
    } finally {
      await detachDebugger(tabId);
    }
  }

  if (!sidebarReady(status)) {
    const domResult = await activateViaContent(tabId);
    status = await probe(tabId);
    if (domResult.ok || sidebarReady(status)) {
      return {
        ok: true,
        already_open: false,
        mode: "content_dom",
        method: domResult.method ?? method,
        comment_item_count: status.comment_item_count ?? domResult.comment_item_count ?? 0,
        is_search_feed: status.is_search_feed,
        url: status.url ?? tab.url,
        message: domResult.message ?? "已通过 DOM 展开评论区",
      };
    }
  }

  const ok = sidebarReady(status);

  return {
    ok,
    already_open: false,
    mode: ok ? "cdp_real_mouse" : targets.length > 0 ? "cdp_real_mouse" : "content_dom",
    method,
    comment_item_count: status.comment_item_count ?? 0,
    has_comments_header: status.has_comments_header,
    is_search_feed: status.is_search_feed,
    icon_targets_tried: targets.length,
    url: status.url ?? tab.url,
    message: ok
      ? status.message ?? "已打开评论区"
      : "未能展开评论区，请确认步骤 9 已打开视频 Feed，或刷新页面后重试",
  };
}
