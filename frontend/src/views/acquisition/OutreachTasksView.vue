<template>
  <div class="outreach-page">
    <header class="page-header">
      <div>
        <h1 class="page-title">触达任务</h1>
        <p class="page-subtitle">从已完成采集任务的精准评论中筛选客户，独立执行关注或私信，可按天循环等待新数据。</p>
      </div>
      <div class="header-actions">
        <el-button @click="refreshAll" :loading="loading">刷新</el-button>
        <el-button type="primary" @click="createOpen = true">+ 创建触达任务</el-button>
      </div>
    </header>

    <section class="summary-band">
      <div class="summary-item">
        <span class="summary-label">可触达线索</span>
        <strong>{{ candidateTotal }}</strong>
      </div>
      <div class="summary-item">
        <span class="summary-label">运行中</span>
        <strong>{{ runningCount }}</strong>
      </div>
      <div class="summary-item">
        <span class="summary-label">今日剩余额度</span>
        <strong>{{ quota.remaining ?? "—" }}</strong>
      </div>
    </section>

    <el-card shadow="never" class="panel-block">
      <template #header>
        <div class="card-head">
          <span>触达任务列表</span>
          <span class="head-hint">采集任务不再自动关注或私信，触达任务可单独启动/暂停。</span>
        </div>
      </template>
      <el-table v-loading="loading" :data="tasks" empty-text="暂无触达任务">
        <el-table-column prop="name" label="任务名称" min-width="180" show-overflow-tooltip />
        <el-table-column label="平台" width="90">
          <template #default="{ row }">
            <el-tag size="small">{{ platformLabel(row.platform) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="动作" width="116">
          <template #default="{ row }">{{ actionLabel(row.action_type) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="108">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="pending_count" label="待执行" width="84" align="right" />
        <el-table-column prop="completed_count" label="成功" width="84" align="right" />
        <el-table-column prop="failed_count" label="失败" width="84" align="right" />
        <el-table-column label="模式" width="92">
          <template #default="{ row }">
            <el-tag size="small" :type="row.recurring ? 'success' : 'info'">
              {{ row.recurring ? "循环" : "一次性" }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="间隔" width="96" align="right">
          <template #default="{ row }">{{ intervalLabel(row.interval_ms) }}</template>
        </el-table-column>
        <el-table-column label="创建时间" width="160">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="210" fixed="right">
          <template #default="{ row }">
            <el-button text type="primary" @click="openItems(row)">明细</el-button>
            <el-button
              v-if="row.status !== 'running'"
              text
              type="primary"
              :disabled="Number(row.pending_count || 0) <= 0 && !row.recurring"
              @click="startTask(row)"
            >
              启动
            </el-button>
            <el-button v-else text type="warning" @click="pauseTask(row)">暂停</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="createOpen" title="创建触达任务" width="820px" destroy-on-close @closed="resetForm">
      <el-form label-width="116px" class="create-form">
        <el-form-item label="任务名称">
          <el-input v-model="form.name" placeholder="例如：本周餐饮精准客户关注" />
        </el-form-item>

        <el-form-item label="平台" required>
          <el-radio-group v-model="form.platform" @change="onPlatformChange">
            <el-radio-button value="douyin">抖音</el-radio-button>
            <el-radio-button value="xiaohongshu" disabled>小红书</el-radio-button>
          </el-radio-group>
          <p class="field-hint">小红书 PC 网页版暂不支持自动关注或私信触达，当前仅支持采集和线索筛选。</p>
        </el-form-item>

        <el-form-item label="触达动作" required>
          <el-radio-group v-model="form.actionType">
            <el-radio-button
              v-for="item in actionOptions"
              :key="item.value"
              :value="item.value"
            >
              {{ item.label }}
            </el-radio-button>
          </el-radio-group>
          <p class="field-hint">{{ actionHint }}</p>
        </el-form-item>

        <el-form-item v-if="form.actionType.includes('dm')" label="私信模板" required>
          <el-select v-model="form.dmPresetId" placeholder="选择私信预设" filterable style="width: 100%">
            <el-option
              v-for="item in dmPresets"
              :key="item.id"
              :label="item.name || item.title || item.id"
              :value="item.id"
            />
          </el-select>
          <el-input
            v-model="form.dmText"
            type="textarea"
            :rows="3"
            placeholder="也可以直接填写本次私信内容"
            class="dm-textarea"
          />
        </el-form-item>

        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="线索数量" required>
              <el-input-number v-model="form.maxItems" :min="1" :max="500" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="执行间隔">
              <el-input-number v-model="form.intervalSeconds" :min="5" :max="300" />
              <span class="unit">秒</span>
              <p class="field-hint">每次关注/私信动作之间都会等待，实际会在该值到 1.5 倍之间浮动。</p>
            </el-form-item>
          </el-col>
        </el-row>

        <el-form-item label="循环执行">
          <el-switch
            v-model="form.recurring"
            active-text="每天自动循环"
            inactive-text="一次性任务"
          />
          <p class="field-hint">开启后，队列为空会继续等待新采集评论；今日额度用完会休眠，隔天额度恢复后继续。</p>
        </el-form-item>

        <el-row v-if="form.recurring" :gutter="16">
          <el-col :span="12">
            <el-form-item label="空闲休眠">
              <el-input-number v-model="form.idleSleepMinutes" :min="1" :max="1440" />
              <span class="unit">分钟</span>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="每次补充">
              <el-input-number v-model="form.refillBatchSize" :min="1" :max="500" />
              <span class="unit">条</span>
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="每日上限">
              <el-input-number v-model="form.dailyQuota" :min="1" :max="500" />
              <p class="field-hint">按动作次数计算；“关注后私信”会占用 2 次额度。</p>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="最低点赞">
              <el-input-number v-model="form.minDiggCount" :min="0" :max="9999" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-form-item label="候选预览">
          <div class="candidate-panel">
            <div class="candidate-head">
              <span>将从所有已完成采集任务的精准评论中选取，自动跳过已完成触达的用户。</span>
              <el-button size="small" @click="loadCandidates" :loading="candidateLoading">刷新预览</el-button>
            </div>
            <el-table
              v-loading="candidateLoading"
              :data="candidateRows"
              size="small"
              empty-text="暂无可触达精准线索"
              max-height="260"
            >
              <el-table-column prop="username" label="用户" width="110" show-overflow-tooltip />
              <el-table-column prop="job_name" label="来源任务" min-width="140" show-overflow-tooltip />
              <el-table-column prop="comment_text" label="精准评论" min-width="180" show-overflow-tooltip />
              <el-table-column prop="evaluation_reason" label="评估说明" min-width="160" show-overflow-tooltip />
              <el-table-column label="评分" width="72" align="right">
                <template #default="{ row }">{{ scoreLabel(row.evaluation_score) }}</template>
              </el-table-column>
            </el-table>
          </div>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="createOpen = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitTask">创建任务</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="itemsOpen" title="触达明细" width="1040px">
      <el-table v-loading="itemsLoading" :data="items" empty-text="暂无明细" max-height="520">
        <el-table-column prop="username" label="用户" width="120" show-overflow-tooltip />
        <el-table-column prop="comment_text" label="精准评论" min-width="180" show-overflow-tooltip />
        <el-table-column prop="dm_text" label="私信内容" min-width="160" show-overflow-tooltip />
        <el-table-column label="状态" width="96">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="attempts" label="次数" width="70" align="right" />
        <el-table-column prop="error_message" label="失败原因" min-width="160" show-overflow-tooltip />
        <el-table-column label="主页" width="76">
          <template #default="{ row }">
            <a v-if="row.profile_url" :href="row.profile_url" target="_blank" rel="noopener noreferrer">打开</a>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import {
  createOutreachTask,
  fetchReplyQuota,
  listOutreachCandidates,
  listOutreachItems,
  listOutreachTasks,
  pauseOutreachTask,
  startOutreachTask,
} from "../../api/localService";
import { listLocalPresets } from "../../utils/localPresets";
import { listPlatformPresets } from "../../api/presets";

const loading = ref(false);
const candidateLoading = ref(false);
const submitting = ref(false);
const itemsLoading = ref(false);
const createOpen = ref(false);
const itemsOpen = ref(false);
const tasks = ref([]);
const quota = ref({});
const candidateRows = ref([]);
const dmPresets = ref([]);
const items = ref([]);

const form = reactive({
  name: "",
  platform: "douyin",
  actionType: "follow",
  dmPresetId: "",
  dmText: "",
  maxItems: 30,
  intervalSeconds: 20,
  dailyQuota: 30,
  minDiggCount: 0,
  recurring: true,
  idleSleepMinutes: 10,
  refillBatchSize: 50,
});

const candidateTotal = computed(() => candidateRows.value.length);
const runningCount = computed(() => tasks.value.filter((row) => row.status === "running").length);
const actionOptions = computed(() => {
  if (form.platform === "xiaohongshu") {
    return [];
  }
  return [
    { value: "follow", label: "关注" },
    { value: "dm", label: "私信" },
    { value: "follow_then_dm", label: "关注后私信" },
  ];
});
const actionHint = computed(() =>
  form.platform === "xiaohongshu"
    ? "小红书 PC 网页版暂不支持自动关注或私信触达。"
    : "抖音支持关注、私信、关注后私信；任务会逐个打开用户主页执行。",
);

watch(
  () => [form.platform, form.maxItems],
  () => {
    if (createOpen.value) void loadCandidates();
  },
);

watch(
  () => form.dmPresetId,
  (id) => {
    const preset = dmPresets.value.find((row) => row.id === id);
    if (preset?.content) form.dmText = preset.content;
  },
);

watch(createOpen, (value) => {
  if (value) {
    void loadPresets();
    void loadCandidates();
  }
});

onMounted(refreshAll);

async function refreshAll() {
  loading.value = true;
  try {
    const [taskRows, quotaResp] = await Promise.all([
      listOutreachTasks(),
      fetchReplyQuota().catch(() => ({})),
    ]);
    tasks.value = taskRows || [];
    quota.value = quotaResp || {};
  } catch (err) {
    ElMessage.error(err?.response?.data?.error || err?.message || "加载触达任务失败");
  } finally {
    loading.value = false;
  }
}

async function loadPresets() {
  try {
    const presets = await listPlatformPresets();
    dmPresets.value = presets.dmOpeners || [];
  } catch {
    dmPresets.value = listLocalPresets("dm-openers").items || [];
  }
}

async function loadCandidates() {
  candidateLoading.value = true;
  try {
    const resp = await listOutreachCandidates({
      platform: form.platform,
      limit: form.maxItems,
    });
    candidateRows.value = resp.candidates || [];
  } catch {
    candidateRows.value = [];
  } finally {
    candidateLoading.value = false;
  }
}

function onPlatformChange() {
  if (!actionOptions.value.some((item) => item.value === form.actionType)) {
    form.actionType = "follow";
  }
}

function resetForm() {
  form.name = "";
  form.platform = "douyin";
  form.actionType = "follow";
  form.dmPresetId = "";
  form.dmText = "";
  form.maxItems = 30;
  form.intervalSeconds = 20;
  form.dailyQuota = 30;
  form.minDiggCount = 0;
  form.recurring = true;
  form.idleSleepMinutes = 10;
  form.refillBatchSize = 50;
  candidateRows.value = [];
}

async function submitTask() {
  if (form.platform === "xiaohongshu") {
    ElMessage.warning("小红书 PC 网页版暂不支持自动关注或私信触达");
    return;
  }
  if (form.actionType.includes("dm") && !form.dmText.trim()) {
    ElMessage.warning("请填写或选择私信内容");
    return;
  }
  if (!candidateRows.value.length && !form.recurring) {
    ElMessage.warning("暂无可触达精准线索；如需等待新数据，请开启循环执行");
    return;
  }
  submitting.value = true;
  try {
    const resp = await createOutreachTask({
      name: form.name.trim() || undefined,
      platform: form.platform,
      action_type: form.actionType,
      dm_text: form.dmText.trim(),
      max_items: form.maxItems,
      interval_ms: form.intervalSeconds * 1000,
      daily_quota: form.dailyQuota,
      min_digg_count: form.minDiggCount,
      recurring: form.recurring,
      idle_sleep_ms: form.idleSleepMinutes * 60 * 1000,
      refill_batch_size: form.refillBatchSize,
    });
    ElMessage.success(`触达任务已创建，共 ${resp.inserted_items || 0} 条线索`);
    createOpen.value = false;
    await refreshAll();
  } catch (err) {
    ElMessage.error(err?.response?.data?.error || err?.message || "创建触达任务失败");
  } finally {
    submitting.value = false;
  }
}

async function startTask(row) {
  try {
    await startOutreachTask(row.id);
    ElMessage.success("触达任务已启动");
    await refreshAll();
  } catch (err) {
    ElMessage.error(err?.response?.data?.error || err?.message || "启动失败");
  }
}

async function pauseTask(row) {
  try {
    await pauseOutreachTask(row.id);
    ElMessage.success("触达任务已暂停");
    await refreshAll();
  } catch (err) {
    ElMessage.error(err?.response?.data?.error || err?.message || "暂停失败");
  }
}

async function openItems(row) {
  itemsOpen.value = true;
  itemsLoading.value = true;
  try {
    const resp = await listOutreachItems(row.id, { limit: 1000 });
    items.value = resp.items || [];
  } catch (err) {
    ElMessage.error(err?.response?.data?.error || err?.message || "加载明细失败");
  } finally {
    itemsLoading.value = false;
  }
}

function platformLabel(platform) {
  return { douyin: "抖音", xiaohongshu: "小红书" }[platform] || platform || "—";
}

function actionLabel(action) {
  return {
    follow: "关注",
    dm: "私信",
    follow_then_dm: "关注后私信",
    reply: "评论回复",
  }[action] || action || "—";
}

function statusLabel(status) {
  return {
    pending: "待执行",
    running: "运行中",
    paused: "已暂停",
    completed: "已完成",
    failed: "失败",
  }[status] || status || "—";
}

function statusType(status) {
  return {
    running: "primary",
    completed: "success",
    failed: "danger",
    paused: "warning",
  }[status] || "info";
}

function intervalLabel(intervalMs) {
  const seconds = Math.round(Number(intervalMs || 0) / 1000);
  if (!seconds) return "—";
  return `${seconds}-${Math.round(seconds * 1.5)} 秒`;
}

function scoreLabel(score) {
  if (score === null || score === undefined) return "—";
  return Number(score).toFixed(2);
}

function formatTime(ms) {
  if (!ms) return "—";
  return new Date(Number(ms)).toLocaleString();
}
</script>

<style scoped>
.outreach-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.header-actions {
  display: flex;
  gap: 10px;
  flex-shrink: 0;
}

.summary-band {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.summary-item {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 14px 16px;
  background: var(--el-fill-color-blank);
}

.summary-label {
  display: block;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  margin-bottom: 6px;
}

.summary-item strong {
  font-size: 24px;
  line-height: 1;
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.head-hint,
.field-hint {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.create-form {
  padding-right: 8px;
}

.unit {
  margin-left: 8px;
  color: var(--el-text-color-secondary);
}

.dm-textarea {
  margin-top: 8px;
}

.candidate-panel {
  width: 100%;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  overflow: hidden;
}

.candidate-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  background: var(--el-fill-color-light);
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

@media (max-width: 760px) {
  .page-header,
  .card-head,
  .candidate-head {
    flex-direction: column;
    align-items: stretch;
  }

  .summary-band {
    grid-template-columns: 1fr;
  }
}
</style>
