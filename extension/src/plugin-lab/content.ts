import { detectPlatformFromUrl } from "./platform-hosts";
import { dispatchKuaishouLabCommand } from "./platforms/kuaishou/lab";
import { dispatchXiaohongshuLabCommand } from "./platforms/xiaohongshu/lab";
import { probeLabReadiness, probeLabPageSnapshot } from "./lab-readiness";
import { clickFilterButton } from "./click-filter-btn";
import { clickFilterOverlay, type ClickFilterOverlayPayload } from "./click-filter-overlay";
import { isPluginLabBackgroundAction } from "./background-actions";
import { clickCommentAvatar, type ClickCommentAvatarPayload } from "./click-comment-avatar";
import {
  clickCommentButtonFallback,
  probeCommentSidebar,
  activateCommentSidebar,
} from "./comment-sidebar-dom";
import { clickDmButton } from "./click-dm-btn";
import { probeDmButton, probeDmInput, probeDmSendButton, probeDmSendVerify, typeDmTextFallback } from "./dm-dom";
import { clickFollowButton } from "./click-follow-btn";
import { clickSearchButton, prepareSearchCapture, submitSearchClick } from "./click-search-btn";
import {
  clickSearchVideoFallback,
  clickSearchVideoInContent,
  prepareSearchForVideoClick,
  probeSearchVideoCard,
} from "./search-video-dom";
import {
  backToProfileList,
  clickProfileVideoAtIndex,
  prepareProfileForVideoClick,
  probeProfileVideoCard,
} from "./profile-video-dom";
import { fetchProfileVideos } from "./fetch-profile-videos";
import { closeVideoDetail } from "./close-video-detail";
import { findFilterOptionPoint, probeFilterDom } from "./filter-dom";
import { fetchSearchResults, type FetchSearchResultsPayload } from "./fetch-search-results";
import { ensureSearchMultiColumnLayout } from "./search-layout";
import { findAndFocusSearchBox } from "./find-search-box";
import { inputSearchText, type InputSearchTextPayload } from "./input-search-text";
import {
  hoverReplyCommentTarget,
  probeReplyCommentTargets,
  probeReplyInput,
  typeReplyCommentText,
} from "./reply-comment-dom";
import { type ResolveCommentPayload } from "./resolve-comment-item";
import { scrollAndCollectComments, type ScrollCollectCommentsPayload } from "./scroll-collect-comments";
import { sendComment } from "./send-comment";
import { sendDm } from "./send-dm";
import { swipePage, type SwipePagePayload } from "./swipe-page";
import {
  swipeSearchFeedNext,
  prepareFeedForSwipe,
  recoverDouyinFeedFromAweme,
  probeDouyinFeed,
} from "./search-feed-next";
import { probeSearchContextDom } from "./search-context-probe";

/**
 * 小红书/快手先走平台 lab；未覆盖的步骤回落到下方共享 switch（抖音主实现 + 通用搜索输入）。
 * 对接小红书时抖音正常，靠的就是这个 fallback，不能改成「纯平台路由、无兜底」。
 */
