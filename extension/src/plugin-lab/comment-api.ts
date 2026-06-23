const INJECTED_CHANNEL = "huoke:injected";
const CONFIG_CHANNEL = "huoke:injected:config";

export const COMMENT_API_STORAGE_KEY = "huoke:comment-api-cache";

const COMMENT_API_MARKERS = ["/comment/list", "aweme/v1/web/comment/list"] as const;

export interface CommentApiItem {
  comment_id: string;
  content: string;
  author: string;
  user_id: string;
  sec_uid: string;
  avatar_url: string;
  digg_count: number;
  create_time: number | null;
  aweme_id: string;
}

export interface CommentCaptureCache {
  at: number;
  byAweme: Record<string, CommentApiItem[]>;
  eventsSeen: number;
  lastApiUrl?: string;
}

let lastCommentCapture: CommentCaptureCache | null = null;
let bridgeReady = false;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function isCommentListApi(url: string): boolean {
  const lower = String(url || "").toLowerCase();
  return COMMENT_API_MARKERS.some((marker) => lower.includes(marker));
}

/** 确保 injected network hook 截获评论 list API */
export function enableCommentNetworkHook(): void {
  if (typeof window === "undefined") return;
  window.postMessage(
    {
      channel: CONFIG_CHANNEL,
      enabled: true,
      patterns: [/\/comment\/list/i, /aweme\/v1\/web\/comment/i],
    },
    "*",
  );
}

function pickString(record: Record<string, unknown>, keys: string[]): string {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "string" && value.trim()) return value.trim();
    if (typeof value === "number" && Number.isFinite(value)) return String(value);
  }
  return "";
}

function pickAvatarUrl(user: Record<string, unknown>): string {
  for (const key of ["avatar_thumb", "avatar_medium", "avatar_larger"]) {
    const avatar = user[key];
    if (typeof avatar === "string" && avatar.trim().startsWith("http")) {
      return avatar.trim();
    }
    if (!avatar || typeof avatar !== "object" || Array.isArray(avatar)) continue;
    const list = (avatar as Record<string, unknown>).url_list;
    if (Array.isArray(list) && typeof list[0] === "string" && list[0].startsWith("http")) {
      return list[0];
    }
  }
  return "";
}

function normalizeCommentNode(
  node: Record<string, unknown>,
  awemeId: string,
): CommentApiItem | null {
  const commentId = pickString(node, ["cid", "comment_id"]);
  const content = pickString(node, ["text", "content"]);
  if (!commentId || !content) return null;

  const user =
    node.user && typeof node.user === "object" && !Array.isArray(node.user)
      ? (node.user as Record<string, unknown>)
      : {};

  return {
    comment_id: commentId,
    content,
    author: pickString(user, ["nickname", "name"]) || "—",
    user_id: pickString(user, ["uid", "user_id"]),
    sec_uid: pickString(user, ["sec_uid"]),
    avatar_url: pickAvatarUrl(user),
    digg_count: Number(node.digg_count ?? 0) || 0,
    create_time:
      typeof node.create_time === "number" && node.create_time > 0
        ? node.create_time
        : null,
    aweme_id: awemeId,
  };
}

export function parseCommentApiBody(body: unknown, fallbackAwemeId = ""): CommentApiItem[] {
  if (!body || typeof body !== "object") return [];
  const record = body as Record<string, unknown>;
  const awemeId =
    pickString(record, ["aweme_id"]) ||
    fallbackAwemeId ||
    extractAwemeIdFromUrl(String(record.url ?? ""));

  const list = record.comments;
  if (!Array.isArray(list)) return [];

  const items: CommentApiItem[] = [];
  const seen = new Set<string>();
  for (const row of list) {
    if (!row || typeof row !== "object") continue;
    const normalized = normalizeCommentNode(row as Record<string, unknown>, awemeId);
    if (!normalized || seen.has(normalized.comment_id)) continue;
    seen.add(normalized.comment_id);
    items.push(normalized);
    const replies = (row as Record<string, unknown>).reply_comment;
    if (!Array.isArray(replies)) continue;
    for (const reply of replies) {
      if (!reply || typeof reply !== "object") continue;
      const replyRow = normalizeCommentNode(reply as Record<string, unknown>, awemeId);
      if (!replyRow || seen.has(replyRow.comment_id)) continue;
      seen.add(replyRow.comment_id);
      items.push(replyRow);
    }
  }
  return items;
}

function extractAwemeIdFromUrl(url: string): string {
  const modal = url.match(/[?&]aweme_id=(\d{8,22})/i)?.[1];
  if (modal) return modal;
  const modalId = url.match(/[?&]modal_id=(\d{8,22})/i)?.[1];
  if (modalId) return modalId;
  const video = url.match(/\/video\/(\d{8,22})/i)?.[1];
  return video ?? "";
}

