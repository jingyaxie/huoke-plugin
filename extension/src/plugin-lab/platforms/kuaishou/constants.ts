export const KS_SEARCH_API_MARKERS = ["/rest/v/search/feed", "/search/feed"] as const;
export const KS_COMMENT_GRAPHQL = "commentListQuery" as const;

export const PHOTO_ID_RE = /^[0-9a-zA-Z]{8,32}$/;

export const VIDEO_LINK_SELECTORS = [
  'a[href*="/short-video/"]',
  'a[href*="/fw/photo/"]',
  '[class*="video-card"] a',
] as const;

export const VIDEO_DETAIL_MARKERS = [
  ".video-info",
  ".player-container",
  '[class*="comment"]',
  ".short-video-info",
] as const;
