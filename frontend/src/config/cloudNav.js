/** 应用导航配置：本地获客 + 可选云端 H5 嵌入（portal 模块） */

import { getCloudRouteMeta } from "../portal/config/cloudNav";

export {
  CLOUD_NAV_SECTIONS,
  buildCloudRoutes,
  findCloudNavByRoute,
  getPortalBaseUrl,
  mapH5PathToCloudRoute,
} from "../portal";

/** 本地获客引擎导航（插件架构，登录态由浏览器管理） */
export const LOCAL_NAV_SECTION = {
  label: "AI 获客（本机）",
  items: [
    { key: "auto_tasks", label: "自动获客", to: "/extension-bridge" },
    { key: "presets", label: "评论/私信预设", to: "/presets" },
    { key: "platform_login", label: "账号绑定", to: "/platform-login" },
  ],
};

const LOCAL_ROUTE_META_MAP = new Map();

for (const item of LOCAL_NAV_SECTION.items) {
  LOCAL_ROUTE_META_MAP.set(item.to, { section: LOCAL_NAV_SECTION.label, title: item.label, cloud: false });
}

LOCAL_ROUTE_META_MAP.set("/extension-bridge", { section: LOCAL_NAV_SECTION.label, title: "自动获客", cloud: false });
LOCAL_ROUTE_META_MAP.set("/manual-tasks", { section: LOCAL_NAV_SECTION.label, title: "手动获客", cloud: false });
LOCAL_ROUTE_META_MAP.set("/platform-login", { section: LOCAL_NAV_SECTION.label, title: "账号绑定", cloud: false });

export function getRouteMeta(path) {
  const cloudMeta = getCloudRouteMeta(path);
  if (cloudMeta) return cloudMeta;
  if (LOCAL_ROUTE_META_MAP.has(path)) return LOCAL_ROUTE_META_MAP.get(path);
  for (const [routePath, meta] of LOCAL_ROUTE_META_MAP) {
    if (path.startsWith(`${routePath}/`)) return meta;
  }
  return null;
}
