import type { PageInfo, PlatformId } from "../../shared/protocol";

export interface PlatformAdapter {
  readonly id: PlatformId;
  readonly hostPatterns: RegExp[];
  matches(url: string): boolean;
  getPageInfo(url: string, title: string): PageInfo;
  handleCommand(action: string, payload: unknown): Promise<unknown>;
}

export function hostMatches(url: string, patterns: RegExp[]): boolean {
  return patterns.some((pattern) => pattern.test(url));
}
