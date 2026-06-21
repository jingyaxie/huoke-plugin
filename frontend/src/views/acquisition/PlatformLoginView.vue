<template>
  <div class="acquisition-page">
    <header class="page-header">
      <div>
        <h1 class="page-title">账号绑定</h1>
        <p class="page-subtitle">
          安装盈小蚁后，先按下方说明配置 Chrome 插件，再登录抖音 / 小红书等平台账号。
        </p>
      </div>
      <div class="header-actions">
        <el-tag :type="bridgeTagType">{{ bridgeLabel }}</el-tag>
        <el-button size="small" @click="checkBridge" :loading="checking">检测连接</el-button>
      </div>
    </header>

    <PlatformBrowserPanel
      :extension-setup="extensionSetup"
      :launching="launchingExtension"
      :checking="checking"
      @launch="onLaunchChromeExtension"
      @open-folder="onOpenExtensionFolder"
      @refresh="refreshAll"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
import { ElMessage } from "element-plus";
import PlatformBrowserPanel from "../../components/PlatformBrowserPanel.vue";
import { fetchBridgeStatus } from "../../api/localService";
import {
  getExtensionSetupStatus,
  isTauriApp,
  launchChromeExtension,
  openExtensionFolder,
} from "../../utils/desktopApp";
import {
  bridgeConnectedLabel,
  bridgeConnectedTagType,
  resolveBridgeClientCount,
} from "../../utils/bridgeStatus";

const checking = ref(false);
const launchingExtension = ref(false);
const bridgeKnown = ref(true);
const bridgeStatus = ref({});
const extensionSetup = ref({});
let pollTimer = null;

const bridgeClientCount = computed(() =>
  resolveBridgeClientCount(bridgeStatus.value, extensionSetup.value),
);

const bridgeConnected = computed(() => bridgeClientCount.value > 0);

const bridgeLabel = computed(() =>
  bridgeConnectedLabel(bridgeClientCount.value, {
    checking: checking.value,
    known: bridgeKnown.value,
  }),
);

const bridgeTagType = computed(() =>
  bridgeConnectedTagType(bridgeClientCount.value, {
    checking: checking.value,
    known: bridgeKnown.value,
  }),
);

async function refreshExtensionSetup() {
  if (!isTauriApp()) return;
  try {
    extensionSetup.value = await getExtensionSetupStatus();
  } catch {
    // 保留已有 Tauri 状态，避免误显示未连接
  }
}

async function checkBridge() {
  await refreshAll();
}

async function refreshAll() {
  checking.value = true;
  try {
    bridgeStatus.value = await fetchBridgeStatus();
    bridgeKnown.value = true;
  } catch {
    bridgeKnown.value = false;
  }
  await refreshExtensionSetup();
  checking.value = false;
}

async function onLaunchChromeExtension() {
  launchingExtension.value = true;
  try {
    extensionSetup.value = await launchChromeExtension();
    await refreshAll();
    if (bridgeConnected.value) {
      ElMessage.success("Chrome 插件已连接");
    } else {
      ElMessage.warning("已启动 Chrome，请在窗口中登录平台并保持页面打开");
    }
  } catch (err) {
    ElMessage.error(err?.message || "启动 Chrome 插件失败");
  } finally {
    launchingExtension.value = false;
  }
}

async function onOpenExtensionFolder() {
  try {
    await openExtensionFolder();
  } catch (err) {
    ElMessage.error(err?.message || "打开插件目录失败");
  }
}

onMounted(async () => {
  await refreshAll();
  pollTimer = window.setInterval(refreshAll, 8000);
});

onUnmounted(() => {
  if (pollTimer) window.clearInterval(pollTimer);
});
</script>

<style scoped>
.acquisition-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
}

.page-subtitle {
  margin: 6px 0 0;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}
</style>
