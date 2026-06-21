import { INJECTED_MESSAGE } from "../../../shared/constants";
import type { PlatformCommentRow } from "../shared/content-item";
import { KS_COMMENT_GRAPHQL } from "./constants";

const CONFIG_CHANNEL = "huoke:injected:config";
const STORAGE_PREFIX = "huoke:ks-comment-api:";

export function isKsCommentApi(url: string, body?: unknown): boolean {
  const lower = url.toLowerCase();
  if (!lower.includes("graphql") && !lower.includes("/comment")) return false;
  if (typeof body === "string" && body.includes(KS_COMMENT_GRAPHQL)) return true;
  if (body && typeof body === "object") {
    const text = JSON.stringify(body);
    if (text.includes(KS_COMMENT_GRAPHQL)) return true;
  }
  return lower.includes("comment");
}

export function enableKsCommentNetworkHook(): void {
  window.postMessage(
    {
      channel: CONFIG_CHANNEL,
      enabled: true,
      patterns: ["/graphql", "/comment", "commentListQuery"],
    },
    "*",
  );
}

function normalizeComment(item: Record<string, unknown>, parentId?: string | null): PlatformCommentRow | null {
  const commentId = String(item.commentId ?? item.comment_id ?? item.id ?? "").trim();
  if (!commentId) return null;
  const author = (item.author ?? {}) as Record<string, unknown>;
  const userId = String(
    item.authorId ?? item.author_id ?? author.id ?? author.authorId ?? "",
  ).trim();
  let createTime = item.timestamp ?? item.create_time ?? item.createTime;
  if (typeof createTime === "number" && createTime > 1_000_000_000_000) {
    createTime = Math.floor(Number(createTime) / 1000);
  }
  return {
    comment_id: commentId,
    parent_comment_id: parentId ?? null,
    content: String(item.content ?? item.text ?? "").trim(),
    username: String(item.authorName ?? item.author_name ?? author.name ?? "").trim(),
    user_id: userId,
    sec_uid: "",
    avatar_url: String(item.headurl ?? item.avatar ?? author.headurl ?? "").trim(),
    digg_count: Number(item.likedCount ?? item.liked_count ?? 0),
    create_time: typeof createTime === "number" ? createTime : null,
    source: "api",
  };
}

export function parseKsCommentApiBody(body: unknown): PlatformCommentRow[] {
  const out: PlatformCommentRow[] = [];
  const seen = new Set<string>();

  const walk = (node: unknown) => {
    if (!node || typeof node !== "object") return;
    if (Array.isArray(node)) {
      for (const child of node) walk(child);
      return;
    }
    const record = node as Record<string, unknown>;
    if ("commentId" in record || "comment_id" in record) {
      const normalized = normalizeComment(record);
      if (normalized && !seen.has(normalized.comment_id)) {
        seen.add(normalized.comment_id);
        out.push(normalized);
      }
    }
    const roots = record.data as Record<string, unknown> | undefined;
    const vision = roots?.visionCommentList as Record<string, unknown> | undefined;
    const list = vision?.rootComments ?? record.rootComments ?? record.comments;
    if (Array.isArray(list)) {
      for (const row of list) {
        if (!row || typeof row !== "object") continue;
        const normalized = normalizeComment(row as Record<string, unknown>);
        if (!normalized || seen.has(normalized.comment_id)) continue;
        seen.add(normalized.comment_id);
        out.push(normalized);
        const subs = (row as Record<string, unknown>).subComments;
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
    }
    for (const value of Object.values(record)) walk(value);
  };

  walk(body);
  return out;
}

interface CommentCache {
  at: number;
  photoId: string;
  items: PlatformCommentRow[];
}

const caches = new Map<string, CommentCache>();

function cacheKey(photoId: string): string {
  return `${STORAGE_PREFIX}${photoId}`;
}

export async function mergeKsCommentCapture(photoId: string, parsed: PlatformCommentRow[]): Promise<void> {
  const prev = caches.get(photoId);
  const merged = new Map<string, PlatformCommentRow>();
  for (const item of prev?.items ?? []) merged.set(item.comment_id, item);
  for (const item of parsed) merged.set(item.comment_id, item);
  const items = Array.from(merged.values());
  const next = { at: Date.now(), photoId, items };
  caches.set(photoId, next);
  try {
    await chrome.storage.session.set({ [cacheKey(photoId)]: next });
  } catch {
    // ignore
  }
}

export async function ingestKsCommentApiResponse(
  url: string,
  body: unknown | null,
  photoHint?: string,
): Promise<boolean> {
  if (!isKsCommentApi(url, body ?? undefined)) return false;
  const parsed = body ? parseKsCommentApiBody(body) : [];
  const photoId =
    photoHint ||
    (() => {
      const match = location.pathname.match(/\/short-video\/([0-9a-zA-Z]{8,32})/);
      return match?.[1] ?? "";
    })();
  if (!photoId) return parsed.length > 0;
  await mergeKsCommentCapture(photoId, parsed);
  return parsed.length > 0;
}

export async function getKsCommentApiItems(photoId: string, maxAgeMs = 120_000): Promise<PlatformCommentRow[]> {
  const mem = caches.get(photoId);
  if (mem && Date.now() - mem.at <= maxAgeMs) return mem.items;
  try {
    const stored = await chrome.storage.session.get(cacheKey(photoId));
    const value = stored[cacheKey(photoId)] as CommentCache | undefined;
    if (value && Date.now() - value.at <= maxAgeMs) {
      caches.set(photoId, value);
      return value.items;
    }
  } catch {
    // ignore
  }
  return [];
}

let bridgeReady = false;

export function initKsCommentApiBridge(): void {
  if (bridgeReady || typeof window === "undefined") return;
  bridgeReady = true;
  window.addEventListener("message", (event) => {
    if (event.source !== window || event.data?.channel !== INJECTED_MESSAGE) return;
    const payload = event.data.payload ?? {};
    void ingestKsCommentApiResponse(payload.url ?? "", payload.body ?? null);
  });
}
