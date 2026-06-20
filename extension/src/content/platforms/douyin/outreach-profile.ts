import { buildVideoUrl, sleep } from "./search";
import { clickFollowButton } from "../../../plugin-lab/click-follow-btn";

const COMMENT_ITEM_SELECTOR = '[data-e2e="comment-item"]';

export interface ProfileFromCommentPayload {
  video_url?: string;
  aweme_id?: string;
  comment_id?: string;
  comment_text?: string;
  scroll_rounds?: number;
}

function normalizeText(value: string) {
  return value.replace(/\s+/g, " ").trim();
}

function getCommentNodes() {
  return Array.from(document.querySelectorAll<HTMLElement>(COMMENT_ITEM_SELECTOR));
}

function matchCommentNode(node: HTMLElement, commentId?: string, commentText?: string) {
  if (commentId) {
    const idAttr =
      node.getAttribute("data-comment-id") ||
      node.dataset.commentId ||
      node.querySelector("[data-comment-id]")?.getAttribute("data-comment-id") ||
      "";
    if (idAttr && idAttr === commentId) return true;
    if (node.outerHTML.includes(commentId)) return true;
  }
  if (commentText) {
    const text = normalizeText(commentText);
    if (text && normalizeText(node.textContent || "").includes(text)) return true;
  }
  return false;
}

async function scrollCommentPanels(rounds: number) {
  for (let i = 0; i < rounds; i += 1) {
    const panels = Array.from(
      document.querySelectorAll<HTMLElement>(
        '[class*="comment"], [data-e2e="comment-list"], [class*="CommentList"]',
      ),
    );
    for (const panel of panels) {
      if (panel.scrollHeight > panel.clientHeight + 40) {
        panel.scrollTop += 700;
      }
    }
    window.scrollBy({ top: 500, behavior: "smooth" });
    await sleep(700);
  }
}

async function waitForCommentItems(timeoutMs = 12000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (getCommentNodes().length > 0) return true;
    await sleep(400);
  }
  return false;
}

async function findTargetComment(commentId?: string, commentText?: string, scrollRounds = 12) {
  for (let round = 0; round <= scrollRounds; round += 1) {
    const nodes = getCommentNodes();
    const direct = nodes.find((node) => matchCommentNode(node, commentId, commentText));
    if (direct) {
      direct.scrollIntoView({ block: "center", behavior: "smooth" });
      await sleep(500);
      return direct;
    }
    if (round < scrollRounds) {
      await scrollCommentPanels(1);
    }
  }
  return null;
}

function findAvatarLink(item: HTMLElement): HTMLAnchorElement | null {
  const selectors = [
    'div.comment-item-avatar a',
    'a[href*="/user/"]',
    '[data-e2e="live-avatar"]',
  ];
  for (const selector of selectors) {
    const node = item.querySelector(selector);
    if (node instanceof HTMLAnchorElement) return node;
  }
  const link = item.querySelector('a[href*="/user/"]');
  return link instanceof HTMLAnchorElement ? link : null;
}

function onProfilePage() {
  return (
    /\/user\//i.test(location.href) ||
    Boolean(document.querySelector('[data-e2e="user-detail"]')) ||
    Boolean(document.querySelector('[data-e2e="user-info-follow-btn"]'))
  );
}

export async function openProfileFromComment(payload: ProfileFromCommentPayload) {
  const commentId = String(payload.comment_id || "").trim();
  const commentText = String(payload.comment_text || "").trim();
  if (!commentId && !commentText) {
    return { ok: false, error: "comment_id or comment_text is required" };
  }

  const awemeId = String(payload.aweme_id || "").trim();
  const videoUrl =
    String(payload.video_url || "").trim() || (awemeId ? buildVideoUrl(awemeId) : "");
  if (videoUrl && !location.href.includes(videoUrl.replace("https://www.douyin.com", ""))) {
    location.href = videoUrl;
    return { ok: false, error: "navigating_to_video", video_url: videoUrl };
  }

  const hasComments = await waitForCommentItems();
  if (!hasComments) {
    return { ok: false, error: "comment list not loaded", video_url: videoUrl };
  }

  const target = await findTargetComment(
    commentId || undefined,
    commentText || undefined,
    Math.max(1, Math.min(payload.scroll_rounds ?? 12, 24)),
  );
  if (!target) {
    return {
      ok: false,
      error: "target comment not found",
      comment_id: commentId || undefined,
      video_url: videoUrl,
    };
  }

  const avatar = findAvatarLink(target);
  if (!avatar) {
    return { ok: false, error: "avatar link not found", video_url: videoUrl };
  }

  avatar.scrollIntoView({ block: "center", inline: "nearest", behavior: "instant" });
  await sleep(400);
  avatar.click();
  await sleep(1200);

  return {
    ok: onProfilePage(),
    profile_url: avatar.href,
    url: location.href,
    comment_id: commentId || undefined,
    video_url: videoUrl,
    error: onProfilePage() ? undefined : "profile page not detected",
  };
}

export async function followFromComment(payload: ProfileFromCommentPayload) {
  const opened = await openProfileFromComment(payload);
  if (!opened.ok) {
    return opened;
  }
  const follow = await clickFollowButton();
  return {
    ok: Boolean(follow.ok),
    step: "follow",
    profile: opened,
    follow,
  };
}
