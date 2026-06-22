import { isStandaloneVideoPage } from "./search-feed-open";

/** 抖音两种播放界面：搜索/主页 Feed 浮层 vs /video/ 独立详情页 */
export type PlaybackMode = "feed" | "video_detail" | "auto";

export function resolvePlaybackMode(payload: Record<string, unknown> = {}): PlaybackMode {
  const raw = String(payload.playback_mode ?? "").trim().toLowerCase();
  if (raw === "feed" || raw === "video_detail") return raw;
  return "auto";
}

export function detectPlaybackMode(): "feed" | "video_detail" {
  return isStandaloneVideoPage() ? "video_detail" : "feed";
}

export function resolveEffectivePlaybackMode(
  payload: Record<string, unknown> = {},
): "feed" | "video_detail" {
  const mode = resolvePlaybackMode(payload);
  return mode === "auto" ? detectPlaybackMode() : mode;
}
