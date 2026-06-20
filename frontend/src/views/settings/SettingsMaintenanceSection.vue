<template>
  <section class="settings-section panel">
    <header class="section-head">
      <h2 class="section-title">维护</h2>
      <p class="section-desc">
        修复运行时缓存、导出诊断日志。不会删除浏览器中的平台登录态与本地预设。
      </p>
    </header>

    <p v-if="!desktopMode" class="hint-text">
      当前为 Web 开发模式，以下功能仅在桌面客户端可用。
    </p>

    <div v-else class="maintenance-cards">
      <article class="maintenance-card">
        <h3 class="card-title">修复并重启</h3>
        <p class="card-desc">
          清除 <strong>runtime-work</strong> 与 <strong>bundle-cache</strong>，下次启动会从安装包重新解压后端与前端。
          你的 <strong>storage</strong>（账号、Skill、规则）不会被删除。
        </p>
        <el-button type="primary" :loading="repairLoading" @click="handleRepair">
          修复并重启
        </el-button>
      </article>

      <article class="maintenance-card">
        <h3 class="card-title">导出诊断日志</h3>
        <p class="card-desc">
          下载 ZIP，包含路径快照、bundle 完整性检查、Skill 注册表摘要与最近日志（不含 API Key）。
        </p>
        <el-button :loading="exportLoading" @click="handleExport">
          导出诊断日志
        </el-button>
      </article>
    </div>

    <p v-if="lastRepairMessage" class="repair-result">{{ lastRepairMessage }}</p>
  </section>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  downloadDesktopDiagnostics,
  fetchDesktopHealth,
  repairDesktopRuntime,
} from "../../api/desktopMaintenance";
import { isDesktopMode, restartDesktopApp, saveBlobDownload } from "../../utils/desktopApp";

const desktopMode = ref(false);
const repairLoading = ref(false);
const exportLoading = ref(false);
const lastRepairMessage = ref("");

async function refreshDesktopMode() {
  desktopMode.value = await isDesktopMode();
}

async function handleRepair() {
  try {
    await ElMessageBox.confirm(
      "将清除运行时缓存目录并重启应用。账号与 Skill 配置会保留。是否继续？",
      "修复并重启",
      { type: "warning", confirmButtonText: "修复并重启", cancelButtonText: "取消" },
    );
  } catch {
    return;
  }

  repairLoading.value = true;
  lastRepairMessage.value = "";
  try {
    const result = await repairDesktopRuntime();
    lastRepairMessage.value = result.message || "修复完成";
    ElMessage.success(result.message || "修复完成，正在重启…");

    const restarted = await restartDesktopApp();
    if (!restarted) {
      await ElMessageBox.alert(
        "缓存已清除。请从系统托盘或任务栏完全退出应用后重新打开，修复才会生效。",
        "请手动重启",
        { type: "info", confirmButtonText: "我知道了" },
      );
      window.location.reload();
    }
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || err.message || "修复失败");
  } finally {
    repairLoading.value = false;
  }
}

async function handleExport() {
  exportLoading.value = true;
  try {
    const { blob, filename } = await downloadDesktopDiagnostics();
    saveBlobDownload(blob, filename);
    ElMessage.success("诊断日志已开始下载");
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || err.message || "导出失败");
  } finally {
    exportLoading.value = false;
  }
}

onMounted(async () => {
  await refreshDesktopMode();
  if (desktopMode.value) {
    try {
      await fetchDesktopHealth();
    } catch {
      // ignore preview errors
    }
  }
});
</script>

<style scoped>
.maintenance-cards {
  display: grid;
  gap: 12px;
}

.maintenance-card {
  padding: 14px 16px;
  border: 1px solid var(--border, #e2e8f0);
  border-radius: 12px;
  background: #fafbfc;
}

.card-title {
  margin: 0 0 8px;
  font-size: 15px;
  font-weight: 700;
}

.card-desc {
  margin: 0 0 12px;
  font-size: 13px;
  color: var(--muted);
  line-height: 1.55;
}

.card-desc strong {
  color: var(--text);
}

.repair-result {
  margin-top: 12px;
  padding: 10px 12px;
  border-radius: 8px;
  background: #ecfdf5;
  color: #047857;
  font-size: 13px;
}
</style>
