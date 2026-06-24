import { createRouter, createWebHistory } from "vue-router";
import MainLayout from "../components/MainLayout.vue";
import PresetsView from "../views/acquisition/PresetsView.vue";
import ExtensionBridgeView from "../views/acquisition/ExtensionBridgeView.vue";
import ManualAcquisitionView from "../views/acquisition/ManualAcquisitionView.vue";
import PlatformLoginView from "../views/acquisition/PlatformLoginView.vue";
import AntibotView from "../views/AntibotView.vue";
import SettingsView from "../views/SettingsView.vue";
import SettingsGeneralSection from "../views/settings/SettingsGeneralSection.vue";
import SettingsModelSection from "../views/settings/SettingsModelSection.vue";
import SettingsMaintenanceSection from "../views/settings/SettingsMaintenanceSection.vue";
import PluginLabView from "../views/plugin-lab/PluginLabView.vue";
import PortalLoginView from "../portal/views/PortalLoginView.vue";
import { buildCloudRoutes } from "../config/cloudNav";
import { isPortalAuthenticated, isPortalEnabled, requiresPortalAuth } from "../portal";
import { canAccessSettings } from "../utils/settingsAccess";

function defaultHomePath() {
  return isPortalEnabled() ? "/cloud/dashboard" : "/extension-bridge";
}

const routes = [
  {
    path: "/portal-login",
    name: "portal-login",
    component: PortalLoginView,
    meta: { public: true },
  },
  {
    path: "/",
    component: MainLayout,
    children: [
      { path: "", redirect: () => defaultHomePath() },
      ...buildCloudRoutes(),
      { path: "auto-tasks", redirect: "/extension-bridge" },
      { path: "manual-tasks", name: "manual-tasks", component: ManualAcquisitionView, meta: { title: "手动获客", section: "AI 获客（本机）", fillContent: true } },
      { path: "llm-settings", redirect: "/settings/model" },
      { path: "account-settings", redirect: "/platform-login" },
      { path: "platform-login", name: "platform-login", component: PlatformLoginView, meta: { title: "账号绑定", section: "AI 获客（本机）" } },
      { path: "presets", name: "presets", component: PresetsView, meta: { title: "私信预设", section: "AI 获客（本机）" } },
      { path: "extension-bridge", name: "extension-bridge", component: ExtensionBridgeView, meta: { title: "自动获客", section: "AI 获客（本机）", fillContent: true } },
      { path: "plugin-lab", redirect: "/settings/plugin-lab" },
      { path: "agent", redirect: "/extension-bridge" },
      { path: "crawl-data", redirect: "/extension-bridge" },
      { path: "crawl-data/user", redirect: "/extension-bridge" },
      {
        path: "tasks",
        redirect: "/extension-bridge",
      },
      { path: "external-api", redirect: "/extension-bridge" },
      { path: "orchestration", redirect: "/extension-bridge" },
      { path: "tasks/create", redirect: "/extension-bridge" },
      { path: "tasks/compile", redirect: "/extension-bridge" },
      { path: "tasks/jobs/:jobId", redirect: "/extension-bridge" },
      {
        path: "settings",
        component: SettingsView,
        redirect: "/settings/general",
        children: [
          { path: "general", name: "settings-general", component: SettingsGeneralSection },
          { path: "model", name: "settings-model", component: SettingsModelSection, meta: { title: "大模型", section: "设置" } },
          { path: "diagnosis", redirect: "/settings/general" },
          { path: "account", redirect: "/platform-login" },
          { path: "runtime", redirect: "/settings/general" },
          { path: "skills", redirect: "/settings/general" },
          { path: "rules", redirect: "/settings/general" },
          { path: "experiences", redirect: "/settings/general" },
          { path: "agents", redirect: "/settings/general" },
          { path: "maintenance", name: "settings-maintenance", component: SettingsMaintenanceSection, meta: { title: "维护", section: "设置" } },
          { path: "plugin-lab", name: "settings-plugin-lab", component: PluginLabView, meta: { title: "插件实验室", section: "设置" } },
        ],
      },
      { path: "login", redirect: () => defaultHomePath() },
      { path: "antibot", name: "antibot", component: AntibotView },
    ],
  },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

router.beforeEach((to) => {
  if (to.path.startsWith("/settings") && !canAccessSettings()) {
    return { path: defaultHomePath() };
  }
  if (!isPortalEnabled()) return true;
  if (to.meta?.public) return true;
  if (!requiresPortalAuth(to.path)) return true;
  if (isPortalAuthenticated()) return true;
  return {
    name: "portal-login",
    query: { redirect: to.fullPath },
  };
});

export default router;
