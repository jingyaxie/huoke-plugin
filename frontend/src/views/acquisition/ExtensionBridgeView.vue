<template>
  <div class="extension-bridge-page">
    <div class="page-toolbar">
      <header class="page-header">
      <div>
        <h1 class="page-title">自动获客</h1>
        <p class="page-subtitle">创建和管理自动获客任务，跟踪抓取进度与评论线索。</p>
      </div>
      <div class="header-actions">
        <el-tag :type="bridgeTagType">{{ bridgeLabel }}</el-tag>
        <el-button type="primary" class="create-btn" @click="createCollectOpen = true">+ 创建任务</el-button>
        <el-button @click="refreshAll" :loading="loading">刷新</el-button>
      </div>
    </header>

    <el-alert
      v-if="bridgeStatus.connected_clients === 0"
      type="warning"
      :closable="false"
      show-icon
      title="Chrome 插件未连接"
      class="panel-block"
    >
      <template #default>
        <template v-if="desktopMode">
          <p>{{ extensionSetup.message || "正在准备浏览器插件…" }}</p>
          <div class="extension-setup-actions">
            <el-button type="primary" :loading="launchingExtension" @click="onLaunchChromeExtension">
              启动浏览器插件
            </el-button>
            <el-button @click="onOpenExtensionFolder">打开插件目录</el-button>
          </div>
          <p class="field-hint">
            安装版会自动加载插件并打开抖音。首次使用请在 Chrome 窗口登录抖音；之后点击「启动浏览器插件」即可。
          </p>
        </template>
        <template v-else>
          请确认：① 已在 <code>chrome://extensions</code> 加载 <code>extension/dist</code> 并重新加载；
          ② 插件图标角标为 <strong>OK</strong>；
          ③ 本地服务已启动（<code>npm run dev</code>，端口 18766）。
          也可先到
          <router-link to="/platform-login">平台登录</router-link>
          页在 Chrome 打开抖音并登录。
        </template>
      </template>
    </el-alert>

    <ExtensionVersionAlert
      v-if="desktopMode"
      class="panel-block"
      :bridge-status="bridgeStatus"
      :extension-setup="extensionSetup"
      :can-launch="true"
      :launching="launchingExtension"
      @launch="onLaunchChromeExtension"
      @open-folder="onOpenExtensionFolder"
    />

    <AcquisitionStatsCards :data="dashboard" :loading="loading" class="panel-block" />
    </div>

    <el-card shadow="never" class="list-card panel-block">
      <template #header>
        <div class="card-header">
          <span>关键词采集</span>
          <el-button type="primary" size="small" @click="createCollectOpen = true">+ 创建任务</el-button>
        </div>
      </template>
      <div class="task-list-scroll">
      <el-table v-loading="loading" :data="collectJobs" empty-text="暂无采集任务">
            <el-table-column label="任务名称" min-width="160" show-overflow-tooltip>
              <template #default="{ row }">{{ jobDisplayName(row) }}</template>
            </el-table-column>
            <el-table-column label="渠道" width="88">
              <template #default="{ row }">
                <el-tag size="small" type="info">{{ platformLabel(row.platform) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="产品关键词" min-width="120" show-overflow-tooltip>
              <template #default="{ row }">{{ row.keyword }}</template>
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
            <el-table-column label="状态" width="108">
              <template #default="{ row }">
                <CollectJobStatusTag :row="row" @continue="onStartCollect" />
              </template>
            </el-table-column>
            <el-table-column prop="video_count" label="视频数" width="72" align="right" />
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
    </el-card>

    <CreateExtensionAutoTaskDialog v-model="createCollectOpen" @created="refreshAll" />

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
import CreateExtensionAutoTaskDialog from "../../components/CreateExtensionAutoTaskDialog.vue";
import ExtensionVersionAlert from "../../components/ExtensionVersionAlert.vue";
import MetricLink from "../../components/MetricLink.vue";
import {
  deleteCollectJob,
  evaluateCollectJob,
  fetchBridgeStatus,
  listCollectJobs,
  pauseCollectJob,
  startCollectJob,
} from "../../api/localService";
import { extensionJobTargetCount, computeExtensionDashboard, loadCollectJobForModal } from "../../utils/extensionCollectJobs";
import {
  getExtensionSetupStatus,
  isDesktopMode,
  isTauriApp,
  launchChromeExtension,
  openExtensionFolder,
} from "../../utils/desktopApp";

const loading = ref(false);
const launchingExtension = ref(false);
const desktopMode = ref(false);
const extensionSetup = ref({ message: "" });
const collectJobs = ref([]);
const bridgeStatus = ref({ connected_clients: 0 });
const createCollectOpen = ref(false);
let pollTimer = null;

const outreachOpen = ref(false);
const outreachLoading = ref(false);
const outreachJob = ref(null);
const outreachView = ref("all");

const bridgeLabel = computed(() => {
  const count = Number(bridgeStatus.value.connected_clients || 0);
  return count > 0 ? `插件已连接 (${count})` : "插件未连接";
});

const bridgeTagType = computed(() =>
  Number(bridgeStatus.value.connected_clients || 0) > 0 ? "success" : "warning",
);

const dashboard = computed(() => computeExtensionDashboard(collectJobs.value));

function jobDisplayName(row) {
  return row.name || `关键词获客-${row.keyword}`;
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

async function refreshExtensionSetup() {
  if (!desktopMode.value || !isTauriApp()) return;
  try {
    extensionSetup.value = await getExtensionSetupStatus();
  } catch {
    extensionSetup.value = { message: "读取插件状态失败" };
  }
}

async function onLaunchChromeExtension() {
  launchingExtension.value = true;
  try {
    extensionSetup.value = await launchChromeExtension();
    await refreshAll();
    if (Number(bridgeStatus.value.connected_clients || 0) > 0) {
      ElMessage.success("Chrome 插件已连接");
    } else {
      ElMessage.warning("已启动 Chrome，请在窗口中登录抖音并保持页面打开");
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

async function refreshAll() {
  loading.value = true;
  try {
    const [status, jobs] = await Promise.all([fetchBridgeStatus(), listCollectJobs()]);
    bridgeStatus.value = status;
    collectJobs.value = (Array.isArray(jobs) ? jobs : []).filter(
      (row) => row.job_type !== "manual",
    );
  } catch (err) {
    ElMessage.error(err?.response?.data?.error || err?.message || "连接 local-service 失败");
  } finally {
    loading.value = false;
  }
}

async function onStartCollect(row) {
  const loadingMsg = ElMessage.info({
    message: row.status === "running" ? "正在重新启动采集…" : "正在启动采集，请稍候…",
    duration: 0,
  });
  try {
    await startCollectJob(row.id);
    loadingMsg.close();
    ElMessage.success("采集已开始，请保持抖音标签页激活");
    await refreshAll();
  } catch (err) {
    loadingMsg.close();
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
  desktopMode.value = await isDesktopMode();
  void refreshAll();
  void refreshExtensionSetup();
  pollTimer = window.setInterval(() => {
    refreshAll();
    refreshExtensionSetup();
  }, 8000);
});

onUnmounted(() => {
  if (pollTimer) window.clearInterval(pollTimer);
});
</script>

<style scoped>
.extension-bridge-page {
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

.quota-hint {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.field-hint {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.extension-setup-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin: 12px 0 4px;
}

.detail-body h4 {
  margin: 0 0 10px;
  font-size: 14px;
}

.detail-comments-title {
  margin-top: 18px;
}

.muted {
  color: var(--el-text-color-secondary);
  font-weight: 400;
}
</style>
