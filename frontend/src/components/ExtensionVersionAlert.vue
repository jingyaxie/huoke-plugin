<template>
  <el-alert
    v-if="versionStatus.message"
    class="extension-version-alert"
    type="warning"
    :closable="false"
    show-icon
    title="Chrome 插件版本不匹配"
  >
    <p class="version-message">{{ versionStatus.message }}</p>
    <p v-if="versionStatus.expectedExtensionVersion" class="version-meta">
      App 要求插件 v{{ versionStatus.expectedExtensionVersion }}
      <template v-if="versionStatus.connectedExtensionVersion">
        · 当前连接 v{{ versionStatus.connectedExtensionVersion }}
      </template>
      <template v-else-if="versionStatus.installedExtensionVersion">
        · 本地目录 v{{ versionStatus.installedExtensionVersion }}
      </template>
    </p>
    <div v-if="canLaunch" class="version-actions">
      <el-button type="primary" size="small" :loading="launching" @click="$emit('launch')">
        启动浏览器插件
      </el-button>
      <el-button size="small" @click="$emit('open-folder')">打开插件目录</el-button>
    </div>
    <p class="version-hint">
      若仍提示不匹配，请到 <code>chrome://extensions</code> 对 Huoke 插件点击「重新加载」，或重新安装最新 App。
    </p>
  </el-alert>
</template>

<script setup>
import { computed } from "vue";
import { resolveExtensionVersionStatus } from "../utils/extensionVersion";

const props = defineProps({
  bridgeStatus: { type: Object, default: () => ({}) },
  extensionSetup: { type: Object, default: () => ({}) },
  canLaunch: { type: Boolean, default: false },
  launching: { type: Boolean, default: false },
});

defineEmits(["launch", "open-folder"]);

const versionStatus = computed(() =>
  resolveExtensionVersionStatus(props.bridgeStatus, props.extensionSetup),
);
</script>

<style scoped>
.extension-version-alert {
  margin-top: 10px;
}

.version-message {
  margin: 0 0 6px;
  font-size: 13px;
  line-height: 1.5;
}

.version-meta {
  margin: 0 0 8px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.version-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 6px;
}

.version-hint {
  margin: 0;
  font-size: 12px;
  line-height: 1.5;
  color: var(--el-text-color-secondary);
}

.version-hint code {
  font-size: 11px;
}
</style>
