export const KS_SEARCH_API_MARKERS = ["/rest/v/search/feed", "/search/feed"] as const;
export const KS_COMMENT_GRAPHQL = "commentListQuery" as const;

export const KS_COMMENT_LIST_QUERY = `query commentListQuery($photoId: String, $pcursor: String) {
  visionCommentList(photoId: $photoId, pcursor: $pcursor) {
    commentCount
    pcursor
    rootCommentsV2 {
      commentId
      authorId
      authorName
      content
      headurl
      timestamp
      likedCount
    }
  }
}` as const;

export const PHOTO_ID_RE = /^[0-9a-zA-Z]{8,32}$/;

export const VIDEO_LINK_SELECTORS = [
  'a[href*="/short-video/"]',
  'a[href*="/fw/photo/"]',
  '[class*="video-card"] a',
  '[class*="VideoCard"] a',
  '[class*="search"] a[href*="/short-video/"]',
  '[class*="Search"] a[href*="/short-video/"]',
] as const;

export const VIDEO_DETAIL_MARKERS = [
  ".video-info",
  ".player-container",
  '[class*="comment"]',
  ".short-video-info",
] as const;
