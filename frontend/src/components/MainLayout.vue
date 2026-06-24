<template>
  <div class="merchant-layout">
    <aside class="sidebar">
      <div class="brand-block">
        <div class="brand-title">盈小蚁</div>
      </div>

      <div class="sidebar-divider" />

      <nav class="nav-scroll">
        <div
          v-for="section in navSections"
          :key="section.label"
          class="nav-section"
          :class="{
            'is-collapsed': !isSectionExpanded(section),
            'section-has-active': sectionHasActiveItem(section),
          }"
        >
          <button
            type="button"
            class="section-title-btn"
            :aria-expanded="isSectionExpanded(section)"
            @click="toggleSection(section.label)"
          >
            <span class="section-title-text">{{ section.label }}</span>
            <span class="section-chevron" :class="{ expanded: isSectionExpanded(section) }" aria-hidden="true" />
          </button>

          <div v-show="isSectionExpanded(section)" class="section-items">
            <router-link
              v-for="item in section.items"
              :key="item.to"
              :to="item.to"
              class="nav-link"
              :class="{ active: isActive(item.to), 'nav-link-local': section.local }"
            >
              <span class="nav-indicator" />
              <span>{{ item.label }}</span>
            </router-link>
          </div>
        </div>
      </nav>

      <div class="sidebar-foot">
        <router-link
          v-if="showSettings"
          to="/settings/general"
          class="settings-link"
          :class="{ active: route.path.startsWith('/settings') }"
        >
          设置
        </router-link>
        <div class="foot-meta">v{{ appVersion }} · {{ portalEnabled ? "云端+本机" : "本地独立运行" }}</div>
      </div>
    </aside>

    <div class="main-column">
      <header class="top-header">
        <div class="breadcrumb">
          <span class="breadcrumb-section">{{ breadcrumbSection }}</span>
          <span class="breadcrumb-sep">/</span>
          <span class="breadcrumb-title">{{ breadcrumbTitle }}</span>
        </div>
        <div class="top-user">
          <span>你好，{{ displayName }}</span>
          <button
            v-if="portalEnabled && portalLoggedIn"
            type="button"
            class="logout-btn"
            :disabled="portalLogoutLoading"
            @click="handlePortalLogout"
          >
            {{ portalLogoutLoading ? "退出中..." : "退出云端" }}
          </button>
        </div>
      </header>

      <main class="content" :class="{ 'content--fill': fillContent || isCloudRoute }">
        <router-view />
      </main>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { CLOUD_NAV_SECTIONS, getRouteMeta, LOCAL_NAV_SECTION } from "../config/cloudNav";
import { getTenantId } from "../api/http";
import {
  clearPortalAuth,
  getPortalDisplayName,
  isPortalAuthenticated,
  isPortalEnabled,
  logoutPortalSession,
  markPortalLogoutPending,
  syncPortalDisplayName,
} from "../portal";
import { canAccessSettings } from "../utils/settingsAccess";
import { clearBackendCredentialsOnLogout, ensureEvaluationCredentialsSynced } from "../api/commentEvaluation";

const route = useRoute();
const router = useRouter();

const portalEnabled = isPortalEnabled();
const cloudNavSections = CLOUD_NAV_SECTIONS;
const localNavItems = LOCAL_NAV_SECTION.items;
const SECTION_STATE_KEY = "huoke_sidebar_sections";

const navSections = computed(() => {
  if (!portalEnabled) {
    return [{ label: LOCAL_NAV_SECTION.label, items: localNavItems, local: false }];
  }
  return [
    ...cloudNavSections.map((section) => ({ ...section, local: false })),
    { label: "AI获客管理", items: localNavItems, local: true },
  ];
});

const sectionExpanded = ref(loadSectionState());

