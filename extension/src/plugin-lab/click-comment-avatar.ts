import { randDelay, sleep } from "./search-input";

const AVATAR_SELECTORS = [
  '[data-e2e="comment-item"] div.comment-item-avatar a',
  '[data-e2e="comment-item"] a[href*="/user/"]',
  '[data-e2e="comment-item"] [data-e2e="live-avatar"]',
  "div.comment-item-avatar a",
] as const;

function getCommentItems(): HTMLElement[] {
  return Array.from(document.querySelectorAll('[data-e2e="comment-item"]')) as HTMLElement[];
}

function findAvatarLink(item: HTMLElement): HTMLAnchorElement | null {
  for (const selector of AVATAR_SELECTORS) {
    const scoped = selector.includes("comment-item")
      ? item.querySelector(selector.replace('[data-e2e="comment-item"] ', ""))
      : item.querySelector(selector);
    if (scoped instanceof HTMLAnchorElement) return scoped;
  }
  const link = item.querySelector('a[href*="/user/"]');
  return link instanceof HTMLAnchorElement ? link : null;
}

export interface ClickCommentAvatarPayload {
  comment_index?: number;
  index?: number;
}

/** 步骤 14：点击评论用户头像进入主页 */
export async function clickCommentAvatar(payload: ClickCommentAvatarPayload = {}) {
  const index = Math.max(1, Number(payload.comment_index ?? payload.index ?? 1));
  const items = getCommentItems();

  if (items.length === 0) {
    return {
      ok: false,
      comment_index: index,
      url: location.href,
      message: "未找到评论项",
    };
  }

  const item = items[Math.min(index, items.length) - 1];
  const avatar = findAvatarLink(item);
  if (!avatar) {
    return {
      ok: false,
      comment_index: index,
      url: location.href,
      message: `第 ${index} 条评论未找到用户头像链接`,
    };
  }

  const profileUrl = avatar.href;
  avatar.scrollIntoView({ block: "center", inline: "nearest", behavior: "instant" });
  await sleep(randDelay(120, 220));
  avatar.click();
  await sleep(randDelay(900, 1400));

  const onProfile =
    /\/user\//i.test(location.href) ||
    Boolean(document.querySelector('[data-e2e="user-detail"]')) ||
    Boolean(document.querySelector('[data-e2e="user-info-follow-btn"]'));

  return {
    ok: onProfile,
    clicked: true,
    comment_index: index,
    profile_url: profileUrl,
    url: location.href,
    message: onProfile ? `已点击第 ${index} 条评论用户头像` : "已点击头像，但未检测到用户主页",
  };
}
