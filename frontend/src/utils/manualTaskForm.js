const PROFILE_URL_PATTERNS = {
  douyin: [/douyin\.com\/user\//i, /iesdouyin\.com\/share\/user\//i],
  xiaohongshu: [/xiaohongshu\.com\/user\/profile\//i],
  kuaishou: [/kuaishou\.com\/profile\//i],
};

const VIDEO_URL_PATTERNS = {
  douyin: [
    /douyin\.com\/video\//i,
    /iesdouyin\.com\/share\/video\//i,
    /v\.douyin\.com\/\S+/i,
  ],
  xiaohongshu: [/xiaohongshu\.com\/explore\//i, /xiaohongshu\.com\/discovery\/item\//i],
  kuaishou: [/kuaishou\.com\/short-video\//i, /v\.kuaishou\.com\/\S+/i],
};

export function isDouyinShortLink(inputUrl) {
  return /v\.douyin\.com\//i.test(String(inputUrl || "").trim());
}

function matchesUrlPatterns(inputUrl, patterns = []) {
  return patterns.some((re) => re.test(inputUrl));
}

/** 从抖音链接解析视频 ID（/video/、modal_id=、vid=、aweme_id=） */
export function extractDouyinVideoIdFromUrl(inputUrl) {
  const trimmed = String(inputUrl || "").trim();
  if (!trimmed) return null;
  try {
    const url = new URL(trimmed);
    for (const key of ["vid", "aweme_id", "modal_id"]) {
      const value = url.searchParams.get(key)?.trim();
      if (value && /^\d{8,22}$/.test(value)) return value;
    }
    const videoMatch = url.pathname.match(/\/video\/(\d{8,22})/i);
    if (videoMatch?.[1]) return videoMatch[1];
  } catch {
    const modalMatch = trimmed.match(/[?&]modal_id=(\d{8,22})/i);
    if (modalMatch?.[1]) return modalMatch[1];
    const vidMatch = trimmed.match(/[?&]vid=(\d{8,22})/i);
    if (vidMatch?.[1]) return vidMatch[1];
    const pathMatch = trimmed.match(/\/video\/(\d{8,22})/i);
    if (pathMatch?.[1]) return pathMatch[1];
  }
  return null;
}

/** 单视频任务：归一化为可直接打开的详情页 URL */
export function normalizeManualInputUrl(inputUrl, intent, platform) {
  const trimmed = String(inputUrl || "").trim();
  if (!trimmed || intent !== "single_video") return trimmed;
  if (platform === "douyin") {
    const videoId = extractDouyinVideoIdFromUrl(trimmed);
    if (videoId) return `https://www.douyin.com/video/${videoId}`;
  }
  return trimmed;
}

/** 根据链接判断手动获客方式；无法判断时返回 null */
export function detectManualUrlIntent(inputUrl, platform) {
  const trimmed = String(inputUrl || "").trim();
  if (!trimmed) return null;
  try {
    // eslint-disable-next-line no-new
    new URL(trimmed);
  } catch {
    return null;
  }
  const profilePatterns = PROFILE_URL_PATTERNS[platform] || [];
  const videoPatterns = VIDEO_URL_PATTERNS[platform] || [];
  const isProfile = matchesUrlPatterns(trimmed, profilePatterns);
  const isVideo = matchesUrlPatterns(trimmed, videoPatterns);
  if (platform === "douyin" && isDouyinShortLink(trimmed)) {
    return null;
  }
  if (platform === "douyin" && extractDouyinVideoIdFromUrl(trimmed)) {
    if (isVideo || /[?&]vid=/i.test(trimmed) || /[?&]modal_id=/i.test(trimmed)) {
      return "single_video";
    }
  }
  if (isProfile && !isVideo) return "account_home";
  if (isVideo && !isProfile) return "single_video";
  return null;
}

export function deriveManualTaskName(inputUrl, intent) {
  const mode = intent === "account_home" ? "home_manual" : "video_manual";
  const trimmed = String(inputUrl || "").trim();
  if (!trimmed) {
    return mode === "home_manual" ? "博主主页获客" : "单视频获客";
  }
  try {
    const url = new URL(trimmed);
    const slug = decodeURIComponent(url.pathname.split("/").filter(Boolean).pop() || "").slice(0, 24);
    if (slug) {
      return mode === "home_manual" ? `博主-${slug}` : `视频-${slug}`;
    }
  } catch {
    /* ignore */
  }
  return mode === "home_manual" ? "博主主页获客" : "单视频获客";
}

export function validateManualTaskUrl(inputUrl, intent, platform) {
  const trimmed = String(inputUrl || "").trim();
  const effectiveIntent = detectManualUrlIntent(trimmed, platform) || intent;
  if (!trimmed) {
    return effectiveIntent === "account_home" ? "请粘贴博主主页链接" : "请粘贴视频详情页链接";
  }
  try {
    // eslint-disable-next-line no-new
    new URL(trimmed);
  } catch {
    return "链接格式不正确，请粘贴完整的 http/https 地址";
  }
  if (effectiveIntent === "single_video" && platform === "douyin") {
    if (extractDouyinVideoIdFromUrl(trimmed) || isDouyinShortLink(trimmed)) return null;
  }
  if (effectiveIntent === "account_home" && platform === "douyin" && isDouyinShortLink(trimmed)) {
    return null;
  }
  const patterns = effectiveIntent === "account_home"
    ? PROFILE_URL_PATTERNS[platform] || []
    : VIDEO_URL_PATTERNS[platform] || [];
  if (!patterns.some((re) => re.test(trimmed))) {
    return effectiveIntent === "account_home"
      ? "请粘贴博主账号主页链接（将从主页获取视频列表并抓取评论）"
      : "请粘贴单条视频链接（/video/xxx、v.douyin.com 短链，或带 vid= 的分享链）";
  }
  return null;
}

export function manualUrlIntentHint(inputUrl, intent, platform) {
  const detected = detectManualUrlIntent(inputUrl, platform);
  if (!detected || detected === intent) return "";
  return detected === "account_home"
    ? "已识别为博主主页链接，将扫描主页视频列表并抓取评论"
    : "已识别为单条视频链接，将打开视频详情页并只抓取该视频评论";
}
