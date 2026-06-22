import { humanClick, randDelay, sleep } from "./search-input";
import { readLabSearchUrl } from "./lab-context";
import { detectPlatformFromUrl } from "./platform-hosts";

const CLOSE_SELECTORS = [
  '[data-e2e="close-icon"]',
  '[aria-label="关闭"]',
  'button[aria-label="关闭"]',
  '[class*="close-btn"]',
] as const;

function isStandaloneVideoPage(url = location.href): boolean {
  return /\/video\/\d/i.test(url);
}

function feedDetailOpen(): boolean {
  return (
    Boolean(document.querySelector('[data-e2e="feed-active-video"]')) ||
    Boolean(document.querySelector('[data-e2e="feed-comment-icon"]')) ||
    /modal_id=/.test(location.href)
  );
}

function findCloseButton(): HTMLElement | null {
  for (const selector of CLOSE_SELECTORS) {
    const node = document.querySelector(selector) as HTMLElement | null;
    if (!node) continue;
    const rect = node.getBoundingClientRect();
    if (rect.width >= 10 && rect.height >= 10) return node;
  }
  return null;
}

/** 步骤 19：关闭视频详情 / Feed 浮层 / 工作窗独立 /video/ 页 */
export async function closeVideoDetail() {
  if (isStandaloneVideoPage()) {
    const platform = detectPlatformFromUrl(location.href) ?? "douyin";
    const storedSearch = await readLabSearchUrl(platform);
    if (storedSearch && !storedSearch.includes("/video/")) {
      location.assign(storedSearch);
      await sleep(randDelay(900, 1400));
    } else {
      history.back();
      await sleep(randDelay(700, 1100));
    }
    if (!isStandaloneVideoPage()) {
      return {
        ok: true,
        method: storedSearch ? "navigate_search" : "history_back",
        url: location.href,
        message: "已离开独立视频页",
      };
    }
    if (platform === "douyin") {
      location.assign("https://www.douyin.com");
      await sleep(randDelay(900, 1400));
    }
  }

  if (!feedDetailOpen()) {
    return {
      ok: true,
      already_closed: true,
      url: location.href,
      message: "视频详情未打开",
    };
  }

  document.dispatchEvent(
    new KeyboardEvent("keydown", { key: "Escape", code: "Escape", bubbles: true, cancelable: true }),
  );
  await sleep(randDelay(250, 400));
  document.dispatchEvent(
    new KeyboardEvent("keydown", { key: "Escape", code: "Escape", bubbles: true, cancelable: true }),
  );
  await sleep(randDelay(350, 550));

  if (!feedDetailOpen()) {
    return {
      ok: true,
      method: "escape",
      url: location.href,
      message: "已通过 Escape 关闭视频详情",
    };
  }

  const closeBtn = findCloseButton();
  if (closeBtn) {
    humanClick(closeBtn);
    await sleep(randDelay(500, 800));
  }

  if (feedDetailOpen() && /modal_id=/.test(location.href)) {
    history.back();
    await sleep(randDelay(500, 800));
  }

  const ok = !feedDetailOpen();
  return {
    ok,
    method: closeBtn ? "click_close" : "escape",
    url: location.href,
    message: ok ? "已关闭视频详情" : "尝试关闭视频详情，但浮层仍在",
  };
}
