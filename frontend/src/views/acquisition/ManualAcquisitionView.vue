<template>
  <div class="acquisition-page">
    <header class="page-header">
      <div>
        <h1 class="page-title">手动获客任务列表</h1>
        <p class="page-subtitle">通过博主主页或单条视频链接发起获客，登录态由 Chrome 管理。</p>
      </div>
      <div class="header-actions">
        <el-tag :type="bridgeTagType">{{ bridgeLabel }}</el-tag>
        <el-button type="primary" class="create-btn" @click="createOpen = true">+ 创建任务</el-button>
        <el-button @click="refreshAll" :loading="loading">刷新</el-button>
      </div>
    </header>

    <div class="task-list-scroll table-card">
    <el-table v-loading="loading" :data="manualJobs" empty-text="暂无手动获客任务">
      <el-table-column label="账号名称" min-width="150" show-overflow-tooltip>
        <template #default="{ row }">{{ manualAccountLabel(row) }}</template>
      </el-table-column>
      <el-table-column label="头像" width="72" align="center">
        <template #default="{ row }">
          <el-avatar :size="28">{{ avatarInitial(manualAccountLabel(row)) }}</el-avatar>
        </template>
      </el-table-column>
      <el-table-column label="获客方式" width="130">
        <template #default="{ row }">{{ manualIntentLabel(row.config?.intent) }}</template>
      </el-table-column>
      <el-table-column label="渠道" width="88">
        <template #default="{ row }">
          <el-tag size="small" type="info">{{ platformLabel(row.platform) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="实际抓取总线索" width="120" align="right">
        <template #default="{ row }">
          <MetricLink
            :value="row.comment_count || 0"
            :clickable="Number(row.comment_count) > 0"
            @click="openCollectData(row, 'all')"
          />
        </template>
      </el-table-column>
      <el-table-column label="评论数" width="80" align="right">
        <template #default="{ row }">
          <MetricLink
            :value="row.reply_count || 0"
            :clickable="Number(row.reply_count) > 0"
            @click="openCollectData(row, 'reply')"
          />
        </template>
      </el-table-column>
      <el-table-column label="私信数" width="80" align="right">
        <template #default="{ row }">
          <MetricLink
            :value="row.dm_count || 0"
            :clickable="Number(row.dm_count) > 0"
            @click="openCollectData(row, 'dm')"
          />
        </template>
      </el-table-column>
      <el-table-column label="关注数" width="80" align="right">
        <template #default="{ row }">
          <MetricLink
            :value="row.follow_count || 0"
            :clickable="Number(row.follow_count) > 0"
            @click="openCollectData(row, 'follow')"
          />
        </template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag size="small" :type="statusTagType(row.status)">{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="创建时间" width="160">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="" width="56" align="center" fixed="right">
        <template #default="{ row }">
          <CollectJobRowActions :row="row" @action="onCollectJobAction(row, $event)" />
        </template>
      </el-table-column>
    </el-table>
    </div>

    <CreateExtensionManualTaskDialog v-model="createOpen" @created="refreshAll" />

    <AcquisitionOutreachModal
      v-model="outreachOpen"
      :job="outreachJob"
      :initial-view="outreachView"
      :loading="outreachLoading"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import AcquisitionOutreachModal from "../../components/AcquisitionOutreachModal.vue";
import CollectJobRowActions from "../../components/CollectJobRowActions.vue";
import CreateExtensionManualTaskDialog from "../../components/CreateExtensionManualTaskDialog.vue";
import MetricLink from "../../components/MetricLink.vue";
import {
  deleteCollectJob,
  fetchBridgeStatus,
  listCollectJobs,
  pauseCollectJob,
  startCollectJob,
} from "../../api/localService";
import {
  avatarInitial,
  manualAccountLabel,
  manualIntentLabel,
} from "../../utils/acquisitionJobs";
import { loadCollectJobForModal } from "../../utils/extensionCollectJobs";

const loading = ref(false);
const allJobs = ref([]);
const bridgeStatus = ref({ connected_clients: 0 });
const createOpen = ref(false);
let pollTimer = null;

const outreachOpen = ref(false);
const outreachLoading = ref(false);
const outreachJob = ref(null);
const outreachView = ref("all");

const manualJobs = computed(() =>
  (allJobs.value || []).filter((row) => row.job_type === "manual"),
);

const bridgeLabel = computed(() => {
  const count = Number(bridgeStatus.value.connected_clients || 0);
  return count > 0 ? `插件已连接 (${count})` : "插件未连接";
});

const bridgeTagType = computed(() =>
  Number(bridgeStatus.value.connected_clients || 0) > 0 ? "success" : "warning",
);

function platformLabel(platform) {
  if (platform === "xiaohongshu") return "小红书";
  if (platform === "kuaishou") return "快手";
  return "抖音";
}

function statusLabel(status) {
  const map = {
    pending: "待执行",
    running: "运行中",
    completed: "已完成",
    failed: "失败",
  };
  return map[status] || status || "—";
}

function statusTagType(status) {
  const map = {
    pending: "info",
    running: "primary",
    completed: "success",
    failed: "danger",
  };
  return map[status] || "info";
}

function onCollectJobAction(row, action) {
  if (action === "view") openCollectData(row, "all");
  else if (action === "start") onStartCollect(row);
  else if (action === "pause") onPauseCollect(row);
  else if (action === "delete") onDeleteCollect(row);
}

function formatTime(ts) {
  const num = Number(ts);
  if (!Number.isFinite(num) || num <= 0) return "—";
  const ms = num > 1e12 ? num : num * 1000;
  return new Date(ms).toLocaleString("zh-CN", { hour12: false });
}

async function refreshAll() {
  loading.value = true;
  try {
    const [status, jobs] = await Promise.all([fetchBridgeStatus(), listCollectJobs()]);
    bridgeStatus.value = status;
    allJobs.value = Array.isArray(jobs) ? jobs : [];
  } catch (err) {
    ElMessage.error(err?.response?.data?.error || err?.message || "连接 local-service 失败");
  } finally {
    loading.value = false;
  }
}

async function onStartCollect(row) {
  try {
    await startCollectJob(row.id);
    ElMessage.success("采集已开始，请保持抖音标签页激活");
    await refreshAll();
  } catch (err) {
    ElMessage.error(err?.response?.data?.error || err?.message || "启动失败");
  }
}

async function onPauseCollect(row) {
  try {
    await pauseCollectJob(row.id);
    ElMessage.success("采集任务已暂停");
    await refreshAll();
  } catch (err) {
    ElMessage.error(err?.response?.data?.error || err?.message || "暂停失败");
  }
}

async function openCollectData(row, view = "all") {
  const countMap = {
    all: row.comment_count,
    reply: row.reply_count,
    dm: row.dm_count,
    follow: row.follow_count,
  };
  if (Number(countMap[view] || 0) <= 0) return;
  outreachView.value = view;
  outreachOpen.value = true;
  outreachLoading.value = true;
  outreachJob.value = null;
  try {
    outreachJob.value = await loadCollectJobForModal(row);
  } catch (err) {
    outreachOpen.value = false;
    ElMessage.error(err?.response?.data?.error || err?.message || "加载采集数据失败");
  } finally {
    outreachLoading.value = false;
  }
}

async function onDeleteCollect(row) {
  const name = row.name || manualAccountLabel(row);
  try {
    await ElMessageBox.confirm(`确定删除任务「${name}」？关联的视频和评论数据将一并删除。`, "删除任务", {
      type: "warning",
      confirmButtonText: "删除",
      cancelButtonText: "取消",
    });
  } catch {
    return;
  }
  try {
    await deleteCollectJob(row.id);
    ElMessage.success("任务已删除");
    if (outreachJob.value?.job_id === row.id) outreachOpen.value = false;
    await refreshAll();
  } catch (err) {
    ElMessage.error(err?.response?.data?.error || err?.message || "删除失败");
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
  height: 100%;
  min-height: 0;
  overflow: hidden;
}

.page-header {
  flex-shrink: 0;
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.create-btn {
  flex-shrink: 0;
  padding: 0 20px;
}

.panel-block {
  width: 100%;
}

.table-card {
  flex: 1;
  min-height: 0;
  padding: 12px 12px 0;
  background: #fff;
  border-radius: 12px;
  overflow: hidden;
}

.task-list-scroll {
  height: 100%;
  overflow-y: auto;
  overflow-x: auto;
}

.detail-body h4 {
  margin: 0 0 10px;
  font-size: 14px;
}

.detail-url {
  margin: 0 0 12px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  word-break: break-all;
}

.detail-comments-title {
  margin-top: 18px;
}
</style>
