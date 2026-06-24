<template>
  <el-dialog
    v-model="visible"
    title="运行日志"
    width="720px"
    destroy-on-close
    class="run-logs-dialog"
    @open="onOpen"
    @closed="onClosed"
  >
    <div v-loading="loading" class="run-logs-body">
      <el-empty v-if="!loading && !runs.length" description="暂无运行日志，任务执行后会自动记录每一步" />

      <template v-else>
        <div class="runs-toolbar">
          <span class="runs-hint">每次点击「开始/继续采集」记为一轮；日志包含搜索、点击、翻页、采评论、触达等全部插件操作，可下载发给客服排查。</span>
        </div>

        <el-collapse v-model="expandedRuns" accordion class="runs-collapse">
          <el-collapse-item
            v-for="run in runs"
            :key="run.run_id"
            :name="String(run.run_id)"
          >
            <template #title>
              <div class="run-title">
                <span class="run-label">第 {{ run.run_id }} 轮</span>
                <span class="run-time">{{ formatTime(run.started_at) }}</span>
                <el-tag size="small" type="success" effect="plain">{{ run.ok_count || 0 }} 成功</el-tag>
                <el-tag v-if="run.fail_count" size="small" type="danger" effect="plain">
                  {{ run.fail_count }} 失败
                </el-tag>
                <el-tag size="small" effect="plain">{{ run.step_count || 0 }} 步</el-tag>
                <span v-if="run.last_label" class="run-last">{{ run.last_label }}</span>
              </div>
            </template>

            <div class="run-actions">
              <el-button size="small" type="primary" plain @click="downloadRun(run.run_id, 'txt')">
                下载 TXT
              </el-button>
              <el-button size="small" plain @click="downloadRun(run.run_id, 'json')">
                下载 JSON
              </el-button>
            </div>

            <div v-if="stepsForRun(run.run_id).length" class="steps-list">
              <div
                v-for="step in stepsForRun(run.run_id)"
                :key="step.id"
                class="step-row"
                :class="`step-${step.status}`"
              >
                <div class="step-head">
                  <span class="step-seq">#{{ step.seq }}</span>
                  <el-tag size="small" :type="statusTagType(step.status)" effect="light">
                    {{ statusLabel(step.status) }}
                  </el-tag>
                  <span class="step-label">{{ step.step_label }}</span>
                  <span class="step-time">{{ formatTime(step.created_at) }}</span>
                </div>
                <p v-if="step.reason" class="step-reason">{{ step.reason }}</p>
                <pre v-if="stepDetailText(step)" class="step-detail">{{ stepDetailText(step) }}</pre>
              </div>
            </div>
            <div v-else-if="loadingSteps[String(run.run_id)]" class="steps-loading">加载步骤中…</div>
            <div v-else class="steps-loading">
              <el-button link type="primary" @click="loadRunSteps(run.run_id)">加载步骤详情</el-button>
            </div>
          </el-collapse-item>
        </el-collapse>
      </template>
    </div>

    <template #footer>
      <el-button @click="visible = false">关闭</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import {
  downloadCollectJobRunLog,
  fetchCollectJobRunLogDetail,
  fetchCollectJobRunLogs,
} from "../api/localService";

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  jobId: { type: String, default: "" },
  jobName: { type: String, default: "" },
});

const emit = defineEmits(["update:modelValue"]);

const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit("update:modelValue", value),
});

const loading = ref(false);
const runs = ref([]);
const stepsByRun = ref({});
const loadingSteps = ref({});
const expandedRuns = ref("");

watch(expandedRuns, (runId) => {
  if (runId) loadRunSteps(Number(runId));
});

function formatTime(ts) {
  const num = Number(ts);
  if (!Number.isFinite(num) || num <= 0) return "—";
  const ms = num > 1e12 ? num : num * 1000;
  return new Date(ms).toLocaleString("zh-CN", { hour12: false });
}

