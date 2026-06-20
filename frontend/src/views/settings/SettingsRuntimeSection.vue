<template>
  <section class="settings-section panel">
    <header class="section-head">
      <h2 class="section-title">运行</h2>
      <p class="section-desc">智能体对话时的浏览器与传输偏好，保存于本地浏览器。</p>
    </header>

    <div class="pref-row">
      <div class="pref-copy">
        <strong>浏览器可见</strong>
        <p>关闭无头（可见）后，Skill 在本机 Chrome 窗口操作，便于排查登录与页面状态。</p>
      </div>
      <el-switch v-model="headless" size="large" inline-prompt active-text="无头" inactive-text="可见" />
    </div>

    <div class="pref-row">
      <div class="pref-copy">
        <strong>传输协议</strong>
        <p>SSE 为默认；WebSocket 适合长连接场景，连接失败会自动回退。</p>
      </div>
      <el-switch v-model="useWebSocket" size="large" inline-prompt active-text="WS" inactive-text="SSE" />
    </div>

    <div class="toolbar-row">
      <el-button :loading="browserLoginLoading === platformId" @click="openCurrentPlatformBrowser">
        打开当前平台浏览器
      </el-button>
      <router-link to="/tasks">
        <el-button text type="primary">Agent 编排</el-button>
      </router-link>
    </div>
  </section>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { fetchAccountBindings } from "../../api/accounts";
import { getPlatformId, getTenantId } from "../../api/http";
import { useAgentPreferences } from "../../composables/useAgentPreferences";
import { useAgentAccounts } from "../../composables/useAgentAccounts";
import { usePlatformBrowserLogin } from "../../composables/usePlatformBrowserLogin";

const PLATFORM_META = {
  douyin: { label: "抖音" },
  xiaohongshu: { label: "小红书" },
  kuaishou: { label: "快手" },
};

const { headless, useWebSocket } = useAgentPreferences();
const { activeAccountId, loadAccounts } = useAgentAccounts();
const accountBindings = ref([]);
const platformId = ref(getPlatformId());
const tenantId = ref(getTenantId());

const { browserLoginLoading, openBrowserLogin } = usePlatformBrowserLogin(() => activeAccountId.value);

async function openCurrentPlatformBrowser() {
  if (!accountBindings.value.length) {
    try {
      const data = await fetchAccountBindings(activeAccountId.value);
      accountBindings.value = data.platforms || [];
    } catch (err) {
      ElMessage.error(err.message || "加载绑定信息失败");
      return;
    }
  }
  const meta = PLATFORM_META[platformId.value] || PLATFORM_META.douyin;
  const row = accountBindings.value.find((item) => item.platform === platformId.value);
  await openBrowserLogin(
    row || { platform: platformId.value, platform_label: meta.label },
    { restore: true },
  );
}

onMounted(async () => {
  await loadAccounts();
});
</script>

<style scoped>
.pref-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  padding: 14px 0;
  border-bottom: 1px solid var(--border, #e2e8f0);
  max-width: 640px;
}

.pref-row:last-of-type {
  border-bottom: none;
  margin-bottom: 8px;
}

.pref-copy strong {
  display: block;
  margin-bottom: 4px;
  font-size: 14px;
}

.pref-copy p {
  margin: 0;
  font-size: 12px;
  color: var(--muted);
  line-height: 1.5;
}
</style>