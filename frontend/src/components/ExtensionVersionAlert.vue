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
      <ExtensionReloadButton
        size="small"
        :connected="bridgeConnected"
        @reloaded="$emit('reloaded')"
      />
      <el-button size="small" @click="$emit('open-folder')">打开插件目录</el-button>
    </div>
    <div v-else-if="bridgeConnected" class="version-actions">
      <ExtensionReloadButton size="small" :connected="true" @reloaded="$emit('reloaded')" />
    </div>
    <p class="version-hint">
      若仍提示不匹配，可点「重新加载插件」，或到 <code>chrome://extensions</code> 手动重新加载。
    </p>
  </el-alert>
</template>

<script setup>
import { computed } from "vue";
import ExtensionReloadButton from "./ExtensionReloadButton.vue";
import { resolveExtensionVersionStatus } from "../utils/extensionVersion";
import { resolveBridgeClientCount } from "../utils/bridgeStatus";

const props = defineProps({
  bridgeStatus: { type: Object, default: () => ({}) },
  extensionSetup: { type: Object, default: () => ({}) },
  canLaunch: { type: Boolean, default: false },
  launching: { type: Boolean, default: false },
});

defineEmits(["launch", "open-folder", "reloaded"]);

const versionStatus = computed(() =>
  resolveExtensionVersionStatus(props.bridgeStatus, props.extensionSetup),
);

const bridgeConnected = computed(
  () => resolveBridgeClientCount(props.bridgeStatus, props.extensionSetup) > 0,
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
