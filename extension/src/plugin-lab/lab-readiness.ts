import {
  contextLabel,
  contextMatchesUrl,
  contextRequirementForAction,
  detectPageContext,
  type LabPageContext,
} from "./lab-context";
import { getPluginLabAdapterForUrl } from "./platforms/registry";
import {
  countPlatformSearchCards,
  isPlatformFeedOverlayOpen,
  isPlatformSearchResultsPage,
} from "./platforms/platform-readiness";
import { probeFilterDom } from "./filter-dom";
import { findSearchInputMatch } from "./search-input";
import { getCachedSearchApiResultsSync } from "./search-api";
import { probeCommentSidebar } from "./comment-sidebar-dom";
import { probeDmButton } from "./dm-dom";
import { probeSearchVideoCard } from "./search-video-dom";
import { collectProfileVideoCards, profileFeedOpen } from "./profile-video-dom";
import { isXhsCommentReady, isXhsNotePage } from "./platforms/xiaohongshu/search-dom";
import { isKsCommentReady, isKsVideoPage } from "./platforms/kuaishou/search-dom";

export interface LabReadinessResult {
  ok: boolean;
  can_execute: boolean;
  target_action: string;
  required_context: LabPageContext;
  detected_context: LabPageContext | null;
  url: string;
  message: string;
  suggest_step?: string;
  suggest_label?: string;
  signals?: Record<string, unknown>;
}

const PREREQUISITE: Record<string, { step: string; label: string }> = {
  "plugin_lab.find_search_box": { step: "1", label: "打开浏览器" },
  "plugin_lab.input_search_text": { step: "3", label: "找到搜索框" },
  "plugin_lab.click_search_btn": { step: "6", label: "输入搜索文本" },
  "plugin_lab.click_filter_btn": { step: "7", label: "点击搜索" },
  "plugin_lab.click_filter_overlay": { step: "4", label: "点击筛选按钮" },
  "plugin_lab.fetch_search_results": { step: "7", label: "点击搜索" },
  "plugin_lab.click_search_video": { step: "8", label: "获取搜索结果" },
  "plugin_lab.search_video_probe": { step: "8", label: "获取搜索结果" },
  "plugin_lab.click_comment_btn": { step: "9", label: "点击搜索结果视频" },
  "plugin_lab.scroll_and_collect_comments": { step: "10", label: "点击评论按钮" },
  "plugin_lab.send_comment": { step: "10", label: "点击评论按钮" },
  "plugin_lab.reply_comment": { step: "11", label: "滑动抓取评论" },
  "plugin_lab.click_comment_avatar": { step: "11", label: "滑动抓取评论" },
  "plugin_lab.click_follow_btn": { step: "14", label: "点击评论用户头像" },
  "plugin_lab.click_dm_btn": { step: "15", label: "点击关注" },
  "plugin_lab.input_dm_text": { step: "16", label: "点击私信" },
  "plugin_lab.send_dm": { step: "17", label: "输入私信文本" },
  "plugin_lab.close_video_detail": { step: "9", label: "打开视频详情" },
};

function fail(
  targetAction: string,
  required: LabPageContext,
  message: string,
  signals?: Record<string, unknown>,
): LabReadinessResult {
  const prereq = PREREQUISITE[targetAction];
  return {
    ok: true,
    can_execute: false,
    target_action: targetAction,
    required_context: required,
    detected_context: detectPageContext(location.href),
    url: location.href,
    message: prereq
      ? `${message} — 请先执行步骤 ${prereq.step}「${prereq.label}」`
      : message,
    suggest_step: prereq?.step,
    suggest_label: prereq?.label,
    signals,
  };
}

function pass(targetAction: string, required: LabPageContext, signals?: Record<string, unknown>): LabReadinessResult {
  return {
    ok: true,
    can_execute: true,
    target_action: targetAction,
    required_context: required,
    detected_context: detectPageContext(location.href),
    url: location.href,
    message: "当前界面可执行",
    signals,
  };
}

function activePlatformId() {
  return getPluginLabAdapterForUrl(location.href).id;
}

function urlContextOk(required: LabPageContext): boolean {
  return contextMatchesUrl(required, location.href);
}

