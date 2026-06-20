export const PLATFORM_IDS = ["douyin", "xiaohongshu", "kuaishou"];

const PLATFORM_LABELS = {
  douyin: "抖音",
  xiaohongshu: "小红书",
  kuaishou: "快手",
};

export const PLATFORM_FILTER_OPTIONS = [
  { value: "", label: "全部平台" },
  ...PLATFORM_IDS.map((id) => ({ value: id, label: PLATFORM_LABELS[id] })),
];

const PLATFORM_COLORS = {
  douyin: "danger",
  xiaohongshu: "warning",
  kuaishou: "success",
};

export function platformLabel(platform) {
  return PLATFORM_LABELS[platform] || platform || "未知平台";
}

export function platformTagType(platform) {
  return PLATFORM_COLORS[platform] || "info";
}

export function externalIdLabel(platform) {
  if (platform === "douyin") return "视频 ID";
  if (platform === "xiaohongshu") return "笔记 ID";
  if (platform === "kuaishou") return "作品 ID";
  return "内容 ID";
}

/** PC 网页端是否支持对用户发私信（小红书 PC 端无此能力）。 */
export function supportsDirectMessage(platform) {
  return platform === "douyin" || platform === "kuaishou";
}

export function directMessageUnsupportedHint(platform) {
  if (platform === "xiaohongshu") {
    return "小红书 PC 网页版不支持私信，请使用抖音/快手，或通过小红书 App 手动联系。";
  }
  return "当前平台不支持网页端私信。";
}
