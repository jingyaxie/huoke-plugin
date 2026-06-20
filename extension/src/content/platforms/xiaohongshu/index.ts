import { hostMatches, type PlatformAdapter } from "../types";
import { buildNoteUrl, buildSearchUrl, detectPageKind, sleep } from "./search";

const HOST_PATTERNS = [/\.xiaohongshu\.com$/i, /^https:\/\/www\.xiaohongshu\.com/i];

let hookEnabled = false;
let hookPatterns: string[] = [];

function applyNavigate(url: string) {
  if (location.href.split("#")[0] === url.split("#")[0]) {
    return { url, navigated: false, reason: "already_on_page" };
  }
  location.href = url;
  return { url, navigated: true };
}

async function scrollComments(rounds: number) {
  const total = Math.max(1, Math.min(rounds, 20));
  for (let i = 0; i < total; i += 1) {
    window.scrollBy({ top: 600, behavior: "smooth" });
    const panels = Array.from(
      document.querySelectorAll<HTMLElement>(
        '[class*="comment"], [class*="Comment"], [data-e2e="comment-list"]',
      ),
    );
    for (const panel of panels) {
      if (panel.scrollHeight > panel.clientHeight + 40) {
        panel.scrollTop += 500;
      }
    }
    await sleep(800);
  }
  return { rounds: total };
}

export const xiaohongshuAdapter: PlatformAdapter = {
  id: "xiaohongshu",
  hostPatterns: HOST_PATTERNS,

  matches(url: string) {
    return hostMatches(url, HOST_PATTERNS);
  },

  getPageInfo(url: string, title: string) {
    return {
      url,
      title,
      platform: "xiaohongshu" as const,
      pageKind: detectPageKind(url),
    };
  },

  async handleCommand(action: string, payload: unknown) {
    switch (action) {
      case "platform.detect":
        return {
          platform: "xiaohongshu",
          url: location.href,
          pageKind: detectPageKind(location.href),
        };
      case "get_page_info":
        return this.getPageInfo(location.href, document.title);
      case "xiaohongshu.page.detect":
      case "xhs.page.detect":
        return {
          platform: "xiaohongshu",
          pageKind: detectPageKind(location.href),
          url: location.href,
        };
      case "xiaohongshu.search.navigate":
      case "xhs.search.navigate": {
        const keyword = String((payload as { keyword?: string })?.keyword ?? "").trim();
        if (!keyword) throw new Error("xiaohongshu.search.navigate: missing keyword");
        return applyNavigate(buildSearchUrl(keyword));
      }
      case "xiaohongshu.note.navigate":
      case "xhs.note.navigate": {
        const body = payload as { note_url?: string; note_id?: string };
        const noteUrl = String(body.note_url ?? "").trim();
        const noteId = String(body.note_id ?? "").trim();
        if (noteUrl) return applyNavigate(noteUrl);
        if (noteId) return applyNavigate(buildNoteUrl(noteId));
        throw new Error("xiaohongshu.note.navigate: missing note_url or note_id");
      }
      case "xiaohongshu.comments.scroll":
      case "xhs.comments.scroll": {
        const rounds = Number((payload as { rounds?: number })?.rounds ?? 3);
        return scrollComments(rounds);
      }
      case "network.hook.enable": {
        hookEnabled = true;
        hookPatterns = (payload as { patterns?: string[] })?.patterns ?? [
          "/api/sns/web/",
          "edith.xiaohongshu.com",
        ];
        window.postMessage(
          { channel: "huoke:injected:config", enabled: true, patterns: hookPatterns },
          "*",
        );
        return { enabled: true, patterns: hookPatterns };
      }
      case "network.hook.disable":
        hookEnabled = false;
        hookPatterns = [];
        window.postMessage({ channel: "huoke:injected:config", enabled: false, patterns: [] }, "*");
        return { enabled: false };
      case "network.hook.status":
        return { enabled: hookEnabled, patterns: hookPatterns };
      default:
        throw new Error(`xiaohongshu adapter: unknown action ${action}`);
    }
  },
};
