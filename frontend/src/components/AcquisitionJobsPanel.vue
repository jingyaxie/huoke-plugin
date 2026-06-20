<template>
  <div class="acquisition-jobs-panel">
    <AcquisitionStatsCards :data="dashboard" :loading="loading" class="panel-block" />

    <AcquisitionTaskFilters
      v-model="filter"
      class="panel-block"
      @submit="onFilterSubmit"
    />

    <el-alert
      v-if="hasQueuedJobs"
      type="info"
      :closable="false"
      show-icon
      title="存在排队中的任务，Worker 将按顺序自动执行；若长时间无进展，请确认后端服务正常并已绑定平台账号。"
    />

    <el-alert
      v-if="hasSuspendedJobs"
      type="warning"
      :closable="false"
      show-icon
      title="部分任务已挂起（抓取或触达步骤失败），请点击操作列「继续执行」重试，或检查账号登录与浏览器环境。"
    />

    <el-alert
      v-if="hasFailedJobs"
      type="warning"
      :closable="false"
      show-icon
      title="部分任务失败，常见原因：Cookie 失效、平台限流、抓取无结果或执行超时。"
    />

    <div class="table-card panel">
      <el-table
        v-loading="loading"
        :data="pageRows"
        class="jobs-table"
        :empty-text="emptyText"
      >
      <template v-if="mode === 'auto'">
        <el-table-column label="任务名称" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">{{ row.name }}</template>
        </el-table-column>
        <el-table-column label="账号" width="120" show-overflow-tooltip>
          <template #default="{ row }">{{ row.account_label || "—" }}</template>
        </el-table-column>
        <el-table-column label="渠道" width="96">
          <template #default="{ row }">
            <PlatformChannelTag :platform="row.platform" />
          </template>
        </el-table-column>
        <el-table-column label="产品关键词" min-width="140" show-overflow-tooltip>
          <template #default="{ row }">{{ row.keywords.join("、") || "—" }}</template>
        </el-table-column>
        <el-table-column label="预设抓取数量" width="112" align="right">
          <template #default="{ row }">{{ row.metrics.requested_target || 0 }}</template>
        </el-table-column>
      </template>

      <template v-else>
        <el-table-column label="账号名称" min-width="150" show-overflow-tooltip>
          <template #default="{ row }">{{ manualAccountLabel(row) }}</template>
        </el-table-column>
        <el-table-column label="头像" width="72" align="center">
          <template #default="{ row }">
            <el-avatar :size="28">{{ avatarInitial(manualAccountLabel(row)) }}</el-avatar>
          </template>
        </el-table-column>
        <el-table-column label="获客方式" width="120">
          <template #default="{ row }">{{ manualIntentLabel(row.intent) }}</template>
        </el-table-column>
      </template>

      <el-table-column label="实际抓取总线索" width="120" align="right">
        <template #default="{ row }">
          <MetricLink :value="row.metrics.produced_total" @click="openOutreach(row.job, 'all')" />
        </template>
      </el-table-column>
      <el-table-column label="精准线索" width="96" align="right">
        <template #default="{ row }">
          <MetricLink :value="row.metrics.progress_precise" @click="openOutreach(row.job, 'precise')" />
        </template>
      </el-table-column>
      <el-table-column label="评论数" width="80" align="right">
        <template #default="{ row }">
          <MetricLink
            :value="row.metrics.comment_count"
            :clickable="metricViewCount(row.job, 'reply') > 0"
            @click="openOutreach(row.job, 'reply')"
          />
        </template>
      </el-table-column>
      <el-table-column label="私信数" width="80" align="right">
        <template #default="{ row }">
          <MetricLink
            :value="row.metrics.dm_count"
            :clickable="metricViewCount(row.job, 'dm') > 0"
            @click="openOutreach(row.job, 'dm')"
          />
        </template>
      </el-table-column>
      <el-table-column label="关注数" width="80" align="right">
        <template #default="{ row }">
          <MetricLink
            :value="row.metrics.follow_count"
            :clickable="metricViewCount(row.job, 'follow') > 0"
            @click="openOutreach(row.job, 'follow')"
          />
        </template>
      </el-table-column>
      <el-table-column label="创建时间" width="128">
        <template #default="{ row }">{{ formatJobTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-button
            v-if="row.display_status === 'suspended'"
            link
            type="warning"
            size="small"
            class="status-btn"
            @click.stop="showSuspendDetail(row)"
          >
            <TaskStatusBadge :status="row.display_status" clickable />
          </el-button>
          <el-button
            v-else-if="row.error && ['failed', 'dead_letter'].includes(row.status)"
            link
            type="danger"
            size="small"
            class="status-btn"
            @click.stop="showFailure(row)"
          >
            <TaskStatusBadge :status="row.display_status || row.status" clickable />
          </el-button>
          <TaskStatusBadge v-else :status="row.display_status || row.status" />
        </template>
      </el-table-column>
      <el-table-column label="操作" width="260" fixed="right">
        <template #default="{ row }">
          <div class="action-row">
            <template v-if="canPauseJob(row)">
              <el-button link type="warning" size="small" @click.stop="pauseOneJob(row)">暂停</el-button>
              <span class="action-sep">|</span>
            </template>
            <template v-if="row.status === 'running'">
              <el-button link type="primary" size="small" @click.stop="cancelOneJob(row.job.job_id)">关闭</el-button>
              <span class="action-sep">|</span>
            </template>
            <el-button link type="primary" size="small" @click.stop="executeOneJob(row.job.job_id)">
              {{ row.display_status === "suspended" ? "继续执行" : "更新线索" }}
            </el-button>
            <span class="action-sep">|</span>
            <el-button link type="primary" size="small" @click.stop="openOutreach(row.job, 'all')">查看数据</el-button>
            <template v-if="canDeleteJob(row.status)">
              <span class="action-sep">|</span>
              <el-button link type="danger" size="small" @click.stop="deleteOneJob(row)">删除</el-button>
            </template>
          </div>
        </template>
      </el-table-column>
    </el-table>

    <div v-if="filteredRows.length" class="pager-row">
      <span class="pager-text">
        共 {{ filteredRows.length }} 个{{ mode === 'manual' ? '手动获客' : '' }}任务，当前显示 {{ pageStart }}-{{ pageEnd }}
      </span>
      <el-pagination
        v-model:current-page="page"
        :page-size="pageSize"
        layout="prev, pager, next"
        :total="filteredRows.length"
        background
        small
      />
    </div>
    </div>

    <AcquisitionOutreachModal
      v-model="outreachOpen"
      :job="outreachJob"
      :initial-view="outreachView"
    />

    <TaskSuspendModal
      v-model="suspendOpen"
      :brief="suspendBrief"
      :job-id="suspendJobId"
      @resume="resumeSuspendedJob"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import AcquisitionOutreachModal from "./AcquisitionOutreachModal.vue";
