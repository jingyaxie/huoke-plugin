import { INJECTED_MESSAGE } from "../../../shared/constants";
import type { PlatformSearchItem } from "../shared/content-item";
import { KS_SEARCH_API_MARKERS, PHOTO_ID_RE } from "./constants";

const CONFIG_CHANNEL = "huoke:injected:config";
const STORAGE_KEY = "huoke:ks-search-api-cache";

export function isKsSearchResultApi(url: string): boolean {
  const lower = url.toLowerCase();
  if (!lower.includes("kuaishou.com")) return false;
  return KS_SEARCH_API_MARKERS.some((m) => lower.includes(m));
}

export function enableKsSearchNetworkHook(): void {
  window.postMessage(
    {
      channel: CONFIG_CHANNEL,
      enabled: true,
      patterns: ["/rest/v/search/feed", "/graphql", "/search/feed"],
    },
    "*",
  );
}

function buildVideoUrl(photoId: string): string {
  return `https://www.kuaishou.com/short-video/${photoId}`;
}

function normalizeFeedItem(feed: Record<string, unknown>, rank: number): PlatformSearchItem | null {
  const photo = (feed.photo ?? feed) as Record<string, unknown>;
  const author = (feed.author ?? {}) as Record<string, unknown>;
  const photoId = String(photo.id ?? photo.photoId ?? feed.photoId ?? "").trim();
  if (!PHOTO_ID_RE.test(photoId)) return null;
  const title = String(photo.caption ?? photo.title ?? "").trim() || `快手视频 ${photoId.slice(0, 8)}`;
  return {
    index: rank,
    title: title.slice(0, 500),
    author: String(author.name ?? author.userName ?? "—").trim() || "—",
    url: buildVideoUrl(photoId),
    aweme_id: photoId,
    source: "api",
    click_by: "aweme_id",
    raw_json: { photo_id: photoId, feed },
  };
}

export function parseKsSearchApiBody(body: unknown): PlatformSearchItem[] {
  const seen = new Set<string>();
  const items: PlatformSearchItem[] = [];

  const walk = (node: unknown) => {
    if (!node || typeof node !== "object") return;
    if (Array.isArray(node)) {
      for (const child of node) walk(child);
      return;
    }
    const record = node as Record<string, unknown>;
    if ("photo" in record || record.id || record.photoId) {
      const normalized = normalizeFeedItem(record, items.length + 1);
      if (normalized && !seen.has(normalized.aweme_id)) {
        seen.add(normalized.aweme_id);
        items.push({ ...normalized, index: items.length + 1 });
      }
    }
    if (Array.isArray(record.feeds)) {
      for (const feed of record.feeds) {
        if (feed && typeof feed === "object") {
          const normalized = normalizeFeedItem(feed as Record<string, unknown>, items.length + 1);
          if (normalized && !seen.has(normalized.aweme_id)) {
            seen.add(normalized.aweme_id);
            items.push({ ...normalized, index: items.length + 1 });
          }
        }
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
}

let cache: SearchCache | null = null;

export async function clearKsSearchApiCache(): Promise<void> {
  cache = null;
  try {
    await chrome.storage.session.remove(STORAGE_KEY);
  } catch {
    // ignore
  }
}

async function mergeCapture(parsed: PlatformSearchItem[]): Promise<void> {
  const merged = new Map<string, PlatformSearchItem>();
  for (const item of cache?.items ?? []) merged.set(item.aweme_id, item);
  for (const item of parsed) merged.set(item.aweme_id, item);
  const items = Array.from(merged.values()).map((item, index) => ({ ...item, index: index + 1 }));
  cache = { at: Date.now(), items };
  try {
    await chrome.storage.session.set({ [STORAGE_KEY]: cache });
  } catch {
    // ignore
  }
}

export async function ingestKsSearchApiResponse(url: string, body: unknown | null, status = 200): Promise<boolean> {
  if (!isKsSearchResultApi(url) || status >= 400) return false;
  const parsed = body ? parseKsSearchApiBody(body) : [];
  await mergeCapture(parsed);
  return parsed.length > 0;
}

export function ingestKsNetworkPayload(payload: { url?: string; status?: number; body?: unknown }): void {
  void ingestKsSearchApiResponse(payload.url ?? "", payload.body ?? null, payload.status ?? 200);
}

export async function getKsSearchApiResults(maxAgeMs = 120_000): Promise<PlatformSearchItem[]> {
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

export async function waitForKsSearchApiResults(timeoutMs = 15_000, minItems = 1): Promise<PlatformSearchItem[]> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const items = await getKsSearchApiResults();
    if (items.length >= minItems) return items;
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
  return getKsSearchApiResults();
}

export function extractKsSearchKeyword(): string {
  try {
    const url = new URL(location.href);
    const fromQuery = url.searchParams.get("searchKey")?.trim();
    if (fromQuery) return fromQuery;
  } catch {
    // ignore
  }
  const inputs = document.querySelectorAll("input, textarea");
  for (let i = 0; i < inputs.length; i += 1) {
    const input = inputs[i] as HTMLInputElement | HTMLTextAreaElement;
    const value = (input.value ?? "").trim();
    if (value.length >= 1) return value;
  }
  return "";
}

/** 对齐 Python KuaishouJsApiTool.search_feed：主动 POST 搜索 feed 接口 */
export async function fireKsSearchFeedRequest(keyword: string): Promise<PlatformSearchItem[]> {
  const trimmed = keyword.trim();
  if (!trimmed) return [];
  try {
    const response = await fetch("https://www.kuaishou.com/rest/v/search/feed", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        keyword: trimmed,
        page: "search",
        webPageArea: "",
        pcursor: "",
      }),
    });
    if (!response.ok) return [];
    const body = (await response.json()) as unknown;
    const parsed = parseKsSearchApiBody(body);
    if (parsed.length > 0) await mergeCapture(parsed);
    return parsed;
  } catch {
    return [];
  }
}

let bridgeReady = false;

export function initKsSearchApiBridge(): void {
  if (bridgeReady || typeof window === "undefined") return;
  bridgeReady = true;
  window.addEventListener("message", (event) => {
    if (event.source !== window || event.data?.channel !== INJECTED_MESSAGE) return;
    ingestKsNetworkPayload(event.data.payload ?? {});
  });
}
