export type DouyinPageKind = "search" | "video" | "profile" | "other";

export function detectPageKind(url: string): DouyinPageKind {
  if (/\/search\/|\/jingxuan\/search\/|\/root\/search\//i.test(url)) return "search";
  try {
    const parsed = new URL(url);
    if (parsed.pathname.toLowerCase().includes("/search")) return "search";
    for (const key of ["keyword", "q", "search_key", "searchKey"]) {
      if (parsed.searchParams.get(key)?.trim()) return "search";
    }
  } catch {
    // ignore
  }
  if (/\/video\/\d+/i.test(url) || /modal_id=\d+/i.test(url)) return "video";
  if (/\/user\//i.test(url)) return "profile";
  return "other";
}

export function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
