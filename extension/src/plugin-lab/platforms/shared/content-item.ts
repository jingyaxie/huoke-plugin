/** 跨平台统一内容项字段（local-service 仍使用 aweme_id 列存 content_id） */
export interface PlatformSearchItem {
  index: number;
  title: string;
  author: string;
  url: string;
  aweme_id: string;
  source: "api" | "dom";
  click_by: "aweme_id" | "dom_rect";
  rect?: { top: number; left: number; width: number; height: number };
  xsec_token?: string;
  xsec_source?: string;
  raw_json?: Record<string, unknown>;
}

export interface PlatformCommentRow {
  comment_id: string;
  parent_comment_id?: string | null;
  content: string;
  username: string;
  user_id: string;
  sec_uid?: string;
  avatar_url?: string;
  digg_count?: number;
  create_time?: number | null;
  source?: "api" | "dom";
}

export function buildSearchResultPayload(
  items: ReadonlyArray<PlatformSearchItem>,
  captureMethod: "api" | "dom" | "none",
) {
  return {
    count: items.length,
    items,
    results: items,
    capture_method: captureMethod,
    search_aweme_ids: items.map((item) => item.aweme_id).filter(Boolean),
  };
}
