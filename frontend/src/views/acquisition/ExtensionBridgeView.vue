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

    <AcquisitionStatsCards :data="dashboard" :loading="loading" class="panel-block" />
    </div>

    <el-tabs v-model="activeTab" class="panel-block page-tabs">
      <el-tab-pane label="采集任务" name="collect">
        <el-card shadow="never" class="list-card">
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
      </el-tab-pane>

      <el-tab-pane label="评论触达" name="outreach">
        <el-card shadow="never" class="list-card">
          <template #header>
            <div class="card-header">
              <span>评论触达任务</span>
              <div class="quota-hint">今日剩余 {{ quota.remaining ?? "—" }} / {{ quota.daily_limit ?? "—" }}</div>
            </div>
          </template>
          <div class="task-list-scroll">
          <el-table v-loading="loading" :data="outreachTasks" empty-text="暂无触达任务">
            <el-table-column prop="name" label="名称" min-width="140" />
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag size="small" :type="statusTagType(row.status)">{{ statusLabel(row.status) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="completed_count" label="成功" width="72" align="right" />
            <el-table-column prop="failed_count" label="失败" width="72" align="right" />
            <el-table-column prop="pending_count" label="待执行" width="80" align="right" />
            <el-table-column label="" width="56" align="center" fixed="right">
              <template #default="{ row }">
                <OutreachTaskRowActions :row="row" @action="onOutreachTaskAction(row, $event)" />
              </template>
            </el-table-column>
          </el-table>
          </div>
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <CreateExtensionAutoTaskDialog v-model="createCollectOpen" @created="refreshAll" />

    <AcquisitionOutreachModal
      v-model="outreachOpen"
      :job="outreachJob"
      :initial-view="outreachView"
      :loading="outreachLoading"
    />

    <el-dialog v-model="createOutreachOpen" title="创建评论触达" width="560px">
      <el-form label-width="120px">
        <el-form-item label="来源采集">
          <el-input :model-value="outreachForm.source_keyword" disabled />
        </el-form-item>
        <el-form-item label="回复预设">
          <el-select
            v-model="selectedPresetId"
            clearable
            placeholder="从预设选择（可选）"
            style="width: 100%"
            @change="applyPreset"
          >
            <el-option v-for="item in replyPresets" :key="item.id" :label="item.label" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="回复文案" required>
          <el-input
            v-model="outreachForm.reply_text"
            type="textarea"
            :rows="4"
            placeholder="将回复到采集到的评论"
          />
        </el-form-item>
        <el-form-item label="触达条数">
          <el-input-number v-model="outreachForm.max_items" :min="1" :max="50" />
        </el-form-item>
        <el-form-item label="最低点赞">
          <el-input-number v-model="outreachForm.min_digg_count" :min="0" :max="10000" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createOutreachOpen = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitOutreach">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import AcquisitionOutreachModal from "../../components/AcquisitionOutreachModal.vue";
import AcquisitionStatsCards from "../../components/AcquisitionStatsCards.vue";
import CollectJobRowActions from "../../components/CollectJobRowActions.vue";
import CreateExtensionAutoTaskDialog from "../../components/CreateExtensionAutoTaskDialog.vue";
import MetricLink from "../../components/MetricLink.vue";
import OutreachTaskRowActions from "../../components/OutreachTaskRowActions.vue";
import {
  createOutreachTask,
  deleteCollectJob,
  fetchBridgeStatus,
  fetchReplyQuota,
  listCollectJobs,
  listOutreachTasks,
  pauseCollectJob,
  pauseOutreachTask,
  startCollectJob,
  startOutreachTask,
} from "../../api/localService";
import { extensionJobTargetCount, loadCollectJobForModal } from "../../utils/extensionCollectJobs";
import { loadReplyPresetOptions } from "../../utils/localPresets";
import {
  getExtensionSetupStatus,
  isDesktopMode,
  isTauriApp,
  launchChromeExtension,
  openExtensionFolder,
} from "../../utils/desktopApp";

const loading = ref(false);
const submitting = ref(false);
const launchingExtension = ref(false);
const desktopMode = ref(false);
const extensionSetup = ref({ message: "" });
const collectJobs = ref([]);
const outreachTasks = ref([]);
const bridgeStatus = ref({ connected_clients: 0 });
const quota = ref({ remaining: 0, daily_limit: 50 });
const createCollectOpen = ref(false);
const createOutreachOpen = ref(false);
const activeTab = ref("collect");
const replyPresets = ref([]);
const selectedPresetId = ref("");
let pollTimer = null;

const outreachForm = reactive({
  source_job_id: "",
  source_keyword: "",
  reply_text: "",
  max_items: 10,
  min_digg_count: 0,
});

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

const dashboard = computed(() => {
  const jobs = collectJobs.value || [];
  const tasks = outreachTasks.value || [];
  const runningJobs = jobs.filter((row) => row.status === "running").length;
  const runningTasks = tasks.filter((row) => row.status === "running").length;
  const queued = jobs.filter((row) => row.status === "pending").length;
  const totalComments = jobs.reduce((sum, row) => sum + Number(row.comment_count || 0), 0);
  const totalReplies = jobs.reduce((sum, row) => sum + Number(row.reply_count || 0), 0);
  const totalDm = jobs.reduce((sum, row) => sum + Number(row.dm_count || 0), 0);
  const totalFollow = jobs.reduce((sum, row) => sum + Number(row.follow_count || 0), 0);
  return {
    running_tasks: runningJobs + runningTasks,
    queued_tasks: queued,
    precise_customers: 0,
    total_leads: totalComments,
    dm_count: totalDm,
    follow_count: totalFollow + totalReplies,
  };
});

function jobDisplayName(row) {
  return row.name || `关键词获客-${row.keyword}`;
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

function platformLabel(platform) {
  const map = { douyin: "抖音", xiaohongshu: "小红书", kuaishou: "快手" };
  return map[platform] || platform || "抖音";
}

function statusLabel(status) {
  const map = {
    pending: "待执行",
    running: "运行中",
    completed: "已完成",
    failed: "失败",
    paused: "已暂停",
  };
  return map[status] || status || "—";
}

function statusTagType(status) {
  const map = {
    pending: "info",
    running: "primary",
    completed: "success",
    failed: "danger",
    paused: "warning",
  };
  return map[status] || "info";
}

function onCollectJobAction(row, action) {
  if (action === "view") openCollectData(row, "all");
  else if (action === "start") onStartCollect(row);
  else if (action === "pause") onPauseCollect(row);
  else if (action === "outreach") openOutreachDialog(row);
  else if (action === "delete") onDeleteCollect(row);
}

function onOutreachTaskAction(row, action) {
  if (action === "start") onStartOutreach(row);
  else if (action === "pause") onPauseOutreach(row);
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
    const [status, quotaData, jobs, tasks] = await Promise.all([
      fetchBridgeStatus(),
      fetchReplyQuota().catch(() => ({ remaining: 0, daily_limit: 50 })),
      listCollectJobs(),
      listOutreachTasks(),
    ]);
    bridgeStatus.value = status;
    quota.value = quotaData;
    collectJobs.value = (Array.isArray(jobs) ? jobs : []).filter(
      (row) => row.job_type !== "manual",
    );
    outreachTasks.value = Array.isArray(tasks) ? tasks : [];
  } catch (err) {
    ElMessage.error(err?.response?.data?.error || err?.message || "连接 local-service 失败");
  } finally {
    loading.value = false;
  }
}

async function loadReplyPresets() {
  try {
    replyPresets.value = await loadReplyPresetOptions();
  } catch {
    replyPresets.value = [];
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

function openOutreachDialog(row) {
  outreachForm.source_job_id = row.id;
  outreachForm.source_keyword = row.keyword;
  outreachForm.reply_text = "";
  outreachForm.max_items = 10;
  outreachForm.min_digg_count = 0;
  selectedPresetId.value = "";
  createOutreachOpen.value = true;
  activeTab.value = "outreach";
}

function applyPreset(presetId) {
  const preset = replyPresets.value.find((row) => row.id === presetId);
  if (preset?.content) outreachForm.reply_text = preset.content;
}

async function submitOutreach() {
  const replyText = outreachForm.reply_text.trim();
  if (!replyText) {
    ElMessage.warning("请输入回复文案");
    return;
  }
  submitting.value = true;
  try {
    const result = await createOutreachTask({
      source_job_id: outreachForm.source_job_id,
      reply_text: replyText,
      max_items: outreachForm.max_items,
      min_digg_count: outreachForm.min_digg_count,
      name: `${outreachForm.source_keyword} 评论触达`,
    });
    createOutreachOpen.value = false;
    ElMessage.success(`触达任务已创建，共 ${result.inserted_items || 0} 条`);
    await refreshAll();
  } catch (err) {
    ElMessage.error(err?.response?.data?.error || err?.message || "创建触达失败");
  } finally {
    submitting.value = false;
  }
}

async function onStartOutreach(row) {
  try {
    await startOutreachTask(row.id);
    ElMessage.success("触达任务已开始");
    await refreshAll();
  } catch (err) {
    ElMessage.error(err?.response?.data?.error || err?.message || "启动失败");
  }
}

async function onPauseOutreach(row) {
  try {
    await pauseOutreachTask(row.id);
    ElMessage.success("触达任务已暂停");
    await refreshAll();
  } catch (err) {
    ElMessage.error(err?.response?.data?.error || err?.message || "暂停失败");
  }
}

onMounted(async () => {
  desktopMode.value = await isDesktopMode();
  await Promise.all([refreshAll(), loadReplyPresets(), refreshExtensionSetup()]);
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

.page-tabs {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.page-tabs :deep(.el-tabs__header) {
  flex-shrink: 0;
  margin-bottom: 12px;
}

.page-tabs :deep(.el-tabs__content) {
  flex: 1;
  min-height: 0;
}

.page-tabs :deep(.el-tab-pane) {
  height: 100%;
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
