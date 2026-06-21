import { INJECTED_MESSAGE } from "../../../shared/constants";
import type { PlatformSearchItem } from "../shared/content-item";
import { NOTE_ID_RE, XHS_SEARCH_API_EXCLUDES, XHS_SEARCH_API_MARKERS } from "./constants";

const CONFIG_CHANNEL = "huoke:injected:config";
const STORAGE_KEY = "huoke:xhs-search-api-cache";

export function isXhsSearchResultApi(url: string): boolean {
  const lower = url.toLowerCase();
  if (!lower.includes("xiaohongshu.com") && !lower.includes("edith.xiaohongshu.com")) return false;
  if (XHS_SEARCH_API_EXCLUDES.some((m) => lower.includes(m))) return false;
  return XHS_SEARCH_API_MARKERS.some((m) => lower.includes(m));
}

export function enableXhsSearchNetworkHook(): void {
  window.postMessage(
    {
      channel: CONFIG_CHANNEL,
      enabled: true,
      patterns: ["/api/sns/web/", "edith.xiaohongshu.com", "/search/notes"],
    },
    "*",
  );
}

function findXsec(node: unknown): { token?: string; source?: string } {
  let token: string | undefined;
  let source: string | undefined;
  const walk = (value: unknown) => {
    if (!value || typeof value !== "object") return;
    if (Array.isArray(value)) {
      for (const item of value) walk(item);
      return;
    }
    const record = value as Record<string, unknown>;
    if (!token) {
      const raw = record.xsec_token ?? record.xsecToken;
      if (typeof raw === "string" && raw.trim()) token = raw.trim();
    }
    if (!source) {
      const raw = record.xsec_source ?? record.xsecSource;
      if (typeof raw === "string" && raw.trim()) source = raw.trim();
    }
    for (const child of Object.values(record)) walk(child);
  };
  walk(node);
  return { token, source };
}

function buildNoteUrl(noteId: string, xsecToken?: string, xsecSource?: string): string {
  const params = new URLSearchParams();
  if (xsecToken) params.set("xsec_token", xsecToken);
  if (xsecSource) params.set("xsec_source", xsecSource);
  const query = params.toString();
  return query
    ? `https://www.xiaohongshu.com/explore/${noteId}?${query}`
    : `https://www.xiaohongshu.com/explore/${noteId}`;
}

function normalizeNoteCard(item: Record<string, unknown>, rank: number): PlatformSearchItem | null {
  const card = (item.note_card ?? item.note ?? item) as Record<string, unknown>;
  const noteId = String(
    card.note_id ?? card.id ?? item.note_id ?? item.id ?? "",
  ).trim();
  if (!NOTE_ID_RE.test(noteId)) return null;

  const user = (card.user ?? card.author ?? {}) as Record<string, unknown>;
  const interact = (card.interact_info ?? card.interactInfo ?? {}) as Record<string, unknown>;
  const title = String(
    card.display_title ?? card.title ?? card.desc ?? card.displayTitle ?? "",
  ).trim() || `小红书笔记 ${noteId.slice(0, 8)}`;

  let xsecToken = String(card.xsec_token ?? item.xsec_token ?? "").trim() || undefined;
  let xsecSource = String(card.xsec_source ?? item.xsec_source ?? "pc_search").trim() || undefined;
  if (!xsecToken) {
    const nested = findXsec(item);
    xsecToken = nested.token;
    xsecSource = nested.source ?? xsecSource;
  }

  return {
    index: rank,
    title,
    author: String(user.nickname ?? user.nick_name ?? user.name ?? "—").trim() || "—",
    url: buildNoteUrl(noteId, xsecToken, xsecSource),
    aweme_id: noteId,
    source: "api",
    click_by: "aweme_id",
    xsec_token: xsecToken,
    xsec_source: xsecSource,
    raw_json: { note_id: noteId, xsec_token: xsecToken, xsec_source: xsecSource, card },
  };
}

export function parseXhsSearchApiBody(body: unknown): PlatformSearchItem[] {
  const seen = new Set<string>();
  const items: PlatformSearchItem[] = [];

  const walk = (node: unknown) => {
    if (!node || typeof node !== "object") return;
    if (Array.isArray(node)) {
      for (const child of node) walk(child);
      return;
    }
    const record = node as Record<string, unknown>;
    if ("note_card" in record || "note_id" in record || "noteId" in record) {
      const normalized = normalizeNoteCard(record, items.length + 1);
      if (normalized && !seen.has(normalized.aweme_id)) {
        seen.add(normalized.aweme_id);
        items.push({ ...normalized, index: items.length + 1 });
      }
    }
    for (const value of Object.values(record)) walk(value);
  };

  walk(body);
  return items;
}

interface SearchCache {
  at: number;
  items: PlatformSearchItem[];
  eventsSeen: number;
}

let cache: SearchCache | null = null;

export async function clearXhsSearchApiCache(): Promise<void> {
  cache = null;
  try {
    await chrome.storage.session.remove(STORAGE_KEY);
  } catch {
    // ignore
  }
}

async function mergeCapture(url: string, parsed: PlatformSearchItem[]): Promise<void> {
  const merged = new Map<string, PlatformSearchItem>();
  for (const item of cache?.items ?? []) merged.set(item.aweme_id, item);
  for (const item of parsed) merged.set(item.aweme_id, item);
  const items = Array.from(merged.values()).map((item, index) => ({ ...item, index: index + 1 }));
  cache = { at: Date.now(), items, eventsSeen: (cache?.eventsSeen ?? 0) + 1 };
  try {
    await chrome.storage.session.set({ [STORAGE_KEY]: cache });
  } catch {
    // ignore
  }
  void url;
}

export async function ingestXhsSearchApiResponse(url: string, body: unknown | null, status = 200): Promise<boolean> {
  if (!isXhsSearchResultApi(url) || status >= 400) return false;
  const parsed = body ? parseXhsSearchApiBody(body) : [];
  await mergeCapture(url, parsed);
  return parsed.length > 0;
}

export function ingestXhsNetworkPayload(payload: { url?: string; status?: number; body?: unknown }): void {
  void ingestXhsSearchApiResponse(payload.url ?? "", payload.body ?? null, payload.status ?? 200);
}

export async function getXhsSearchApiResults(maxAgeMs = 120_000): Promise<PlatformSearchItem[]> {
  if (cache && Date.now() - cache.at <= maxAgeMs) return cache.items;
  try {
    const stored = await chrome.storage.session.get(STORAGE_KEY);
    const value = stored[STORAGE_KEY] as SearchCache | undefined;
    if (value && Date.now() - value.at <= maxAgeMs) {
      cache = value;
      return value.items;
    }
  } catch {
    // ignore
  }
  return [];
}

export async function waitForXhsSearchApiResults(timeoutMs = 15_000, minItems = 1): Promise<PlatformSearchItem[]> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const items = await getXhsSearchApiResults();
    if (items.length >= minItems) return items;
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
  return getXhsSearchApiResults();
}

let bridgeReady = false;

export function initXhsSearchApiBridge(): void {
  if (bridgeReady || typeof window === "undefined") return;
  bridgeReady = true;
  window.addEventListener("message", (event) => {
    if (event.source !== window || event.data?.channel !== INJECTED_MESSAGE) return;
    ingestXhsNetworkPayload(event.data.payload ?? {});
  });
}