export async function dispatchPluginLabCommand(action: string, payload: unknown): Promise<unknown> {
  const platform = detectPlatformFromUrl(location.href);
  if (platform === "xiaohongshu") {
    const routed = await dispatchXiaohongshuLabCommand(action, payload);
    if (routed !== undefined) return routed;
  }
  if (platform === "kuaishou") {
    const routed = await dispatchKuaishouLabCommand(action, payload);
    if (routed !== undefined) return routed;
  }

  switch (action) {
    case "plugin_lab.preflight":
      return probeLabReadiness((payload ?? {}) as { target_action?: string });
    case "plugin_lab.page_snapshot":
      return probeLabPageSnapshot();
    case "plugin_lab.search_context_dom_probe":
      return probeSearchContextDom();
    case "plugin_lab.swipe_page":
      return swipePage((payload ?? {}) as SwipePagePayload);
    case "plugin_lab.find_search_box":
      return findAndFocusSearchBox((payload ?? {}) as Record<string, unknown>);
    case "plugin_lab.input_search_text":
      return inputSearchText((payload ?? {}) as InputSearchTextPayload);
    case "plugin_lab.click_filter_btn":
      return clickFilterButton();
    case "plugin_lab.click_filter_overlay":
      return clickFilterOverlay((payload ?? {}) as ClickFilterOverlayPayload);
    case "plugin_lab.click_search_btn":
      return clickSearchButton((payload ?? {}) as Parameters<typeof clickSearchButton>[0]);
    case "plugin_lab.search_prepare":
      return prepareSearchCapture();
    case "plugin_lab.search_submit":
      return submitSearchClick((payload ?? {}) as Parameters<typeof submitSearchClick>[0]);
    case "plugin_lab.fetch_search_results":
      return fetchSearchResults((payload ?? {}) as FetchSearchResultsPayload);
    case "plugin_lab.ensure_search_multi_column":
      return ensureSearchMultiColumnLayout();
    case "plugin_lab.prepare_search_video":
      return prepareSearchForVideoClick((payload ?? {}) as { skip_restore?: boolean });
    case "plugin_lab.swipe_search_feed_next":
      return swipeSearchFeedNext();
    case "plugin_lab.prepare_feed_for_swipe":
      return prepareFeedForSwipe();
    case "plugin_lab.recover_search_feed":
      return recoverDouyinFeedFromAweme(
        String((payload as { aweme_id?: string })?.aweme_id ?? ""),
      );
    case "plugin_lab.probe_douyin_feed":
      return probeDouyinFeed();
    case "plugin_lab.search_video_dom_click":
      return clickSearchVideoInContent((payload ?? {}) as {
        video_index?: number;
        index?: number;
        aweme_id?: string;
        aweme_hint?: string;
        strategy?: "modal_only" | "full";
      });
    case "plugin_lab.click_search_video":
      return clickSearchVideoFallback((payload ?? {}) as { video_index?: number; index?: number });
    case "plugin_lab.search_video_probe":
      return probeSearchVideoCard((payload ?? {}) as { video_index?: number; index?: number });
    case "plugin_lab.comment_sidebar_probe":
      return probeCommentSidebar((payload ?? {}) as Record<string, unknown>);
    case "plugin_lab.activate_comment_sidebar":
      return activateCommentSidebar((payload ?? {}) as Record<string, unknown>);
    case "plugin_lab.click_comment_btn":
      return clickCommentButtonFallback((payload ?? {}) as Record<string, unknown>);
    case "plugin_lab.scroll_and_collect_comments":
      return scrollAndCollectComments((payload ?? {}) as ScrollCollectCommentsPayload);
    case "plugin_lab.send_comment":
      return sendComment();
    case "plugin_lab.click_comment_avatar":
      return clickCommentAvatar((payload ?? {}) as ClickCommentAvatarPayload);
    case "plugin_lab.click_follow_btn":
      return clickFollowButton();
    case "plugin_lab.click_dm_btn":
      return clickDmButton();
    case "plugin_lab.dm_button_probe":
      return probeDmButton();
    case "plugin_lab.dm_input_probe":
      return probeDmInput();
    case "plugin_lab.input_dm_text":
      return typeDmTextFallback((payload ?? {}) as { dm_text?: string; text?: string });
    case "plugin_lab.dm_send_probe":
      return probeDmSendButton();
    case "plugin_lab.dm_send_verify":
      return probeDmSendVerify((payload ?? {}) as { dm_text?: string; text?: string });
    case "plugin_lab.send_dm":
      return sendDm();
    case "plugin_lab.fetch_profile_videos":
      return fetchProfileVideos((payload ?? {}) as { limit?: number });
    case "plugin_lab.prepare_profile_video":
      return prepareProfileForVideoClick((payload ?? {}) as { fresh_profile?: boolean });
    case "plugin_lab.profile_video_dom_click":
      return clickProfileVideoAtIndex((payload ?? {}) as {
        video_index?: number;
        index?: number;
        aweme_id?: string;
        aweme_hint?: string;
      });
    case "plugin_lab.click_profile_video":
      return clickProfileVideoAtIndex((payload ?? {}) as { video_index?: number; index?: number });
    case "plugin_lab.profile_video_probe":
      return probeProfileVideoCard((payload ?? {}) as {
        video_index?: number;
        index?: number;
        status_only?: boolean;
        aweme_id?: string;
      });
    case "plugin_lab.back_to_profile":
      return backToProfileList(String((payload as { profile_url?: string })?.profile_url ?? ""));
    case "plugin_lab.close_video_detail":
      return closeVideoDetail();
    case "plugin_lab.filter_probe":
      return probeFilterDom();
    case "plugin_lab.filter_find_option":
      return findFilterOptionPoint(String((payload as { label?: string })?.label ?? ""));
    case "plugin_lab.reply_comment_probe":
      return probeReplyCommentTargets((payload ?? {}) as ResolveCommentPayload);
    case "plugin_lab.reply_comment_hover":
      return hoverReplyCommentTarget((payload ?? {}) as ResolveCommentPayload);
    case "plugin_lab.reply_comment_input_probe":
      return probeReplyInput();
    case "plugin_lab.reply_comment_type":
      return typeReplyCommentText((payload ?? {}) as { reply_text?: string; text?: string });
    default:
      throw new Error(`unsupported plugin_lab content action: ${action}`);
  }
}

export function isPluginLabContentAction(action: string): boolean {
  return action.startsWith("plugin_lab.") && !isPluginLabBackgroundAction(action);
}
