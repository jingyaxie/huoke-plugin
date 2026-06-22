/** 云端客户后台导航（对齐 AI customer_ui 管理员可见 H5 菜单，不含已下线/组员专属入口） */

export function getPortalBaseUrl() {
  return (import.meta.env.VITE_PORTAL_BASE_URL || "https://www.tanjiyunai.com").replace(/\/+$/, "");
}

/** @type {Array<{ label: string, items: Array<{ key: string, label: string, to: string, h5Path: string }> }>} */
export const CLOUD_NAV_SECTIONS = [
  {
    label: "数据看板",
    items: [{ key: "dashboard", label: "数据看板", to: "/cloud/dashboard", h5Path: "/customer/dashboard" }],
  },
  {
    label: "账号管理",
    items: [{ key: "account_list", label: "账号列表", to: "/cloud/accounts", h5Path: "/customer/accounts" }],
  },
  {
    label: "AI客服管理",
    items: [
      { key: "materials", label: "素材管理", to: "/cloud/service/materials", h5Path: "/customer/service/materials" },
      { key: "agent_list", label: "智能体管理", to: "/cloud/agents", h5Path: "/customer/agents" },
      { key: "knowledge_bases", label: "知识库管理", to: "/cloud/knowledge-bases", h5Path: "/customer/knowledge-bases" },
      { key: "recall_lab", label: "知识库验证", to: "/cloud/recall-lab", h5Path: "/customer/recall-lab" },
      { key: "knowledge_questions", label: "问题管理", to: "/cloud/service/knowledge-questions", h5Path: "/customer/service/knowledge-questions" },
    ],
  },
  {
    label: "AI销冠管理",
    items: [
      { key: "sales_issues", label: "问题情况查询", to: "/cloud/sales/issues", h5Path: "/customer/sales/issues" },
      { key: "sales_recordings", label: "录音与文字查询", to: "/cloud/sales/recordings", h5Path: "/customer/sales/recordings" },
      { key: "sales_questions", label: "真人/销冠回答", to: "/cloud/sales/questions", h5Path: "/customer/sales/questions" },
    ],
  },
  {
    label: "客户管理",
    items: [{ key: "customer_list", label: "客户列表", to: "/cloud/customers", h5Path: "/customer/customers" }],
  },
];

const CLOUD_ROUTE_META_MAP = new Map();

function registerCloudMeta(item, section) {
  CLOUD_ROUTE_META_MAP.set(item.to, { section, title: item.label, cloud: true });
}

for (const section of CLOUD_NAV_SECTIONS) {
  for (const item of section.items) {
    registerCloudMeta(item, section.label);
  }
}

export function getCloudRouteMeta(path) {
  if (CLOUD_ROUTE_META_MAP.has(path)) return CLOUD_ROUTE_META_MAP.get(path);
  for (const [routePath, meta] of CLOUD_ROUTE_META_MAP) {
    if (path.startsWith(`${routePath}/`)) return meta;
  }
  return null;
}

export function findCloudNavByRoute(path) {
  for (const section of CLOUD_NAV_SECTIONS) {
    for (const item of section.items) {
      if (path === item.to || path.startsWith(`${item.to}/`)) return item;
    }
  }
  return null;
}

/** 将 H5 路径（/customer/dashboard）映射为壳层路由（/cloud/dashboard） */
export function mapH5PathToCloudRoute(h5Path) {
  const normalized = String(h5Path || "").trim();
  if (!normalized) return "/cloud/dashboard";
  const item = CLOUD_NAV_SECTIONS.flatMap((s) => s.items).find((entry) => {
    return normalized === entry.h5Path || normalized.startsWith(`${entry.h5Path}/`);
  });
  if (item) return item.to;
  if (normalized.startsWith("/customer/")) {
    return `/cloud${normalized.slice("/customer".length)}`;
  }
  return "/cloud/dashboard";
}

export function buildCloudRoutes() {
  const routes = [];
  const seen = new Set();
  const allCloudItems = CLOUD_NAV_SECTIONS.flatMap((s) => s.items);
  for (const item of allCloudItems) {
    if (seen.has(item.to)) continue;
    seen.add(item.to);
    const routePath = item.to.replace(/^\//, "");
    routes.push({
      path: routePath,
      name: `cloud-${item.key}`,
      component: () => import("../views/CloudEmbedView.vue"),
      meta: {
        cloud: true,
        h5Path: item.h5Path,
        title: item.label,
        section: getCloudRouteMeta(item.to)?.section,
        fillContent: true,
      },
    });
  }
  return routes;
}
