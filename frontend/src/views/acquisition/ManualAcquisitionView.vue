<template>
  <div class="manual-acquisition-page">
    <div class="page-toolbar">
      <header class="page-header">
        <div>
          <h1 class="page-title">手动获客</h1>
          <p class="page-subtitle">通过博主主页或单条视频链接发起获客，跟踪抓取进度与评论线索。</p>
        </div>
        <div class="header-actions">
          <el-tag :type="bridgeTagType">{{ bridgeLabel }}</el-tag>
          <el-button type="primary" class="create-btn" @click="createOpen = true">+ 创建任务</el-button>
          <el-button @click="refreshAll" :loading="loading">刷新</el-button>
        </div>
      </header>

      <AcquisitionStatsCards :data="dashboard" :loading="loading" class="panel-block" />
    </div>

    <el-card shadow="never" class="list-card panel-block">
      <template #header>
        <div class="card-header">
          <span>手动获客任务</span>
          <el-button type="primary" size="small" @click="createOpen = true">+ 创建任务</el-button>
        </div>
      </template>
      <div class="task-list-scroll">
        <el-table v-loading="loading" :data="manualJobs" empty-text="暂无手动获客任务">
          <el-table-column label="任务名称" min-width="160" show-overflow-tooltip>
            <template #default="{ row }">{{ jobDisplayName(row) }}</template>
          </el-table-column>
          <el-table-column label="渠道" width="88">
            <template #default="{ row }">
              <el-tag size="small" type="info">{{ platformLabel(row.platform) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="获客方式" width="120" show-overflow-tooltip>
            <template #default="{ row }">{{ manualIntentLabel(row.config?.intent) }}</template>
          </el-table-column>
          <el-table-column label="预设抓取数量" width="112" align="right">
            <template #default="{ row }">{{ extensionJobTargetCount(row) }}</template>
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
          <el-table-column label="精准客户" width="88" align="right">
            <template #default="{ row }">
              <MetricLink
                :value="row.precise_count || 0"
                :clickable="Number(row.precise_count) > 0"
                @click="openCollectData(row, 'precise')"
              />
            </template>
          </el-table-column>
          <el-table-column label="私信数" width="80" align="right">
            <template #default="{ row }">
              <MetricLink
                :value="row.dm_count || 0"
                always-clickable
                @click="openOutreachMetric(row, 'dm')"
              />
            </template>
          </el-table-column>
          <el-table-column label="关注数" width="80" align="right">
            <template #default="{ row }">
              <MetricLink
                :value="row.follow_count || 0"
                always-clickable
                @click="openOutreachMetric(row, 'follow')"
              />
            </template>
          </el-table-column>
          <el-table-column label="状态" width="108">
            <template #default="{ row }">
              <CollectJobStatusTag :row="row" @continue="onStartCollect" />
            </template>
          </el-table-column>
          <el-table-column prop="video_count" label="视频数" width="72" align="right" />
          <el-table-column label="创建时间" width="160">
            <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="" width="56" align="center">
            <template #default="{ row }">
              <CollectJobRowActions :row="row" @action="onCollectJobAction(row, $event)" />
            </template>
          </el-table-column>
        </el-table>
      </div>
    </el-card>

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
import AcquisitionStatsCards from "../../components/AcquisitionStatsCards.vue";
import CollectJobRowActions from "../../components/CollectJobRowActions.vue";
import CollectJobStatusTag from "../../components/CollectJobStatusTag.vue";
import CreateExtensionManualTaskDialog from "../../components/CreateExtensionManualTaskDialog.vue";
import MetricLink from "../../components/MetricLink.vue";
import {
  deleteCollectJob,
  evaluateCollectJob,
  fetchBridgeStatus,
  listCollectJobs,
  pauseCollectJob,
  startCollectJob,
} from "../../api/localService";
import { manualAccountLabel, manualIntentLabel } from "../../utils/acquisitionJobs";
import {
  computeExtensionDashboard,
  extensionJobTargetCount,
  loadCollectJobForModal,
} from "../../utils/extensionCollectJobs";
import { alertOutreachRiskIfZero } from "../../utils/outreachRisk";
import { collectJobStartMessage, collectJobStartSuccessMessage } from "../../utils/collectJobStart";

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

const dashboard = computed(() => computeExtensionDashboard(manualJobs.value));

const bridgeLabel = computed(() => {
  const count = Number(bridgeStatus.value.connected_clients || 0);
  return count > 0 ? `插件已连接 (${count})` : "插件未连接";
});

const bridgeTagType = computed(() =>
  Number(bridgeStatus.value.connected_clients || 0) > 0 ? "success" : "warning",
);

function jobDisplayName(row) {
  return row.name || manualAccountLabel(row);
}

function platformLabel(platform) {
  const map = { douyin: "抖音", xiaohongshu: "小红书", kuaishou: "快手" };
  return map[platform] || platform || "抖音";
}

function onCollectJobAction(row, action) {
  if (action === "view") openCollectData(row, "all");
  else if (action === "evaluate") onEvaluateCollect(row);
  else if (action === "start") onStartCollect(row);
  else if (action === "pause") onPauseCollect(row);
  else if (action === "delete") onDeleteCollect(row);
}

async function onEvaluateCollect(row) {
  try {
    ElMessage.info("正在按任务评估标准识别精准客户…");
    const result = await evaluateCollectJob(row.id);
    const precise = Number(result?.precise_count ?? result?.precise ?? 0);
    ElMessage.success(`评估完成：${precise} 条精准客户 / ${result?.evaluated ?? 0} 条已评估`);
    await refreshAll();
  } catch (err) {
    ElMessage.error(err?.response?.data?.error || err?.message || "评估失败");
  }
}

function formatTime(ts) {
  const num = Number(ts);
  if (!Number.isFinite(num) || num <= 0) return "—";
  const ms = num > 1e12 ? num : num * 1000;
  return new Date(ms).toLocaleString("zh-CN", { hour12: false });
}

async function refreshAll({ silent = false } = {}) {
  if (!silent) loading.value = true;
  try {
    const [status, jobs] = await Promise.all([fetchBridgeStatus(), listCollectJobs()]);
    bridgeStatus.value = status;
    allJobs.value = Array.isArray(jobs) ? jobs : [];
  } catch (err) {
    if (!silent) {
      ElMessage.error(err?.response?.data?.error || err?.message || "连接 local-service 失败");
    }
  } finally {
    if (!silent) loading.value = false;
  }
  schedulePoll();
}

function hasActiveCollectJobs() {
  return manualJobs.value.some((j) => j.status === "running");
}

function schedulePoll() {
  if (pollTimer) window.clearInterval(pollTimer);
  const interval = hasActiveCollectJobs() ? 2000 : 8000;
  pollTimer = window.setInterval(() => refreshAll({ silent: true }), interval);
}

async function onStartCollect(row) {
  if (!row?.id) return;
  const previousStatus = row.status;
  const idx = allJobs.value.findIndex((item) => item.id === row.id);
  if (idx >= 0) {
    allJobs.value[idx] = {
      ...allJobs.value[idx],
      status: "running",
      error_message: "",
    };
  }
  schedulePoll();
  const loadingMsg = ElMessage.info({
    message: collectJobStartMessage(previousStatus),
    duration: 0,
  });
  try {
    await startCollectJob(row.id);
    loadingMsg.close();
    ElMessage.success(collectJobStartSuccessMessage(previousStatus));
    await refreshAll({ silent: true });
  } catch (err) {
    loadingMsg.close();
    ElMessage.error(err?.response?.data?.error || err?.message || "启动失败");
    await refreshAll({ silent: true });
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

async function openOutreachMetric(row, view) {
  const countMap = { dm: row.dm_count, follow: row.follow_count };
  if (await alertOutreachRiskIfZero(countMap[view])) return;
  await openCollectData(row, view);
}

async function openCollectData(row, view = "all") {
  const countMap = {
    all: row.comment_count,
    precise: row.precise_count,
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
  const name = jobDisplayName(row);
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
});

onUnmounted(() => {
  if (pollTimer) window.clearInterval(pollTimer);
});
</script>

<style scoped>
.manual-acquisition-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
  height: 100%;
  min-height: 0;
  overflow: hidden;
}

.page-toolbar {
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.list-card {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.list-card :deep(.el-card__body) {
  flex: 1;
  min-height: 0;
  padding: 0;
}

.task-list-scroll {
  height: 100%;
  overflow-y: auto;
  overflow-x: auto;
  padding: 0 16px 16px;
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

.create-btn {
  flex-shrink: 0;
  padding: 0 20px;
}

.panel-block {
  width: 100%;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
</style>
