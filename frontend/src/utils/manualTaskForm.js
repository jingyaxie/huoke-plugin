const PROFILE_URL_PATTERNS = {
  douyin: [/douyin\.com\/user\//i, /iesdouyin\.com\/share\/user\//i, /v\.douyin\.com\//i],
  xiaohongshu: [/xiaohongshu\.com\/user\/profile\//i],
  kuaishou: [/kuaishou\.com\/profile\//i, /v\.kuaishou\.com\//i],
};

const VIDEO_URL_PATTERNS = {
  douyin: [/douyin\.com\/video\//i, /iesdouyin\.com\/share\/video\//i],
  xiaohongshu: [/xiaohongshu\.com\/explore\//i, /xiaohongshu\.com\/discovery\/item\//i],
  kuaishou: [/kuaishou\.com\/short-video\//i, /v\.kuaishou\.com\/short\//i],
};

function matchesUrlPatterns(inputUrl, patterns = []) {
  return patterns.some((re) => re.test(inputUrl));
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
  const patterns = effectiveIntent === "account_home"
    ? PROFILE_URL_PATTERNS[platform] || []
    : VIDEO_URL_PATTERNS[platform] || [];
  if (!patterns.some((re) => re.test(trimmed))) {
    return effectiveIntent === "account_home"
      ? "请粘贴博主账号主页链接（将从主页获取视频列表并抓取评论）"
      : "请粘贴单条视频详情页链接";
  }
  return null;
}

export function manualUrlIntentHint(inputUrl, intent, platform) {
  const detected = detectManualUrlIntent(inputUrl, platform);
  if (!detected || detected === intent) return "";
  return detected === "account_home"
    ? "已识别为博主主页链接，将扫描主页视频列表并抓取评论"
    : "已识别为单条视频链接，将只抓取该视频评论";
}
