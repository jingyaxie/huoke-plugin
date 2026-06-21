import {
  contextLabel,
  contextRequirementForAction,
  detectPageContext,
  type LabPageContext,
} from "./lab-context";
import { probeFilterDom } from "./filter-dom";
import { findSearchInputMatch } from "./search-input";
import { collectSearchResultCards, isFeedOverlayOpen, isSearchResultsPage } from "./search-results-dom";
import { getCachedSearchApiResultsSync } from "./search-api";
import { probeCommentSidebar } from "./comment-sidebar-dom";
import { probeDmButton } from "./dm-dom";
import { probeSearchVideoCard } from "./search-video-dom";

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

function urlContextOk(required: LabPageContext): boolean {
  const detected = detectPageContext(location.href);
  if (!detected) return false;
  if (required === "platform") return true;
  if (required === "search") return detected === "search" || detected === "video";
  if (required === "video") return detected === "video" || detected === "search";
  if (required === "profile") return detected === "profile";
  return false;
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
      const match = findSearchInputMatch("douyin");
      if (!match) {
        return fail(targetAction, required, "页面上未找到搜索框", { search_input: false });
      }
      return pass(targetAction, required, { search_input: true, selector: match.selector });
    }

    case "plugin_lab.click_filter_btn":
    case "plugin_lab.click_filter_overlay": {
      if (!isSearchResultsPage()) {
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
      if (!isSearchResultsPage()) {
        const apiItems = getCachedSearchApiResultsSync();
        if (!apiItems?.length) {
          return fail(targetAction, required, "不在搜索结果页", { on_search_page: false });
        }
      }
      if (isFeedOverlayOpen()) {
        return fail(targetAction, required, "当前为视频浮层，请先关闭视频详情", {
          on_search_page: true,
          feed_overlay_open: true,
        });
      }
      const apiItems = getCachedSearchApiResultsSync();
      if (apiItems?.length) {
        return pass(targetAction, required, {
          search_card_count: apiItems.length,
          capture_method: "api",
        });
      }
      const cards = collectSearchResultCards();
      if (cards.length === 0) {
        return fail(targetAction, required, "搜索列表尚无视频卡片（可能仍在加载）", {
          on_search_page: true,
          search_card_count: 0,
        });
      }
      return pass(targetAction, required, { search_card_count: cards.length });
    }

    case "plugin_lab.swipe_page": {
      return pass(targetAction, required, { on_search_page: isSearchResultsPage() });
    }

    case "plugin_lab.click_comment_btn":
    case "plugin_lab.comment_sidebar_probe":
    case "plugin_lab.scroll_and_collect_comments":
    case "plugin_lab.send_comment":
    case "plugin_lab.reply_comment":
    case "plugin_lab.reply_comment_probe":
    case "plugin_lab.reply_comment_hover":
    case "plugin_lab.reply_comment_input_probe":
    case "plugin_lab.reply_comment_type":
    case "plugin_lab.close_video_detail":
    case "plugin_lab.click_comment_avatar": {
      const sidebar = probeCommentSidebar();
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
  const sidebar = probeCommentSidebar();
  const cards = collectSearchResultCards();
  const searchInput = findSearchInputMatch("douyin");
  return {
    ok: true,
    url: location.href,
    detected_context: detectPageContext(location.href),
    on_search_page: isSearchResultsPage(),
    search_card_count: cards.length,
    search_input: Boolean(searchInput),
    feed_open: sidebar.feed_open,
    comment_item_count: sidebar.comment_item_count,
  };
}
