<template>
  <div class="settings-page">
    <aside class="settings-nav panel">
      <div class="nav-head">
        <router-link to="/extension-bridge" class="back-link">← 返回自动获客</router-link>
        <h1 class="nav-title">设置</h1>
        <p class="nav-desc">通用配置与桌面维护</p>
      </div>
      <nav class="nav-list">
        <router-link
          v-for="item in navItems"
          :key="item.path"
          :to="item.path"
          class="nav-item"
          active-class="active"
        >
          <span class="nav-item-label">{{ item.label }}</span>
          <span v-if="item.hint" class="nav-item-hint">{{ item.hint }}</span>
        </router-link>
      </nav>
    </aside>

    <main class="settings-main">
      <router-view />
    </main>
  </div>
</template>

<script setup>
const navItems = [
  { path: "/settings/general", label: "通用", hint: "租户与 API" },
  { path: "/settings/maintenance", label: "维护", hint: "修复与诊断" },
];
</script>

<style scoped>
.settings-page {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  width: 100%;
  min-height: 0;
}

.settings-nav {
  flex: 0 0 220px;
  position: sticky;
  top: 0;
  padding: 16px 14px;
}

.nav-head {
  padding: 0 6px 12px;
  border-bottom: 1px solid var(--border, #e2e8f0);
  margin-bottom: 8px;
}

.back-link {
  display: inline-block;
  margin-bottom: 8px;
  font-size: 13px;
  color: var(--muted);
  text-decoration: none;
}

.back-link:hover {
  color: var(--primary);
}

.nav-title {
  margin: 0 0 4px;
  font-size: 18px;
  font-weight: 700;
}

.nav-desc {
  margin: 0;
  font-size: 12px;
  color: var(--muted);
  line-height: 1.5;
}

.nav-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.nav-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 9px 10px;
  border-radius: 10px;
  text-decoration: none;
  color: var(--text);
  transition: background 0.15s;
}

.nav-item:hover {
  background: #f8fafc;
}

.nav-item.active {
  background: var(--el-color-primary-light-9);
  color: var(--primary);
}

.nav-item-label {
  font-size: 14px;
  font-weight: 600;
}

.nav-item-hint {
  font-size: 11px;
  color: var(--muted);
}

.nav-item.active .nav-item-hint {
  color: var(--el-color-primary-light-3);
}

.settings-main {
  flex: 1;
  min-width: 0;
  margin: 0;
  padding: 0;
}

@media (max-width: 860px) {
  .settings-page {
    flex-direction: column;
  }

  .settings-nav {
    position: static;
    flex: none;
    width: 100%;
  }

  .nav-list {
    flex-direction: row;
    flex-wrap: wrap;
  }

  .nav-item {
    min-width: 120px;
  }
}
</style>

<style>
.settings-section.panel {
  margin: 0;
  width: 100%;
  padding: 16px 18px;
}

.settings-section .section-head {
  margin-bottom: 14px;
}

.settings-section .section-title {
  margin: 0 0 6px;
  font-size: 18px;
  font-weight: 700;
}

.settings-section .section-desc {
  margin: 0;
  font-size: 13px;
  color: var(--muted);
  line-height: 1.5;
}

.settings-section .field-label {
  display: block;
  margin: 0 0 6px;
  font-size: 12px;
  color: var(--muted);
}

.settings-section .field-block {
  margin-bottom: 12px;
  max-width: 420px;
}

.settings-section .toolbar-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}

.settings-section .hint-text {
  margin: 0 0 12px;
  font-size: 13px;
  color: var(--muted);
  line-height: 1.5;
}

.settings-section .hint-text strong {
  color: var(--text);
}
</style>
