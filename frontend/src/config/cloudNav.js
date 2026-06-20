/** 本地获客引擎导航（插件架构，登录态由浏览器管理） */

export const LOCAL_NAV_SECTION = {
  label: "AI 获客（本机）",
  items: [
    { key: "platform_login", label: "平台登录", to: "/platform-login" },
    { key: "auto_tasks", label: "自动获客", to: "/extension-bridge" },
    { key: "manual_tasks", label: "手动获客", to: "/manual-tasks" },
    { key: "presets", label: "评论/私信预设", to: "/presets" },
    { key: "plugin_lab", label: "插件实验室", to: "/plugin-lab" },
  ],
};

const ROUTE_META_MAP = new Map();

for (const item of LOCAL_NAV_SECTION.items) {
  ROUTE_META_MAP.set(item.to, { section: LOCAL_NAV_SECTION.label, title: item.label });
}

ROUTE_META_MAP.set("/extension-bridge", { section: LOCAL_NAV_SECTION.label, title: "自动获客" });
ROUTE_META_MAP.set("/plugin-lab", { section: LOCAL_NAV_SECTION.label, title: "插件实验室" });
ROUTE_META_MAP.set("/manual-tasks", { section: LOCAL_NAV_SECTION.label, title: "手动获客" });

export function getRouteMeta(path) {
  if (ROUTE_META_MAP.has(path)) return ROUTE_META_MAP.get(path);
  for (const [routePath, meta] of ROUTE_META_MAP) {
    if (path.startsWith(`${routePath}/`)) return meta;
  }
  return null;
}
