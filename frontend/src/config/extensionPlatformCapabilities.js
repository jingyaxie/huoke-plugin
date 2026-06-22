/** 插件 / 本机采集各平台能力（与 local-service GET /api/collect/capabilities 对齐） */

/** 前端获客 UI 展示的渠道（小红书、快手暂隐藏） */
export const EXTENSION_UI_PLATFORM_IDS = ["douyin"];

export const EXTENSION_PLATFORM_DEFINITIONS = [
  {
    id: "douyin",
    label: "抖音",
    collect: true,
    outreach: true,
    intents: ["keyword_auto", "single_video", "account_home"],
  },
  {
    id: "xiaohongshu",
    label: "小红书",
    collect: true,
    outreach: false,
    intents: ["keyword_auto", "single_video", "account_home"],
  },
  {
    id: "kuaishou",
    label: "快手",
    collect: true,
    outreach: false,
    intents: ["keyword_auto", "single_video", "account_home"],
  },
];

export const EXTENSION_PLATFORM_LOGIN_CARDS = [
  {
    id: "douyin",
    label: "抖音",
    url: "https://www.douyin.com",
    desc: "支持关键词采集与线索管理",
  },
  {
    id: "xiaohongshu",
    label: "小红书",
    url: "https://www.xiaohongshu.com",
    desc: "adapter 已接入，能力逐步开放",
  },
].filter((row) => EXTENSION_UI_PLATFORM_IDS.includes(row.id));

export function isExtensionUiVisiblePlatform(platform) {
  return EXTENSION_UI_PLATFORM_IDS.includes(String(platform || "").trim());
}

export function filterExtensionUiPlatforms(platforms) {
  return (platforms || []).filter((row) => isExtensionUiVisiblePlatform(row.id));
}

export function listExtensionCollectPlatforms() {
  return EXTENSION_PLATFORM_DEFINITIONS.filter(
    (row) => row.collect && isExtensionUiVisiblePlatform(row.id),
  ).map((row) => row.id);
}

export function isExtensionCollectPlatform(platform) {
  const row = EXTENSION_PLATFORM_DEFINITIONS.find((item) => item.id === platform);
  return Boolean(row?.collect) && isExtensionUiVisiblePlatform(platform);
}

export function extensionPlatformLabel(platform) {
  return EXTENSION_PLATFORM_DEFINITIONS.find((item) => item.id === platform)?.label ?? platform;
}

/** 合并服务端 capabilities（若可用）与本地默认值 */
export function mergeExtensionCapabilities(remotePlatforms = []) {
  if (!Array.isArray(remotePlatforms) || remotePlatforms.length === 0) {
    return filterExtensionUiPlatforms(EXTENSION_PLATFORM_DEFINITIONS);
  }
  const byId = new Map(EXTENSION_PLATFORM_DEFINITIONS.map((row) => [row.id, { ...row }]));
  for (const remote of remotePlatforms) {
    const id = String(remote?.id || "").trim();
    if (!id || !byId.has(id)) continue;
    const local = byId.get(id);
    byId.set(id, {
      ...local,
      collect: remote.collect ?? local.collect,
      outreach: remote.outreach ?? local.outreach,
      intents: remote.intents ?? local.intents,
      label: remote.label ?? local.label,
    });
  }
  return filterExtensionUiPlatforms([...byId.values()]);
}