import AcquisitionStatsCards from "./AcquisitionStatsCards.vue";
import AcquisitionTaskFilters from "./AcquisitionTaskFilters.vue";
import MetricLink from "./MetricLink.vue";
import PlatformChannelTag from "./PlatformChannelTag.vue";
import TaskStatusBadge from "./TaskStatusBadge.vue";
import TaskSuspendModal from "./TaskSuspendModal.vue";
import {
  cancelAgentJobTask,
  deleteAgentJob,
  executeAgentJob,
  fetchAgentJobs,
  pauseAgentJobTask,
} from "../api/agent";
import {
  avatarInitial,
  computeDashboardFromJobs,
  DEFAULT_ACQUISITION_FILTER,
  filterAutoJobs,
  filterManualJobs,
  formatJobTime,
  getJobDisplayStatus,
  getJobRowModel,
  getJobSuspendBrief,
  getMetricViewCounts,
  manualAccountLabel,
  manualIntentLabel,
  matchesJobFilter,
  sortJobsByCreated,
} from "../utils/acquisitionJobs";

const props = defineProps({
  mode: {
    type: String,
    default: "auto",
    validator: (value) => ["auto", "manual", "all"].includes(value),
  },
  active: { type: Boolean, default: true },
  emptyText: {
    type: String,
    default: "暂无任务，点击右上角创建任务开始获客",
  },
});

const emit = defineEmits(["jobs-updated"]);

const loading = ref(false);
const allJobs = ref([]);
const filter = reactive({ ...DEFAULT_ACQUISITION_FILTER });
const page = ref(1);
const pageSize = 5;
const outreachOpen = ref(false);
const outreachJob = ref(null);
const outreachView = ref("all");
const suspendOpen = ref(false);
const suspendBrief = ref(null);
const suspendJobId = ref("");
let pollTimer = null;

const modeJobs = computed(() => {
  if (props.mode === "manual") return filterManualJobs(allJobs.value);
  if (props.mode === "auto") return filterAutoJobs(allJobs.value);
  return allJobs.value;
});

const filteredRows = computed(() => {
  const rows = modeJobs.value
    .filter((job) => matchesJobFilter(job, filter))
    .map((job) => ({ ...getJobRowModel(job), job }));
  return sortJobsByCreated(rows, filter.sort);
});

const pageRows = computed(() => {
  const start = (page.value - 1) * pageSize;
  return filteredRows.value.slice(start, start + pageSize);
});

const pageStart = computed(() => (filteredRows.value.length ? (page.value - 1) * pageSize + 1 : 0));
const pageEnd = computed(() => Math.min(page.value * pageSize, filteredRows.value.length));

