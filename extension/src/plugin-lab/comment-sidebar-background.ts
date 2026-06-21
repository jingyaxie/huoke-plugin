import { resolveLabTabForAction } from "./resolve-lab-tab";
import {
  attachDebugger,
  clickMouse,
  detachDebugger,
  moveMouse,
  randDelay,
} from "./real-mouse";
import { sendContentPluginLabCommand } from "./tab-command";

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

interface SidebarProbe {
  active?: boolean;
  sidebar_active?: boolean;
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

function sidebarOpen(probe: SidebarProbe): boolean {
  return Boolean(
    probe.sidebar_active
    || probe.active
    || (probe.comment_item_count ?? 0) > 0
    || probe.has_comments_header,
  );
}

async function probe(tabId: number): Promise<SidebarProbe> {
  return (await sendContentPluginLabCommand(tabId, "plugin_lab.comment_sidebar_probe", {})) as SidebarProbe;
}

/** 步骤 10：CDP 真实鼠标打开评论区 */
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

  if (sidebarOpen(status)) {
    return {
      ok: true,
      already_open: true,
      mode: "cdp_real_mouse",
      is_search_feed: status.is_search_feed,
      comment_item_count: status.comment_item_count ?? 0,
      has_comments_header: status.has_comments_header,
      url: status.url ?? tab.url,
      message: status.message ?? "评论区已打开",
    };
  }

  if (!status.is_search_feed && !status.feed_open) {
    return {
      ok: false,
      mode: "cdp_real_mouse",
      feed_open: false,
      is_search_feed: false,
      url: status.url ?? tab.url,
      message: "搜索 Feed 浮层未打开，请先执行步骤 9 打开搜索结果视频",
    };
  }

  // 搜索 Feed 浮层：右侧评论栏常已展开
  if (status.is_search_feed && (status.has_visible_comments || status.has_comments_header)) {
    return {
      ok: true,
      already_open: true,
      mode: "cdp_real_mouse",
      is_search_feed: true,
      comment_item_count: status.comment_item_count ?? 0,
      url: status.url ?? tab.url,
      message: "搜索 Feed 右侧评论栏已可见",
    };
  }

  const targets = status.icon_targets ?? [];
  if (targets.length === 0) {
    return {
      ok: false,
      mode: "cdp_real_mouse",
      feed_open: true,
      is_search_feed: status.is_search_feed,
      url: status.url ?? tab.url,
      message: "未找到评论按钮 DOM（feed-comment-icon / 评论 Tab）",
    };
  }

  let method = "none";

  await attachDebugger(tabId);
  try {
    // 非搜索 Feed 才点视频暂停，搜索浮层右侧常已有评论栏，点视频易误触点赞
    if (!status.is_search_feed && status.video_player_center) {
      await clickMouse(tabId, status.video_player_center.x, status.video_player_center.y);
      await sleep(randDelay(350, 600));
      status = await probe(tabId);
      if (sidebarOpen(status)) {
        method = "video_pause";
      }
    }

    for (let attempt = 0; attempt < 6 && !sidebarOpen(status); attempt += 1) {
      const roundTargets = status.icon_targets ?? targets;
      for (const target of roundTargets) {
        await moveMouse(tabId, target.center.x, target.center.y);
        await sleep(randDelay(220, 380));
        await clickMouse(tabId, target.center.x, target.center.y);
        method = target.selector;
        await sleep(randDelay(550, 900));

        status = await probe(tabId);
        if (sidebarOpen(status)) break;
      }

      if (sidebarOpen(status)) break;
      await sleep(350);
    }
  } finally {
    await detachDebugger(tabId);
  }

  const ok = sidebarOpen(status);

  return {
    ok,
    already_open: false,
    mode: "cdp_real_mouse",
    method,
    comment_item_count: status.comment_item_count ?? 0,
    has_comments_header: status.has_comments_header,
    is_search_feed: status.is_search_feed,
    icon_targets_tried: targets.length,
    url: status.url ?? tab.url,
    message: ok
      ? status.message ?? "已打开评论区"
      : "未能打开评论区，请确认步骤 9 已打开视频 Feed，或刷新页面后重试",
  };
}