function statusLabel(status) {
  const map = {
    ok: "成功",
    fail: "失败",
    skip: "跳过",
    warn: "警告",
    info: "信息",
  };
  return map[status] || status || "—";
}

function statusTagType(status) {
  const map = {
    ok: "success",
    fail: "danger",
    skip: "info",
    warn: "warning",
    info: "",
  };
  return map[status] || "info";
}

function stepsForRun(runId) {
  return stepsByRun.value[String(runId)] || [];
}

function stepDetailText(step) {
  if (!step?.detail || typeof step.detail !== "object") return "";
  try {
    return JSON.stringify(step.detail, null, 2);
  } catch {
    return String(step.detail);
  }
}

async function onOpen() {
  await refreshRuns();
}

function onClosed() {
  runs.value = [];
  stepsByRun.value = {};
  loadingSteps.value = {};
  expandedRuns.value = "";
}

async function refreshRuns() {
  const jobId = String(props.jobId || "").trim();
  if (!jobId) return;
  loading.value = true;
  try {
    const data = await fetchCollectJobRunLogs(jobId);
    runs.value = Array.isArray(data?.runs) ? data.runs : [];
    if (runs.value.length === 1) {
      expandedRuns.value = String(runs.value[0].run_id);
    }
  } catch (err) {
    ElMessage.error(err?.response?.data?.error || err?.message || "加载运行日志失败");
  } finally {
    loading.value = false;
  }
}

async function loadRunSteps(runId) {
  const jobId = String(props.jobId || "").trim();
  const key = String(runId);
  if (!jobId || stepsByRun.value[key]?.length) return;
  loadingSteps.value = { ...loadingSteps.value, [key]: true };
  try {
    const data = await fetchCollectJobRunLogDetail(jobId, runId);
    stepsByRun.value = {
      ...stepsByRun.value,
      [key]: Array.isArray(data?.steps) ? data.steps : [],
    };
  } catch (err) {
    ElMessage.error(err?.response?.data?.error || err?.message || "加载步骤失败");
  } finally {
    loadingSteps.value = { ...loadingSteps.value, [key]: false };
  }
}

async function downloadRun(runId, format) {
  const jobId = String(props.jobId || "").trim();
  if (!jobId) return;
  try {
    await downloadCollectJobRunLog(jobId, runId, format);
    ElMessage.success(format === "json" ? "JSON 日志已下载" : "TXT 日志已下载");
  } catch (err) {
    ElMessage.error(err?.response?.data?.error || err?.message || "下载失败");
  }
}
</script>

<style scoped>
.run-logs-body {
  min-height: 200px;
}

.runs-hint {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
}

.runs-collapse {
  margin-top: 12px;
  border: none;
}

.run-title {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding-right: 8px;
}

.run-label {
  font-weight: 600;
}

.run-time {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.run-last {
  font-size: 12px;
  color: var(--el-text-color-regular);
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.run-actions {
  margin-bottom: 12px;
}

.steps-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 360px;
  overflow-y: auto;
}

.step-row {
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--el-fill-color-light);
  border-left: 3px solid var(--el-border-color);
}

.step-row.step-ok {
  border-left-color: var(--el-color-success);
}

.step-row.step-fail {
  border-left-color: var(--el-color-danger);
}

.step-row.step-warn {
  border-left-color: var(--el-color-warning);
}

.step-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.step-seq {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  font-variant-numeric: tabular-nums;
}

.step-label {
  font-weight: 500;
}

.step-time {
  margin-left: auto;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.step-reason {
  margin: 6px 0 0;
  font-size: 13px;
  color: var(--el-text-color-regular);
  line-height: 1.5;
}

.step-detail {
  margin: 6px 0 0;
  padding: 8px;
  font-size: 11px;
  background: var(--el-bg-color);
  border-radius: 4px;
  overflow-x: auto;
  max-height: 120px;
}

.steps-loading {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  padding: 8px 0;
}
</style>
