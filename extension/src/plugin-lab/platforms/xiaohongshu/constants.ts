export const XHS_SEARCH_API_MARKERS = ["/api/sns/web/v1/search/notes", "/search/notes"] as const;
export const XHS_SEARCH_API_EXCLUDES = ["login", "qrcode", "suggest", "recommend"] as const;
export const XHS_COMMENT_PAGE_MARKERS = ["/api/sns/web/v2/comment/page", "/comment/page"] as const;
export const XHS_PROFILE_POST_MARKERS = ["/api/sns/web/v1/user_posted", "/user_posted"] as const;

export const NOTE_ID_RE = /[0-9a-fA-F]{16,32}/;

export const NOTE_LINK_SELECTORS = [
  'a[href*="/explore/"]',
  'a[href*="/discovery/item/"]',
  'section.note-item a',
] as const;

export const NOTE_DETAIL_MARKERS = [
  "#detail-title",
  ".note-detail",
  ".interaction-container",
  ".comments-el",
  "#noteContainer",
  ".note-scroller",
] as const;
