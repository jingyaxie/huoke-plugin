import { resolveEffectivePlaybackMode } from "./playback-mode";
import {
  activateFeedCommentSidebar,
  clickFeedCommentButtonFallback,
  collectFeedCommentIconTargets,
  isFeedCommentSidebarActive,
  isFeedCommentSidebarReadyForCollect,
  isFeedOverlayOpen,
  probeFeedCommentSidebar,
} from "./feed-comment-sidebar-dom";
import {
  activateVideoDetailCommentSidebar,
  clickVideoDetailCommentButtonFallback,
  collectVideoDetailCommentIconTargets,
  isDouyinVideoDetailSidePanel,
  isVideoDetailCommentSidebarActive,
  isVideoDetailCommentSidebarReadyForCollect,
  probeVideoDetailCommentSidebar,
} from "./video-detail-comment-sidebar-dom";

export type { DomPoint, DomRect, IconTarget } from "./comment-sidebar-shared";
export {
  countVisibleCommentItems,
  dismissTransientOverlay,
  hasVisibleCommentItems,
} from "./comment-sidebar-shared";
export { isFeedOverlayOpen } from "./feed-comment-sidebar-dom";
export { isDouyinVideoDetailSidePanel } from "./video-detail-comment-sidebar-dom";

function modeFromPayload(payload: Record<string, unknown> = {}) {
  return resolveEffectivePlaybackMode(payload);
}

/** @deprecated 请按 playback_mode 使用 feed / video_detail 专用 API */
export function isCommentSidebarActive(payload: Record<string, unknown> = {}): boolean {
  return modeFromPayload(payload) === "video_detail"
    ? isVideoDetailCommentSidebarActive()
    : isFeedCommentSidebarActive();
}

/** @deprecated 请按 playback_mode 使用 feed / video_detail 专用 API */
export function isCommentSidebarReadyForCollect(payload: Record<string, unknown> = {}): boolean {
  return modeFromPayload(payload) === "video_detail"
    ? isVideoDetailCommentSidebarReadyForCollect()
    : isFeedCommentSidebarReadyForCollect();
}

export function collectCommentIconTargets(payload: Record<string, unknown> = {}) {
  return modeFromPayload(payload) === "video_detail"
    ? collectVideoDetailCommentIconTargets()
    : collectFeedCommentIconTargets();
}

export function probeCommentSidebar(payload: Record<string, unknown> = {}) {
  return modeFromPayload(payload) === "video_detail"
    ? probeVideoDetailCommentSidebar()
    : probeFeedCommentSidebar();
}

export async function activateCommentSidebar(
  payload: Record<string, unknown> = {},
  maxAttempts = 5,
) {
  return modeFromPayload(payload) === "video_detail"
    ? activateVideoDetailCommentSidebar(maxAttempts)
    : activateFeedCommentSidebar(maxAttempts);
}

export async function clickCommentButtonFallback(payload: Record<string, unknown> = {}) {
  return modeFromPayload(payload) === "video_detail"
    ? clickVideoDetailCommentButtonFallback()
    : clickFeedCommentButtonFallback();
}
