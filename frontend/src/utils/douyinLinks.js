export function normalizeExternalUrl(url) {
  const trimmed = String(url || "").trim();
  if (!trimmed) return "";
  if (/^https?:\/\//i.test(trimmed)) return trimmed;
  if (trimmed.startsWith("//")) return `https:${trimmed}`;
  return `https://${trimmed}`;
}

export function parseDouyinUserFromUrl(url) {
  const trimmed = String(url || "").trim();
  if (!trimmed) return { userId: "", secUid: "" };
  try {
    const parsed = new URL(normalizeExternalUrl(trimmed));
    const pathMatch = parsed.pathname.match(/\/user\/([^/?#]+)/i);
    if (pathMatch?.[1]) {
      const id = decodeURIComponent(pathMatch[1]);
      if (/^\d+$/.test(id)) return { userId: id, secUid: "" };
      return { userId: "", secUid: id };
    }
    return {
      userId: parsed.searchParams.get("uid") || parsed.searchParams.get("user_id") || "",
      secUid: parsed.searchParams.get("sec_uid") || "",
    };
  } catch {
    return { userId: "", secUid: "" };
  }
}

export function resolveDouyinVideoUrl({ awemeId, videoUrl, contentUrl } = {}) {
  const direct = normalizeExternalUrl(videoUrl || contentUrl || "");
  if (direct && /douyin\.com\/(video|note)/i.test(direct)) return direct;
  const id = String(awemeId || "").trim();
  if (!id || id.startsWith("poster_") || !/^\d{8,22}$/.test(id)) return direct;
  return `https://www.douyin.com/video/${id}`;
}

export function resolveDouyinProfileUrl({ secUid, userId, profileUrl, userProfileUrl, userUrl } = {}) {
  const direct = normalizeExternalUrl(profileUrl || userProfileUrl || userUrl || "");
  if (direct && /douyin\.com\/user\//i.test(direct)) return direct;
  const sec = String(secUid || "").trim();
  if (sec) return `https://www.douyin.com/user/${sec}`;
  const uid = String(userId || "").trim();
  if (uid) return `https://www.douyin.com/user/${uid}`;
  const parsed = parseDouyinUserFromUrl(direct);
  if (parsed.secUid) return `https://www.douyin.com/user/${parsed.secUid}`;
  if (parsed.userId) return `https://www.douyin.com/user/${parsed.userId}`;
  return "";
}

export function resolveCommentLinks(row, platform = "douyin") {
  const base = row && typeof row === "object" ? row : {};
  if (platform === "douyin") {
    return {
      video_url: resolveDouyinVideoUrl({
        awemeId: base.aweme_id,
        videoUrl: base.video_url,
        contentUrl: base.content_url,
      }),
      profile_url: resolveDouyinProfileUrl({
        secUid: base.sec_uid,
        userId: base.user_id,
        profileUrl: base.profile_url,
        userProfileUrl: base.user_profile_url,
        userUrl: base.user_url,
      }),
    };
  }
  return {
    video_url: normalizeExternalUrl(base.video_url || base.content_url || ""),
    profile_url: normalizeExternalUrl(base.profile_url || base.user_profile_url || base.user_url || ""),
  };
}
