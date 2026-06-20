<template>
  <div class="acquisition-page">
    <header class="page-header">
      <div>
        <h1 class="page-title">平台登录</h1>
        <p class="page-subtitle">
          在 Chrome 中打开对应平台并完成登录。登录态由浏览器自行管理，App 不绑定、不检测账号状态。
        </p>
      </div>
      <div class="header-actions">
        <el-tag :type="bridgeTagType">{{ bridgeLabel }}</el-tag>
        <el-button @click="checkBridge" :loading="checking">检测插件连接</el-button>
      </div>
    </header>

    <PlatformBrowserPanel />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import PlatformBrowserPanel from "../../components/PlatformBrowserPanel.vue";
import { fetchBridgeStatus } from "../../api/localService";

const checking = ref(false);
const bridgeStatus = ref({ connected_clients: 0 });

const bridgeLabel = computed(() => {
  const count = Number(bridgeStatus.value.connected_clients || 0);
  return count > 0 ? `插件已连接 (${count})` : "插件未连接";
});

const bridgeTagType = computed(() =>
  Number(bridgeStatus.value.connected_clients || 0) > 0 ? "success" : "warning",
);

async function checkBridge() {
  checking.value = true;
  try {
    bridgeStatus.value = await fetchBridgeStatus();
  } catch {
    bridgeStatus.value = { connected_clients: 0 };
  } finally {
    checking.value = false;
  }
}

onMounted(() => {
  void checkBridge();
});
</script>

<style scoped>
.acquisition-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
}

.page-subtitle {
  margin: 6px 0 0;
  color: var(--el-text-color-secondary);
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}
</style>
