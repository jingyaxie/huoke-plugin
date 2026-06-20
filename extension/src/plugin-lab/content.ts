import { clickFilterButton } from "./click-filter-btn";
import { clickFilterOverlay, type ClickFilterOverlayPayload } from "./click-filter-overlay";
import { isPluginLabBackgroundAction } from "./background-actions";
import { clickCommentAvatar, type ClickCommentAvatarPayload } from "./click-comment-avatar";
import {
  clickCommentButtonFallback,
  probeCommentSidebar,
} from "./comment-sidebar-dom";
import { clickDmButton } from "./click-dm-btn";
import { probeDmButton, probeDmInput, probeDmSendButton, probeDmSendVerify, typeDmTextFallback } from "./dm-dom";
import { clickFollowButton } from "./click-follow-btn";
import { clickSearchButton } from "./click-search-btn";
import {
  clickSearchVideoFallback,
  probeSearchVideoCard,
} from "./search-video-dom";
import { closeVideoDetail } from "./close-video-detail";
import { findFilterOptionPoint, probeFilterDom } from "./filter-dom";
import { fetchSearchResults, type FetchSearchResultsPayload } from "./fetch-search-results";
import { findAndFocusSearchBox } from "./find-search-box";
import { inputSearchText, type InputSearchTextPayload } from "./input-search-text";
import {
  probeReplyCommentTargets,
  probeReplyInput,
  typeReplyCommentText,
} from "./reply-comment-dom";
import { scrollAndCollectComments, type ScrollCollectCommentsPayload } from "./scroll-collect-comments";
import { sendComment } from "./send-comment";
import { sendDm } from "./send-dm";
import { swipePage, type SwipePagePayload } from "./swipe-page";

export async function dispatchPluginLabCommand(action: string, payload: unknown): Promise<unknown> {
  switch (action) {
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
      return clickSearchButton();
    case "plugin_lab.fetch_search_results":
      return fetchSearchResults((payload ?? {}) as FetchSearchResultsPayload);
    case "plugin_lab.click_search_video":
      return clickSearchVideoFallback((payload ?? {}) as { video_index?: number; index?: number });
    case "plugin_lab.search_video_probe":
      return probeSearchVideoCard((payload ?? {}) as { video_index?: number; index?: number });
    case "plugin_lab.click_comment_btn":
      return clickCommentButtonFallback();
    case "plugin_lab.comment_sidebar_probe":
      return probeCommentSidebar();
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
    case "plugin_lab.close_video_detail":
      return closeVideoDetail();
    case "plugin_lab.filter_probe":
      return probeFilterDom();
    case "plugin_lab.filter_find_option":
      return findFilterOptionPoint(String((payload as { label?: string })?.label ?? ""));
    case "plugin_lab.reply_comment_probe":
      return probeReplyCommentTargets((payload ?? {}) as { comment_index?: number; index?: number });
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
