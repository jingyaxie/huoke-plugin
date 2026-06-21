/** 本地获客引擎导航（插件架构，登录态由浏览器管理） */

export const LOCAL_NAV_SECTION = {
  label: "AI 获客（本机）",
  items: [
    { key: "auto_tasks", label: "自动获客", to: "/extension-bridge" },
    { key: "manual_tasks", label: "手动获客", to: "/manual-tasks" },
    { key: "presets", label: "评论/私信预设", to: "/presets" },
    { key: "platform_login", label: "账号绑定", to: "/platform-login" },
  ],
};

const ROUTE_META_MAP = new Map();

for (const item of LOCAL_NAV_SECTION.items) {
  ROUTE_META_MAP.set(item.to, { section: LOCAL_NAV_SECTION.label, title: item.label });
}

ROUTE_META_MAP.set("/extension-bridge", { section: LOCAL_NAV_SECTION.label, title: "自动获客" });
ROUTE_META_MAP.set("/manual-tasks", { section: LOCAL_NAV_SECTION.label, title: "手动获客" });
ROUTE_META_MAP.set("/platform-login", { section: LOCAL_NAV_SECTION.label, title: "账号绑定" });

export function getRouteMeta(path) {
  if (ROUTE_META_MAP.has(path)) return ROUTE_META_MAP.get(path);
  for (const [routePath, meta] of ROUTE_META_MAP) {
    if (path.startsWith(`${routePath}/`)) return meta;
  }
  return null;
}
