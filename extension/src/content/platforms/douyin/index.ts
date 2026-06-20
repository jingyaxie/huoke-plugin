import { hostMatches, type PlatformAdapter } from "../types";
import {
  buildSearchUrl,
  buildVideoUrl,
  detectPageKind,
  sleep,
} from "./search";
import { replyToComment } from "./reply";
import { followFromComment, openProfileFromComment } from "./outreach-profile";
import { openSearchVideo } from "./open-search";
import {
  applyPublishTimeFilter,
  browseSearchVideos,
  listSearchVideos,
  runSearchUiFlow,
  submitSearch,
  typeSearchKeyword,
} from "./search-ui";

const HOST_PATTERNS = [/\.douyin\.com$/i, /^https:\/\/www\.douyin\.com/i];

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
  const scrolled: number[] = [];

  for (let i = 0; i < total; i += 1) {
    window.scrollBy({ top: 700, behavior: "smooth" });
    scrolled.push(window.scrollY);

    const panels = Array.from(
      document.querySelectorAll<HTMLElement>(
        '[class*="comment"], [data-e2e="comment-list"], [class*="CommentList"]',
      ),
    );
    for (const panel of panels) {
      if (panel.scrollHeight > panel.clientHeight + 40) {
        panel.scrollTop += 600;
      }
    }
    await sleep(900);
  }

  return { rounds: total, positions: scrolled };
}

async function scrollProfile(rounds: number) {
  const total = Math.max(1, Math.min(rounds, 12));
  const positions: number[] = [];
  for (let i = 0; i < total; i += 1) {
    window.scrollBy({ top: 900, behavior: "smooth" });
    positions.push(window.scrollY);
    const grids = Array.from(
      document.querySelectorAll<HTMLElement>(
        '[class*="user-post"], [class*="tab"], [class*="waterfall"], main',
      ),
    );
    for (const grid of grids) {
      if (grid.scrollHeight > grid.clientHeight + 40) {
        grid.scrollTop += 700;
      }
    }
    await sleep(1000);
  }
  return { rounds: total, positions };
}

export const douyinAdapter: PlatformAdapter = {
  id: "douyin",
  hostPatterns: HOST_PATTERNS,

  matches(url: string) {
    return hostMatches(url, HOST_PATTERNS);
  },

  getPageInfo(url: string, title: string) {
    return {
      url,
      title,
      platform: "douyin" as const,
      pageKind: detectPageKind(url),
    };
  },

  async handleCommand(action: string, payload: unknown) {
    switch (action) {
      case "platform.detect":
        return {
          platform: "douyin",
          url: location.href,
          pageKind: detectPageKind(location.href),
        };
      case "get_page_info":
        return this.getPageInfo(location.href, document.title);
      case "douyin.page.detect":
        return {
          platform: "douyin",
          pageKind: detectPageKind(location.href),
          url: location.href,
        };
      case "douyin.search.navigate": {
        const keyword = String((payload as { keyword?: string })?.keyword ?? "").trim();
        if (!keyword) throw new Error("douyin.search.navigate: missing keyword");
        return applyNavigate(buildSearchUrl(keyword));
      }
      case "douyin.search.open_video": {
        const index = Number((payload as { index?: number })?.index ?? 0);
        return openSearchVideo(index);
      }
      case "douyin.search.type": {
        const keyword = String((payload as { keyword?: string })?.keyword ?? "").trim();
        const charDelay = (payload as { char_delay_ms?: { min: number; max: number } })?.char_delay_ms;
        return typeSearchKeyword(keyword, charDelay);
      }
      case "douyin.search.submit": {
        const keyword = String((payload as { keyword?: string })?.keyword ?? "").trim();
        return submitSearch(keyword || undefined);
      }
      case "douyin.search.filter_time": {
        const days = Number((payload as { days?: number })?.days ?? 7);
        return applyPublishTimeFilter(days);
      }
      case "douyin.search.list_videos": {
        const max = Number((payload as { max?: number })?.max ?? 20);
        return listSearchVideos(max);
      }
      case "douyin.search.browse_videos": {
        const body = payload as { max?: number; pause_ms?: number; search_url?: string };
        return browseSearchVideos(body);
      }
      case "douyin.search.ui_flow":
        return runSearchUiFlow(payload as Parameters<typeof runSearchUiFlow>[0]);
      case "douyin.video.navigate": {
        const body = payload as { video_url?: string; aweme_id?: string; url?: string };
        const directUrl = String(body.url ?? body.video_url ?? "").trim();
        const awemeId = String(body.aweme_id ?? "").trim();
        if (directUrl) return applyNavigate(directUrl);
        if (awemeId) return applyNavigate(buildVideoUrl(awemeId));
        throw new Error("douyin.video.navigate: missing url, video_url or aweme_id");
      }
      case "douyin.url.navigate": {
        const url = String((payload as { url?: string })?.url ?? "").trim();
        if (!url) throw new Error("douyin.url.navigate: missing url");
        return applyNavigate(url);
      }
      case "douyin.profile.scroll": {
        const rounds = Number((payload as { rounds?: number })?.rounds ?? 3);
        return scrollProfile(rounds);
      }
      case "douyin.comments.scroll": {
        const rounds = Number((payload as { rounds?: number })?.rounds ?? 3);
        return scrollComments(rounds);
      }
      case "douyin.comment.reply":
        return replyToComment(payload as Parameters<typeof replyToComment>[0]);
      case "douyin.outreach.open_profile_from_comment":
        return openProfileFromComment(payload as Parameters<typeof openProfileFromComment>[0]);
      case "douyin.outreach.follow_from_comment":
        return followFromComment(payload as Parameters<typeof followFromComment>[0]);
      case "network.hook.enable": {
        hookEnabled = true;
        hookPatterns = (payload as { patterns?: string[] })?.patterns ?? [];
        window.postMessage(
          {
            channel: "huoke:injected:config",
            enabled: true,
            patterns: hookPatterns,
          },
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
        throw new Error(`douyin adapter: unknown action ${action}`);
    }
  },
};

export function isDouyinHookEnabled() {
  return hookEnabled;
}
