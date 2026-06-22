import { resolveEffectivePlaybackMode } from "./playback-mode";
import { clickFeedCommentButtonBackground } from "./feed-comment-sidebar-background";
import { clickVideoDetailCommentButtonBackground } from "./video-detail-comment-sidebar-background";

/** 步骤 10：按 playback_mode 分发到 Feed 浮层或 /video/ 详情页实现 */
export async function clickCommentButtonBackground(payload: Record<string, unknown> = {}) {
  const mode = resolveEffectivePlaybackMode(payload);
  if (mode === "video_detail") {
    return clickVideoDetailCommentButtonBackground(payload);
  }
  return clickFeedCommentButtonBackground(payload);
}