async function readCacheFromStorage(): Promise<CommentCaptureCache | null> {
  try {
    const stored = await chrome.storage.session.get(COMMENT_API_STORAGE_KEY);
    return (stored[COMMENT_API_STORAGE_KEY] as CommentCaptureCache | undefined) ?? null;
  } catch {
    return null;
  }
}

async function writeCacheToStorage(cache: CommentCaptureCache): Promise<void> {
  lastCommentCapture = cache;
  try {
    await chrome.storage.session.set({ [COMMENT_API_STORAGE_KEY]: cache });
  } catch {
    // ignore
  }
}

export async function clearCommentApiCache(): Promise<void> {
  lastCommentCapture = null;
  try {
    await chrome.storage.session.remove(COMMENT_API_STORAGE_KEY);
  } catch {
    // ignore
  }
}

async function mergeCommentApiCapture(
  url: string,
  parsed: CommentApiItem[],
): Promise<void> {
  if (!parsed.length) return;
  const previous = lastCommentCapture ?? (await readCacheFromStorage());
  const byAweme = { ...(previous?.byAweme ?? {}) };

  for (const item of parsed) {
    const key = item.aweme_id || extractAwemeIdFromUrl(url) || "_unknown";
    const bucket = byAweme[key] ? [...byAweme[key]] : [];
    const index = bucket.findIndex((row) => row.comment_id === item.comment_id);
    if (index >= 0) bucket[index] = { ...item, aweme_id: key };
    else bucket.push({ ...item, aweme_id: key });
    byAweme[key] = bucket;
  }

  await writeCacheToStorage({
    at: Date.now(),
    byAweme,
    eventsSeen: (previous?.eventsSeen ?? 0) + 1,
    lastApiUrl: url,
  });
}

export async function ingestCommentApiResponse(
  url: string,
  body: unknown | null,
  status = 200,
): Promise<boolean> {
  if (!isCommentListApi(url)) return false;
  if (status >= 400 || !body) return false;
  const parsed = parseCommentApiBody(body, extractAwemeIdFromUrl(url));
  if (!parsed.length) return false;
  await mergeCommentApiCapture(url, parsed);
  return true;
}

export function ingestCommentNetworkPayload(payload: {
  url?: string;
  status?: number;
  body?: unknown;
}): boolean {
  const url = String(payload?.url ?? "");
  void ingestCommentApiResponse(url, payload?.body ?? null, payload?.status ?? 200);
  return Boolean(
    payload?.body &&
      isCommentListApi(url) &&
      parseCommentApiBody(payload.body, extractAwemeIdFromUrl(url)).length > 0,
  );
}

export async function getCommentApiItemsForAweme(
  awemeId: string,
  maxAgeMs = 180_000,
): Promise<CommentApiItem[]> {
  const cache =
    lastCommentCapture && Date.now() - lastCommentCapture.at <= maxAgeMs
      ? lastCommentCapture
      : await readCacheFromStorage();
  if (!cache || Date.now() - cache.at > maxAgeMs) return [];
  lastCommentCapture = cache;
  return cache.byAweme[awemeId] ?? [];
}

export async function getAllCachedCommentApiItems(maxAgeMs = 180_000): Promise<CommentApiItem[]> {
  const cache =
    lastCommentCapture && Date.now() - lastCommentCapture.at <= maxAgeMs
      ? lastCommentCapture
      : await readCacheFromStorage();
  if (!cache || Date.now() - cache.at > maxAgeMs) return [];
  lastCommentCapture = cache;
  return Object.values(cache.byAweme).flat();
}

export async function pollCommentApiCache(options: {
  timeoutMs?: number;
  minItems?: number;
  awemeId?: string;
} = {}): Promise<CommentApiItem[]> {
  const timeoutMs = options.timeoutMs ?? 8000;
  const minItems = Math.max(1, options.minItems ?? 1);
  const awemeId = String(options.awemeId ?? "").trim();
  const deadline = Date.now() + timeoutMs;

  while (Date.now() < deadline) {
    const items = awemeId
      ? await getCommentApiItemsForAweme(awemeId)
      : await getAllCachedCommentApiItems();
    if (items.length >= minItems) return items;
    await sleep(250);
  }

  return awemeId
    ? await getCommentApiItemsForAweme(awemeId)
    : await getAllCachedCommentApiItems();
}

export function initCommentApiCaptureBridge(): void {
  if (bridgeReady || typeof window === "undefined") return;
  bridgeReady = true;
  void readCacheFromStorage().then((cache) => {
    if (cache) lastCommentCapture = cache;
  });
  window.addEventListener("message", (event) => {
    if (event.source !== window || event.data?.channel !== INJECTED_CHANNEL) return;
    ingestCommentNetworkPayload(event.data.payload ?? {});
  });
}
