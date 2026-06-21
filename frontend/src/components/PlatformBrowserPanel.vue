<template>
  <el-card shadow="never" class="platform-browser-panel">
    <template #header>
      <div class="panel-head">
        <span>平台登录</span>
        <span class="panel-hint">在 Chrome 打开平台页完成登录，插件复用浏览器 Cookie</span>
      </div>
    </template>

    <div class="platform-grid">
      <article v-for="item in platforms" :key="item.id" class="platform-card">
        <div class="platform-name">{{ item.label }}</div>
        <p class="platform-desc">{{ item.desc }}</p>
        <el-button type="primary" plain @click="openPlatform(item)">在 Chrome 中打开</el-button>
      </article>
    </div>

    <ExtensionSetupGuide
      :can-launch="canLaunch"
      :runtime-path="runtimePath"
      :bundle-path="bundlePath"
      :launching="launching"
      :checking="checking"
      @launch="$emit('launch')"
      @open-folder="$emit('open-folder')"
      @refresh="$emit('refresh')"
    />
  </el-card>
</template>

<script setup>
import { computed } from "vue";
import { ElMessage } from "element-plus";
import ExtensionSetupGuide from "./ExtensionSetupGuide.vue";
import { EXTENSION_PLATFORM_LOGIN_CARDS } from "../config/extensionPlatformCapabilities";
import { isTauriApp } from "../utils/desktopApp";

const props = defineProps({
  extensionSetup: { type: Object, default: () => ({}) },
  launching: { type: Boolean, default: false },
  checking: { type: Boolean, default: false },
});

defineEmits(["launch", "open-folder", "refresh"]);

const platforms = EXTENSION_PLATFORM_LOGIN_CARDS;
const canLaunch = computed(() => isTauriApp());

const runtimePath = computed(() => {
  const path = props.extensionSetup?.extensionPath || "";
  if (path) return path;
  if (/Win/i.test(navigator.userAgent)) {
    return "%APPDATA%\\com.huoke.desktop\\extension";
  }
  return "~/Library/Application Support/com.huoke.desktop/extension";
});

const bundlePath = computed(() => {
  const path = props.extensionSetup?.bundleExtensionPath || "";
  if (path) return path;
  if (/Win/i.test(navigator.userAgent)) {
    return "%LOCALAPPDATA%\\Programs\\盈小蚁\\resources\\desktop\\bundle\\extension";
  }
  return "盈小蚁.app/Contents/Resources/desktop/bundle/extension";
});

function openPlatform(item) {
  const opened = window.open(item.url, "_blank", "noopener,noreferrer");
  if (!opened) {
    ElMessage.warning("请允许弹出窗口，或手动在 Chrome 地址栏打开：" + item.url);
    return;
  }
  ElMessage.success(`已在浏览器打开${item.label}，请在该页面完成登录`);
}
</script>

<style scoped>
.platform-browser-panel {
  width: 100%;
}

.panel-head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 10px;
}

.panel-hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  font-weight: 400;
}

.platform-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.platform-card {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.platform-name {
  font-size: 16px;
  font-weight: 600;
}

.platform-desc {
  margin: 0;
  flex: 1;
  font-size: 13px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
}

@media (max-width: 900px) {
  .platform-grid {
    grid-template-columns: 1fr;
  }
}
</style>
