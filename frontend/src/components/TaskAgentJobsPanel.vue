<template>
  <div class="agent-jobs-panel">
    <div class="panel jobs-panel">
      <div class="panel-head">
        <h2 class="section-title">编排任务队列</h2>
        <div class="panel-head-actions">
          <span class="result-count">共 {{ filteredJobs.length }} 条</span>
          <el-button type="primary" size="small" @click="$emit('create')">新建任务</el-button>
        </div>
      </div>
      <el-table
        v-loading="loading"
        :data="filteredJobs"
        stripe
        class="jobs-table"
        empty-text="暂无编排任务，点击上方「创建任务」描述需求，由 Agent 自动编排执行"
        row-class-name="job-row"
        @row-click="openJobDetail"
      >
        <el-table-column prop="job_id" label="Job ID" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">
            <button type="button" class="job-link" @click.stop="openJobDetail(row)">
              <code class="mono">{{ row.job_id }}</code>
            </button>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.status)" size="small" effect="light">
              {{ statusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="stage" label="阶段" width="100" />
        <el-table-column prop="retry_count" label="重试" width="72" align="center" />
        <el-table-column prop="run_id" label="Run ID" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">
            <code v-if="row.run_id" class="mono">{{ row.run_id }}</code>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="updated_at" label="更新时间" width="168">
          <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="280" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click.stop="openJobDetail(row)">查看</el-button>
            <el-button
              v-if="['pending', 'cancelled', 'failed', 'dead_letter', 'completed'].includes(row.status)"
              link
              type="success"
              size="small"
              @click.stop="executeOneJob(row.job_id)"
            >
              {{ row.status === 'pending' ? '启动' : '重启' }}
            </el-button>
            <el-button link type="primary" size="small" @click.stop="refreshOneJob(row.job_id)">刷新</el-button>
            <el-button
              v-if="row.status === 'queued' || row.status === 'running'"
              link
              type="danger"
              size="small"
              @click.stop="cancelOneJob(row.job_id)"
            >
              取消
            </el-button>
            <el-button
              v-if="canDeleteJob(row.status)"
              link
              type="danger"
              size="small"
              @click.stop="deleteOneJob(row)"
            >
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  cancelAgentJobTask,
  deleteAgentJob,
  executeAgentJob,
  fetchAgentJob,
  fetchAgentJobs,
} from "../api/agent";

const props = defineProps({
  statusFilter: { type: String, default: "" },
  active: { type: Boolean, default: false },
});

const emit = defineEmits(["jobs-updated", "create"]);

const router = useRouter();
const loading = ref(false);
const jobs = ref([]);
let pollTimer = null;

const STATUS_MAP = {
  pending: "待执行",
  retrying: "重试中",
  queued: "排队中",
  running: "运行中",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
  dead_letter: "死信",
};

const filteredJobs = computed(() => {
  if (!props.statusFilter) return jobs.value;
  if (props.statusFilter === "failed") {
    return jobs.value.filter((j) => j.status === "failed" || j.status === "dead_letter");
  }
  return jobs.value.filter((j) => j.status === props.statusFilter);
});

function statusLabel(status) {
  return STATUS_MAP[status] || status;
}

function statusTagType(status) {
  if (status === "completed") return "success";
  if (status === "running") return "primary";
  if (status === "retrying") return "warning";
  if (status === "failed" || status === "dead_letter") return "danger";
  if (status === "cancelled") return "info";
  if (status === "pending") return "info";
  return "warning";
}

function formatTime(value) {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return String(value);
  }
}

async function loadJobs() {
  loading.value = true;
  try {
    const data = await fetchAgentJobs(50);
    jobs.value = Array.isArray(data) ? data : [];
    emit("jobs-updated", jobs.value);
    schedulePoll();
  } catch (err) {
    ElMessage.error(err.message || "加载 Agent 队列失败");
  } finally {
    loading.value = false;
  }
}

function openJobDetail(row) {
  if (!row?.job_id) return;
  router.push(`/tasks/jobs/${row.job_id}`);
}

async function executeOneJob(jobId) {
  try {
    const data = await executeAgentJob(jobId);
    const idx = jobs.value.findIndex((item) => item.job_id === jobId);
    if (idx >= 0) jobs.value[idx] = data;
    ElMessage.success("任务已启动");
    schedulePoll();
  } catch (err) {
    ElMessage.error(err.message || "启动任务失败");
  }
}

async function refreshOneJob(jobId) {
  try {
    const data = await fetchAgentJob(jobId);
    const idx = jobs.value.findIndex((item) => item.job_id === jobId);
    if (idx >= 0) jobs.value[idx] = data;
    else jobs.value.unshift(data);
  } catch (err) {
    ElMessage.error(err.message || "刷新任务失败");
  }
}

function canDeleteJob(status) {
  return ["pending", "cancelled", "failed", "dead_letter", "completed"].includes(status);
}

async function deleteOneJob(row) {
  const jobId = row?.job_id;
  if (!jobId) return;
  try {
    await ElMessageBox.confirm(
      `确定删除任务 ${jobId.slice(0, 8)}…？将同时删除沙盒与执行记录，不可恢复。`,
      "删除任务",
      { type: "warning", confirmButtonText: "删除", cancelButtonText: "取消" },
    );
    await deleteAgentJob(jobId);
    jobs.value = jobs.value.filter((item) => item.job_id !== jobId);
    emit("jobs-updated", jobs.value);
    ElMessage.success("任务已删除");
  } catch (err) {
    if (err === "cancel" || err?.message === "cancel") return;
    ElMessage.error(err.message || "删除任务失败");
  }
}

async function cancelOneJob(jobId) {
  try {
    await cancelAgentJobTask(jobId);
    ElMessage.success("已取消任务");
    await refreshOneJob(jobId);
  } catch (err) {
    ElMessage.error(err.message || "取消任务失败");
  }
}

function schedulePoll() {
  if (pollTimer) clearInterval(pollTimer);
  if (!props.active) return;
  const hasActive = jobs.value.some((j) => ["running", "queued", "retrying"].includes(j.status));
  if (!hasActive) return;
  pollTimer = setInterval(async () => {
    try {
      const data = await fetchAgentJobs(50);
      jobs.value = Array.isArray(data) ? data : [];
      emit("jobs-updated", jobs.value);
      if (!jobs.value.some((j) => ["running", "queued", "retrying"].includes(j.status))) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
    } catch {
      /* ignore */
    }
  }, 2000);
}

defineExpose({ loadJobs, jobs });

watch(
  () => props.active,
  (isActive) => {
    if (isActive) {
      loadJobs();
      return;
    }
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  },
);

onMounted(() => {
  if (props.active) loadJobs();
});

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer);
});
</script>

<style scoped>
.agent-jobs-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.jobs-panel {
  padding: 16px 18px;
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.panel-head-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.section-title {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
}

.result-count {
  font-size: 13px;
  color: var(--muted);
}

.mono {
  font-family: ui-monospace, monospace;
  font-size: 12px;
}

.muted {
  color: #cbd5e1;
}

:deep(.job-row) {
  cursor: pointer;
}

.job-link {
  padding: 0;
  border: none;
  background: none;
  cursor: pointer;
}

.job-link .mono {
  color: var(--el-color-primary);
}
</style>
