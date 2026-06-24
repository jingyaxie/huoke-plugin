<template>
  <el-button
    :size="size"
    :plain="plain"
    :type="type"
    :loading="loading"
    :disabled="disabled && !loading"
    @click="handleReload"
  >
    重新加载插件
  </el-button>
</template>

<script setup>
import { ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  fetchBridgeStatus,
  reloadChromeExtension,
  waitForBridgeReconnect,
} from "../api/localService";

const props = defineProps({
  /** 显式传入；不传则点击时现查 bridge 状态 */
  connected: { type: Boolean, default: undefined },
  size: { type: String, default: "default" },
  plain: { type: Boolean, default: true },
  type: { type: String, default: "default" },
  /** 跳过确认框（维护页等场景可设为 true） */
  skipConfirm: { type: Boolean, default: false },
});

const emit = defineEmits(["reloaded"]);

const loading = ref(false);
const disabled = ref(false);

async function resolveConnected() {
  if (props.connected !== undefined) return props.connected;
  try {
    const status = await fetchBridgeStatus();
    return Number(status.connected_clients || status.extension_clients || 0) > 0;
  } catch {
    return false;
  }
}

async function handleReload() {
  const connected = await resolveConnected();
  if (!connected) {
    ElMessage.warning("插件未连接，请先在 chrome://extensions 加载 Huoke 扩展");
    return;
  }

  if (!props.skipConfirm) {
    try {
      await ElMessageBox.confirm(
        "将重新加载 Chrome 中的 Huoke 插件，并重置当前会话。抖音等平台页会自动刷新。是否继续？",
        "重新加载插件",
        { type: "warning", confirmButtonText: "重新加载", cancelButtonText: "取消" },
      );
    } catch {
      return;
    }
  }

  loading.value = true;
  disabled.value = true;
  try {
    await reloadChromeExtension();
    ElMessage.info("插件正在重新加载…");
    await waitForBridgeReconnect();
    ElMessage.success("插件已重新加载并重新连接");
    emit("reloaded");
  } catch (err) {
    ElMessage.error(err?.message || "重新加载插件失败");
  } finally {
    loading.value = false;
    disabled.value = false;
  }
}
</script>