const dashboard = computed(() => computeDashboardFromJobs(modeJobs.value));
const hasQueuedJobs = computed(() =>
  modeJobs.value.some((job) => getJobDisplayStatus(job) === "queued"),
);
const hasSuspendedJobs = computed(() =>
  modeJobs.value.some((job) => getJobDisplayStatus(job) === "suspended"),
);
const hasFailedJobs = computed(() => modeJobs.value.some((job) => ["failed", "dead_letter"].includes(job.status)));

function canDeleteJob(status) {
  return ["completed", "cancelled", "failed", "dead_letter"].includes(status);
}

function canPauseJob(row) {
  return ["running", "queued", "retrying"].includes(row.status);
}

function metricViewCount(job, view) {
  if (!job) return 0;
  return getMetricViewCounts(job)[view] || 0;
}

function onFilterSubmit() {
  page.value = 1;
}

async function loadJobs({ silent = false } = {}) {
  if (!silent) loading.value = true;
  try {
    const list = await fetchAgentJobs(200);
    allJobs.value = Array.isArray(list) ? list : [];
    emit("jobs-updated", filteredRows.value);
  } catch (err) {
    if (!silent) ElMessage.error(err.message || "加载任务失败");
  } finally {
    if (!silent) loading.value = false;
  }
}

async function executeOneJob(jobId) {
  try {
    await executeAgentJob(jobId);
    ElMessage.success("任务已更新");
    await loadJobs();
  } catch (err) {
    ElMessage.error(err.message || "更新失败");
  }
}

async function cancelOneJob(jobId) {
  try {
    await cancelAgentJobTask(jobId);
    ElMessage.success("任务已关闭");
    await loadJobs();
  } catch (err) {
    ElMessage.error(err.message || "关闭失败");
  }
}

async function pauseOneJob(row) {
  try {
    await ElMessageBox.confirm(
      `确认暂停任务「${row.name}」？暂停后可点击「继续执行」恢复。`,
      "暂停任务",
      { type: "warning", confirmButtonText: "暂停", cancelButtonText: "取消" },
    );
    await pauseAgentJobTask(row.job.job_id);
    ElMessage.success("任务已暂停");
    await loadJobs();
  } catch (err) {
    if (err !== "cancel") {
      ElMessage.error(err?.message || "暂停失败");
    }
  }
}

async function deleteOneJob(row) {
  try {
    await ElMessageBox.confirm(`确认删除任务「${row.name}」？`, "删除任务", { type: "warning" });
    await deleteAgentJob(row.job.job_id);
    ElMessage.success("已删除");
    await loadJobs();
  } catch (err) {
    if (err !== "cancel") {
      ElMessage.error(err?.message || "删除失败");
    }
  }
}

function openOutreach(job, view = "all") {
  outreachJob.value = job;
  outreachView.value = view;
  outreachOpen.value = true;
}

function showSuspendDetail(row) {
  const brief = getJobSuspendBrief(row.job);
  if (!brief) return;
  suspendBrief.value = brief;
  suspendJobId.value = row.job?.job_id || "";
  suspendOpen.value = true;
}

function showFailure(row) {
  const message = row.error || row.suspend_reason || "任务执行失败";
  ElMessageBox.alert(message, "失败详情", { type: "error" });
}

async function resumeSuspendedJob() {
  if (!suspendJobId.value) return;
  await executeOneJob(suspendJobId.value);
}

function hasActiveJobs() {
  return modeJobs.value.some((job) => ["queued", "pending", "running"].includes(job.status));
}

function startPolling() {
  stopPolling();
  const interval = hasActiveJobs() ? 4000 : 15000;
  pollTimer = window.setInterval(() => {
    if (props.active) void loadJobs({ silent: true });
  }, interval);
}

function stopPolling() {
  if (pollTimer) {
    window.clearInterval(pollTimer);
    pollTimer = null;
  }
}

watch(
  () => props.active,
  (active) => {
    if (active) {
      void loadJobs();
      startPolling();
    } else {
      stopPolling();
    }
  },
  { immediate: true },
);

watch(filteredRows, () => {
  const maxPage = Math.max(1, Math.ceil(filteredRows.value.length / pageSize));
  if (page.value > maxPage) page.value = maxPage;
  startPolling();
});

onMounted(() => {
  if (props.active) startPolling();
});

onUnmounted(stopPolling);

defineExpose({ loadJobs, jobs: filteredRows, dashboard });
</script>

<style scoped>
.acquisition-jobs-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.panel-block {
  width: 100%;
}

.table-card {
  padding: 20px;
  overflow: hidden;
}

.jobs-table {
  width: 100%;
}

.jobs-table :deep(.el-table__header th) {
  background: #f8fafc;
  color: #64748b;
  font-size: 13px;
  font-weight: 500;
}

.jobs-table :deep(.el-table__row td) {
  font-size: 13px;
}

.status-btn {
  padding: 0;
  height: auto;
}

.action-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 2px;
}

.action-sep {
  color: #e2e8f0;
  font-size: 12px;
  user-select: none;
}

.pager-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid var(--border);
}

.pager-text {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}
</style>
