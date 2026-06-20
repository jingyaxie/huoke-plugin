import http from "./http";
import { executeSkill } from "./skills";

const LIST_TIMEOUT = 15000;

export function fetchContentList(platform, { offset = 0, limit = 50, updatedAfter, updatedBefore } = {}) {
  const params = { offset, limit };
  if (updatedAfter) params.updated_after = updatedAfter;
  if (updatedBefore) params.updated_before = updatedBefore;
  return http.get(`/platforms/${platform}/contents`, { params, timeout: LIST_TIMEOUT });
}

export function fetchContentDetail(platform, contentId, { maxComments } = {}) {
  const params = {};
  if (maxComments != null) params.max_comments = maxComments;
  return http.get(`/platforms/${platform}/contents/${encodeURIComponent(contentId)}`, {
    params,
    timeout: LIST_TIMEOUT,
  });
}

/** 回复指定评论（暖场浏览评论区 + 拦截 API 替换目标 comment_id，不必在页面定位该评论） */
export function replyComment(platform, params) {
  const contentUrl = params.content_url || params.video_url || params.note_url || "";
  const useWarmPublish = platform === "xiaohongshu" || platform === "douyin";
  return executeSkill({
    skill_id: "reply-comment",
    platform,
    params: {
      comment_id: params.comment_id,
      reply_text: params.reply_text,
      content_id: params.content_id,
      content_url: contentUrl,
      video_url: params.video_url || (platform !== "xiaohongshu" ? contentUrl : undefined),
      note_url: params.note_url || (platform === "xiaohongshu" ? contentUrl : undefined),
      comment_text: params.comment_text,
      photo_author_id: params.photo_author_id,
      reply_to_user_id: params.reply_to_user_id,
      show_browser: Boolean(params.show_browser),
      warm_publish: params.warm_publish ?? useWarmPublish,
    },
    timeout_seconds: 120,
  });
}
