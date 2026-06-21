import { INJECTED_MESSAGE } from "../../../shared/constants";
import type { PlatformCommentRow } from "../shared/content-item";
import { XHS_COMMENT_PAGE_MARKERS } from "./constants";

const CONFIG_CHANNEL = "huoke:injected:config";
const STORAGE_PREFIX = "huoke:xhs-comment-api:";

export function isXhsCommentApi(url: string): boolean {
  const lower = url.toLowerCase();
  return XHS_COMMENT_PAGE_MARKERS.some((m) => lower.includes(m));
}

export function enableXhsCommentNetworkHook(): void {
  window.postMessage(
    {
      channel: CONFIG_CHANNEL,
      enabled: true,
      patterns: ["/api/sns/web/", "edith.xiaohongshu.com", "/comment/"],
    },
    "*",
  );
}

function normalizeComment(item: Record<string, unknown>, parentId?: string | null): PlatformCommentRow | null {
  const commentId = String(item.id ?? item.comment_id ?? item.commentId ?? "").trim();
  if (!commentId) return null;
  const user = (item.user_info ?? item.user ?? item.author ?? {}) as Record<string, unknown>;
  const content = String(item.content ?? item.text ?? item.note ?? "").trim();
  let createTime = item.create_time ?? item.createTime ?? item.time;
  if (typeof createTime === "number" && createTime > 1_000_000_000_000) {
    createTime = Math.floor(Number(createTime) / 1000);
  }
  return {
    comment_id: commentId,
    parent_comment_id: parentId ?? null,
    content,
    username: String(user.nickname ?? user.nick_name ?? user.name ?? "").trim(),
    user_id: String(user.user_id ?? user.userId ?? user.id ?? "").trim(),
    sec_uid: "",
    avatar_url: String(user.image ?? user.avatar ?? "").trim(),
    digg_count: Number(item.like_count ?? item.liked_count ?? item.likeCount ?? 0),
    create_time: typeof createTime === "number" ? createTime : null,
    source: "api",
  };
}

export function parseXhsCommentApiBody(body: unknown): PlatformCommentRow[] {
  const out: PlatformCommentRow[] = [];
  const seen = new Set<string>();
  const data = body as Record<string, unknown> | null;
  const comments = (data?.data as Record<string, unknown> | undefined)?.comments ?? data?.comments;
  const list = Array.isArray(comments) ? comments : [];
  for (const row of list) {
    if (!row || typeof row !== "object") continue;
    const record = row as Record<string, unknown>;
    const normalized = normalizeComment(record);
    if (!normalized || seen.has(normalized.comment_id)) continue;
    seen.add(normalized.comment_id);
    out.push(normalized);
    const subs = record.sub_comments ?? record.subComments;
    if (Array.isArray(subs)) {
      for (const sub of subs) {
        if (!sub || typeof sub !== "object") continue;
        const child = normalizeComment(sub as Record<string, unknown>, normalized.comment_id);
        if (child && !seen.has(child.comment_id)) {
          seen.add(child.comment_id);
          out.push(child);
        }
      }
    }
  }
  return out;
}

interface CommentCache {
  at: number;
  noteId: string;
  items: PlatformCommentRow[];
}

const caches = new Map<string, CommentCache>();

function cacheKey(noteId: string): string {
  return `${STORAGE_PREFIX}${noteId}`;
}

export async function mergeXhsCommentCapture(noteId: string, parsed: PlatformCommentRow[]): Promise<void> {
  const prev = caches.get(noteId);
  const merged = new Map<string, PlatformCommentRow>();
  for (const item of prev?.items ?? []) merged.set(item.comment_id, item);
  for (const item of parsed) merged.set(item.comment_id, item);
  const items = Array.from(merged.values());
  const next = { at: Date.now(), noteId, items };
  caches.set(noteId, next);
  try {
    await chrome.storage.session.set({ [cacheKey(noteId)]: next });
  } catch {
    // ignore
  }
}

export async function ingestXhsCommentApiResponse(
  url: string,
  body: unknown | null,
  noteHint?: string,
): Promise<boolean> {
  if (!isXhsCommentApi(url)) return false;
  const parsed = body ? parseXhsCommentApiBody(body) : [];
  const noteId =
    noteHint ||
    (() => {
      try {
        const match = location.pathname.match(/\/explore\/([0-9a-fA-F]{16,32})/);
        return match?.[1] ?? "";
      } catch {
        return "";
      }
    })();
  if (!noteId) return parsed.length > 0;
  await mergeXhsCommentCapture(noteId, parsed);
  return parsed.length > 0;
}

export async function getXhsCommentApiItems(noteId: string, maxAgeMs = 120_000): Promise<PlatformCommentRow[]> {
  const mem = caches.get(noteId);
  if (mem && Date.now() - mem.at <= maxAgeMs) return mem.items;
  try {
    const stored = await chrome.storage.session.get(cacheKey(noteId));
    const value = stored[cacheKey(noteId)] as CommentCache | undefined;
    if (value && Date.now() - value.at <= maxAgeMs) {
      caches.set(noteId, value);
      return value.items;
    }
  } catch {
    // ignore
  }
  return [];
}

let bridgeReady = false;

export function initXhsCommentApiBridge(): void {
  if (bridgeReady || typeof window === "undefined") return;
  bridgeReady = true;
  window.addEventListener("message", (event) => {
    if (event.source !== window || event.data?.channel !== INJECTED_MESSAGE) return;
    const payload = event.data.payload ?? {};
    void ingestXhsCommentApiResponse(payload.url ?? "", payload.body ?? null);
  });
}