/** 步骤执行前：检测当前 DOM 是否满足 target_action */
export function probeLabReadiness(payload: { target_action?: string } = {}): LabReadinessResult {
  const targetAction = String(payload.target_action ?? "").trim();
  if (!targetAction) {
    return {
      ok: false,
      can_execute: false,
      target_action: "",
      required_context: "platform",
      detected_context: detectPageContext(location.href),
      url: location.href,
      message: "preflight: missing target_action",
    };
  }

  const { context: required } = contextRequirementForAction(targetAction);
  const adapter = getPluginLabAdapterForUrl(location.href);

  if (!adapter.capabilities.collect && targetAction !== "plugin_lab.preflight" && targetAction !== "plugin_lab.page_snapshot") {
    return fail(targetAction, required, `${adapter.label} 插件采集尚未实现`, {
      platform: adapter.id,
      collect_supported: false,
    });
  }

  if (!urlContextOk(required)) {
    return fail(
      targetAction,
      required,
      `当前不在${contextLabel(required)}（${location.href}）`,
      { url_context_ok: false },
    );
  }

  switch (targetAction) {
    case "plugin_lab.find_search_box":
    case "plugin_lab.input_search_text":
    case "plugin_lab.click_search_btn": {
      const match = findSearchInputMatch(activePlatformId());
      if (!match) {
        return fail(targetAction, required, "页面上未找到搜索框", { search_input: false });
      }
      return pass(targetAction, required, { search_input: true, selector: match.selector });
    }

    case "plugin_lab.click_filter_btn":
    case "plugin_lab.click_filter_overlay": {
      if (activePlatformId() !== "douyin") {
        return pass(targetAction, required, { filter_skipped: true, platform: activePlatformId() });
      }
      if (!isPlatformSearchResultsPage(activePlatformId())) {
        return fail(targetAction, required, "不在搜索结果页，无法操作筛选", { on_search_page: false });
      }
      const filter = probeFilterDom();
      if (targetAction === "plugin_lab.click_filter_overlay" && !filter.panel_open && !filter.button) {
        return fail(targetAction, required, "筛选浮层未打开且未找到筛选按钮", {
          panel_open: filter.panel_open,
          has_button: Boolean(filter.button),
        });
      }
      return pass(targetAction, required, {
        panel_open: filter.panel_open,
        has_button: Boolean(filter.button),
        option_count: filter.options?.length ?? 0,
      });
    }

    case "plugin_lab.fetch_search_results":
    case "plugin_lab.click_search_video":
    case "plugin_lab.search_video_probe": {
      const platform = activePlatformId();
      if (!isPlatformSearchResultsPage(platform)) {
        const apiItems = platform === "douyin" ? getCachedSearchApiResultsSync() : null;
        if (!apiItems?.length && countPlatformSearchCards(platform) === 0) {
          return fail(targetAction, required, "不在搜索结果页", { on_search_page: false });
        }
      }
      if (isPlatformFeedOverlayOpen(platform)) {
        return fail(targetAction, required, "当前为视频浮层，请先关闭视频详情", {
          on_search_page: true,
          feed_overlay_open: true,
        });
      }
      const apiItems = platform === "douyin" ? getCachedSearchApiResultsSync() : null;
      if (apiItems?.length) {
        return pass(targetAction, required, {
          search_card_count: apiItems.length,
          capture_method: "api",
        });
      }
      const cardCount = countPlatformSearchCards(platform);
      if (cardCount === 0) {
        if (platform === "kuaishou" && isPlatformSearchResultsPage(platform)) {
          return pass(targetAction, required, {
            on_search_page: true,
            search_card_count: 0,
            capture_method: "pending",
          });
        }
        return fail(targetAction, required, "搜索列表尚无内容卡片（可能仍在加载）", {
          on_search_page: true,
          search_card_count: 0,
        });
      }
      return pass(targetAction, required, { search_card_count: cardCount });
    }

    case "plugin_lab.swipe_page": {
      return pass(targetAction, required, {
        on_search_page: isPlatformSearchResultsPage(activePlatformId()),
        on_profile_page: detectPageContext(location.href) === "profile",
      });
    }

    case "plugin_lab.close_video_detail": {
      const sidebar = probeCommentSidebar();
      const feedOpen = Boolean(sidebar.feed_open || sidebar.sidebar_active || sidebar.has_visible_comments);
      if (!feedOpen) {
        return pass(targetAction, required, { feed_open: false, already_closed: true });
      }
      return pass(targetAction, required, {
        feed_open: sidebar.feed_open,
        comment_item_count: sidebar.comment_item_count,
      });
    }

    case "plugin_lab.fetch_profile_videos":
    case "plugin_lab.prepare_profile_video":
    case "plugin_lab.click_profile_video":
    case "plugin_lab.profile_video_probe":
    case "plugin_lab.profile_video_dom_click":
    case "plugin_lab.back_to_profile": {
      if (detectPageContext(location.href) !== "profile") {
        return fail(targetAction, required, "不在用户主页", { on_profile: false });
      }
      const cards = collectProfileVideoCards(3);
      if (
        (targetAction === "plugin_lab.prepare_profile_video"
          || targetAction === "plugin_lab.click_profile_video")
        && cards.length === 0
        && !profileFeedOpen()
      ) {
        return fail(targetAction, required, "主页作品列表尚无视频卡片", {
          on_profile: true,
          profile_card_count: 0,
        });
      }
      return pass(targetAction, required, {
        on_profile: true,
        profile_card_count: cards.length,
        profile_feed_open: profileFeedOpen(),
      });
    }

    case "plugin_lab.click_comment_btn":
    case "plugin_lab.comment_sidebar_probe":
    case "plugin_lab.activate_comment_sidebar":
    case "plugin_lab.scroll_and_collect_comments":
    case "plugin_lab.send_comment":
    case "plugin_lab.reply_comment":
    case "plugin_lab.reply_comment_probe":
    case "plugin_lab.reply_comment_hover":
    case "plugin_lab.reply_comment_input_probe":
    case "plugin_lab.reply_comment_type":
    case "plugin_lab.click_comment_avatar": {
      const platform = activePlatformId();
      const standaloneVideoProbeActions = new Set([
        "plugin_lab.click_comment_btn",
        "plugin_lab.comment_sidebar_probe",
        "plugin_lab.activate_comment_sidebar",
      ]);
      if (platform === "xiaohongshu" && isXhsNotePage()) {
        const ready = isXhsCommentReady();
        if (!ready && !standaloneVideoProbeActions.has(targetAction)) {
          return fail(targetAction, required, "小红书笔记页评论区未就绪", { is_standalone_video: true });
        }
        return pass(targetAction, required, { is_standalone_video: true, sidebar_ready: ready });
      }
      if (platform === "kuaishou" && isKsVideoPage()) {
        const ready = isKsCommentReady();
        if (!ready && !standaloneVideoProbeActions.has(targetAction)) {
          return fail(targetAction, required, "快手视频页评论区未就绪", { is_standalone_video: true });
        }
        return pass(targetAction, required, { is_standalone_video: true, sidebar_ready: ready });
      }
      const sidebar = probeCommentSidebar();
      if (sidebar.is_standalone_video) {
        const canExecute =
          standaloneVideoProbeActions.has(targetAction)
          || sidebar.sidebar_ready
          || sidebar.sidebar_active
          || (sidebar.comment_item_count ?? 0) > 0;
        if (!canExecute) {
          return fail(targetAction, required, "独立视频页未就绪", {
            is_standalone_video: true,
            icon_targets: sidebar.icon_targets?.length ?? 0,
          });
        }
        return pass(targetAction, required, {
          is_standalone_video: true,
          sidebar_ready: sidebar.sidebar_ready,
          comment_item_count: sidebar.comment_item_count,
        });
      }
      const feedOpen = Boolean(sidebar.feed_open || sidebar.sidebar_active || sidebar.has_visible_comments);
      if (!feedOpen) {
        const videoProbe = probeSearchVideoCard({ video_index: 1 });
        return fail(targetAction, required, "视频 Feed/评论区未打开", {
          feed_open: sidebar.feed_open,
          sidebar_active: sidebar.sidebar_active,
          search_video_available: videoProbe.available ?? 0,
        });
      }
      return pass(targetAction, required, {
        feed_open: sidebar.feed_open,
        comment_item_count: sidebar.comment_item_count,
      });
    }

    case "plugin_lab.click_follow_btn":
    case "plugin_lab.click_dm_btn":
    case "plugin_lab.dm_button_probe":
    case "plugin_lab.dm_input_probe":
    case "plugin_lab.input_dm_text":
    case "plugin_lab.dm_send_probe":
    case "plugin_lab.dm_send_verify":
    case "plugin_lab.send_dm": {
      const platform = activePlatformId();
      if (platform !== "douyin") {
        return fail(targetAction, required, platform === "xiaohongshu" ? "小红书不支持插件私信" : "快手不支持插件私信", {
          dm_supported: false,
          platform,
        });
      }
      if (detectPageContext(location.href) !== "profile") {
        return fail(targetAction, required, "不在用户主页", { on_profile: false });
      }
      const dm = probeDmButton();
      if (targetAction === "plugin_lab.click_dm_btn" && !dm.ok && !dm.panel_open) {
        return fail(targetAction, required, "未找到私信按钮", { dm_button: false });
      }
      return pass(targetAction, required, {
        dm_button: dm.ok,
        dm_panel_open: dm.panel_open,
      });
    }

    default:
      return pass(targetAction, required, { generic: true });
  }
}

export function probeLabPageSnapshot() {
  const platform = activePlatformId();
  const sidebar = probeCommentSidebar();
  const searchCardCount = countPlatformSearchCards(platform);
  const searchInput = findSearchInputMatch(platform);
  return {
    ok: true,
    url: location.href,
    platform,
    detected_context: detectPageContext(location.href),
    on_search_page: isPlatformSearchResultsPage(platform),
    search_card_count: searchCardCount,
    search_input: Boolean(searchInput),
    feed_open: platform === "douyin" ? sidebar.feed_open : isXhsNotePage() || isKsVideoPage(),
    comment_item_count: sidebar.comment_item_count,
  };
}
