/** 插件 / 本机采集各平台能力（与 local-service GET /api/collect/capabilities 对齐） */

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

export function listExtensionCollectPlatforms() {
  return EXTENSION_PLATFORM_DEFINITIONS.filter((row) => row.collect).map((row) => row.id);
}

export function isExtensionCollectPlatform(platform) {
  const row = EXTENSION_PLATFORM_DEFINITIONS.find((item) => item.id === platform);
  return Boolean(row?.collect);
}

export function extensionPlatformLabel(platform) {
  return EXTENSION_PLATFORM_DEFINITIONS.find((item) => item.id === platform)?.label ?? platform;
}

/** 合并服务端 capabilities（若可用）与本地默认值 */
export function mergeExtensionCapabilities(remotePlatforms = []) {
  if (!Array.isArray(remotePlatforms) || remotePlatforms.length === 0) {
    return EXTENSION_PLATFORM_DEFINITIONS;
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
  return [...byId.values()];
}