function loadSectionState() {
  try {
    const raw = localStorage.getItem(SECTION_STATE_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function saveSectionState() {
  localStorage.setItem(SECTION_STATE_KEY, JSON.stringify(sectionExpanded.value));
}

function sectionHasActiveItem(section) {
  return section.items.some((item) => isActive(item.to));
}

function isSectionExpanded(section) {
  const saved = sectionExpanded.value[section.label];
  if (typeof saved === "boolean") return saved;
  return sectionHasActiveItem(section);
}

function toggleSection(label) {
  const section = navSections.value.find((item) => item.label === label);
  if (!section) return;
  sectionExpanded.value = {
    ...sectionExpanded.value,
    [label]: !isSectionExpanded(section),
  };
  saveSectionState();
}

function syncActiveSection() {
  let changed = false;
  const next = { ...sectionExpanded.value };
  for (const section of navSections.value) {
    if (sectionHasActiveItem(section) && next[section.label] === false) {
      next[section.label] = true;
      changed = true;
    }
  }
  if (changed) {
    sectionExpanded.value = next;
    saveSectionState();
  }
}

const portalLoggedIn = ref(isPortalAuthenticated());
const portalDisplayName = ref(getPortalDisplayName());
const portalLogoutLoading = ref(false);
const showSettings = computed(() => {
  void portalLoggedIn.value;
  void portalDisplayName.value;
  return canAccessSettings();
});

const appVersion = computed(() => import.meta.env.VITE_APP_VERSION || "0.2.0");
const isCloudRoute = computed(() => Boolean(route.meta?.cloud) || route.path.startsWith("/cloud/"));

const displayName = computed(() => {
  if (portalEnabled && portalLoggedIn.value) {
    const portalName = portalDisplayName.value || getPortalDisplayName();
    if (portalName) return portalName;
  }
  const tenantId = getTenantId();
  if (tenantId && tenantId !== "default") return tenantId;
  return "用户";
});

const breadcrumbSection = computed(() => {
  const meta = route.meta?.section || getRouteMeta(route.path)?.section;
  return meta || (isCloudRoute.value ? "客户后台" : "AI 获客");
});

const breadcrumbTitle = computed(() => {
  const meta = route.meta?.title || getRouteMeta(route.path)?.title;
  return meta || (isCloudRoute.value ? "盈小蚁" : "AI获客");
});

const fillContent = computed(() => route.meta.fillContent === true);

function onPortalAuthChanged() {
  portalLoggedIn.value = isPortalAuthenticated();
  portalDisplayName.value = getPortalDisplayName();
  void ensureEvaluationCredentialsSynced();
}

async function handlePortalLogout() {
  if (portalLogoutLoading.value) return;
  portalLogoutLoading.value = true;
  const redirect = route.fullPath;
  try {
    clearPortalAuth();
    portalLoggedIn.value = false;
    portalDisplayName.value = "";
    markPortalLogoutPending();
    await clearBackendCredentialsOnLogout();
    const loginRoute = { name: "portal-login" };
    if (redirect && redirect !== "/portal-login") {
      loginRoute.query = { redirect };
    }
    await router.replace(loginRoute);
    await logoutPortalSession();
    ElMessage.success("已退出云端登录");
  } catch {
    ElMessage.error("退出失败，请重试");
  } finally {
    portalLogoutLoading.value = false;
  }
}

function isActive(path) {
  return route.path === path || route.path.startsWith(`${path}/`);
}

onMounted(() => {
  syncActiveSection();
  window.addEventListener("huoke-portal-auth-changed", onPortalAuthChanged);
  void ensureEvaluationCredentialsSynced();
  if (portalEnabled && portalLoggedIn.value && !getPortalDisplayName()) {
    syncPortalDisplayName().then((name) => {
      portalLoggedIn.value = isPortalAuthenticated();
      portalDisplayName.value = name || getPortalDisplayName();
    });
  }
});

watch(() => route.path, () => {
  syncActiveSection();
});

onUnmounted(() => {
  window.removeEventListener("huoke-portal-auth-changed", onPortalAuthChanged);
});
</script>

<style scoped>
.merchant-layout {
  display: flex;
  height: 100%;
  background: var(--bg);
}

.sidebar {
  position: relative;
  display: flex;
  flex-direction: column;
  width: var(--sidebar-width);
  flex-shrink: 0;
  color-scheme: dark;
  background: var(--sidebar-bg);
  color: var(--sidebar-text);
  border-right: 1px solid var(--sidebar-border);
  box-shadow: 0 16px 32px rgba(1, 5, 14, 0.35);
}

.sidebar::before {
  content: "";
  position: absolute;
  inset: 0;
  background: radial-gradient(circle at top, var(--sidebar-glow), transparent 55%);
  opacity: 0.75;
  pointer-events: none;
}

.sidebar > * {
  position: relative;
  z-index: 1;
}

.brand-block {
  margin: 22px 16px 18px;
  padding: 8px 12px;
}

.brand-title {
  font-size: 22px;
  font-weight: 700;
  letter-spacing: 0.6px;
  line-height: 1.25;
  background: linear-gradient(135deg, #ffffff 0%, #b8e4ff 100%);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}

.brand-sub {
  margin-top: 8px;
  font-size: 13px;
  font-weight: 400;
  color: rgba(148, 180, 210, 0.88);
  letter-spacing: 0.3px;
  line-height: 1.4;
}

.sidebar-divider {
  height: 1px;
  margin: 0 16px 4px;
  background: var(--sidebar-border);
}

.nav-scroll {
  flex: 1;
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
  padding-right: 4px;
  scrollbar-width: thin;
  scrollbar-color: rgba(148, 163, 184, 0.32) transparent;
}

.nav-scroll::-webkit-scrollbar {
  width: 5px;
}

.nav-scroll::-webkit-scrollbar-track {
  margin: 4px 0;
  background: transparent;
}

.nav-scroll::-webkit-scrollbar-thumb {
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.22);
  transition: background 0.2s ease;
}

.nav-scroll:hover::-webkit-scrollbar-thumb {
  background: rgba(0, 229, 255, 0.38);
}

.nav-scroll::-webkit-scrollbar-thumb:active {
  background: rgba(0, 229, 255, 0.55);
}

.nav-scroll::-webkit-scrollbar-button {
  display: none;
  width: 0;
  height: 0;
}

.nav-section {
  padding: 4px 12px 0;
}

.nav-section + .nav-section {
  margin-top: 8px;
  padding-top: 10px;
  border-top: 1px solid rgba(148, 163, 184, 0.12);
}

.section-title-btn {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  margin: 0 0 2px;
  padding: 8px 8px 8px;
  border: none;
  border-radius: 0;
  background: transparent;
  color: var(--sidebar-text-strong);
  font: inherit;
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 0.02em;
  text-transform: none;
  text-align: left;
  cursor: pointer;
  transition: color 0.15s ease;
}

.section-title-btn:hover {
  color: #fff;
}

.section-has-active .section-title-btn {
  color: var(--sidebar-accent);
}

.section-title-text {
  flex: 1;
  min-width: 0;
}

.section-chevron {
  display: inline-block;
  width: 7px;
  height: 7px;
  margin-left: 8px;
  border-right: 1.5px solid var(--sidebar-text);
  border-bottom: 1.5px solid var(--sidebar-text);
  transform: rotate(45deg);
  transition: transform 0.15s ease, border-color 0.15s ease;
  flex-shrink: 0;
}

.section-has-active .section-chevron,
.section-title-btn:hover .section-chevron {
  border-color: var(--sidebar-accent);
}

.section-chevron.expanded {
  transform: rotate(-135deg);
}

.section-items {
  margin: 0 0 8px 10px;
  padding: 2px 0;
}

.nav-section.is-collapsed .section-title-btn {
  margin-bottom: 0;
}

.nav-link {
  position: relative;
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 2px 0;
  padding: 8px 10px 8px 12px;
  border: 1px solid transparent;
  border-radius: 8px;
  color: var(--sidebar-text);
  text-decoration: none;
  font-size: 12px;
  font-weight: 400;
  line-height: 1.35;
  transition: background 0.15s ease, color 0.15s ease, border-color 0.15s ease, box-shadow 0.15s ease;
}

.nav-link-local {
  color: #b8c5d6;
}

.nav-link:hover {
  background: var(--sidebar-accent-soft);
  border-color: rgba(0, 229, 255, 0.28);
  color: var(--sidebar-text-strong);
}

.nav-link.active {
  background: rgba(31, 155, 255, 0.14);
  border-color: rgba(31, 155, 255, 0.35);
  color: #fff;
  box-shadow: 0 0 0 1px rgba(0, 229, 255, 0.2), 0 0 16px rgba(0, 229, 255, 0.12);
}

.nav-indicator {
  flex-shrink: 0;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: transparent;
}

.nav-link.active .nav-indicator {
  background: var(--sidebar-accent);
  box-shadow: 0 0 8px rgba(0, 229, 255, 0.75);
}

.sidebar-foot {
  padding: 14px 20px 18px;
  border-top: 1px solid var(--sidebar-border);
}

.settings-link {
  display: inline-flex;
  align-items: center;
  margin-bottom: 8px;
  padding: 6px 10px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--sidebar-text);
  text-decoration: none;
  transition: background 0.15s ease, color 0.15s ease;
}

.settings-link:hover,
.settings-link.active {
  background: var(--sidebar-accent-soft);
  color: #fff;
}

.foot-meta {
  font-size: 11px;
  color: var(--sidebar-text-muted);
}

.main-column {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
  height: 100%;
}

.top-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 56px;
  flex-shrink: 0;
  padding: 0 32px;
  background: #fff;
  color: var(--text);
  border-bottom: 1px solid var(--border);
}

.breadcrumb {
  font-size: 14px;
}

.breadcrumb-section {
  font-weight: 500;
  color: var(--muted);
}

.breadcrumb-sep {
  margin: 0 8px;
  color: #cbd5e1;
}

.breadcrumb-title {
  color: var(--text);
}

.top-user {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 14px;
  color: var(--text);
}

.logout-btn {
  border: none;
  background: transparent;
  padding: 4px 6px;
  font-size: 14px;
  color: var(--muted);
  cursor: pointer;
  border-radius: 4px;
}

.logout-btn:hover {
  color: var(--primary);
  background: #f8fafc;
}

.content {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 28px 32px;
}

.content--fill {
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.content--fill > * {
  flex: 1;
  min-height: 0;
}

@media (max-width: 900px) {
  .merchant-layout {
    flex-direction: column;
  }

  .sidebar {
    width: 100%;
    max-height: 220px;
  }

  .content {
    padding: 16px;
  }
}
</style>
