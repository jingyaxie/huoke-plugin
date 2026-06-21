export type DouyinPageKind = "search" | "video" | "profile" | "other";

export function detectPageKind(url: string): DouyinPageKind {
  if (/\/search\/|\/jingxuan\/search\/|\/root\/search\//i.test(url)) return "search";
  if (/\/video\/\d+/i.test(url) || /modal_id=\d+/i.test(url)) return "video";
  if (/\/user\//i.test(url)) return "profile";
  return "other";
}

export function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
