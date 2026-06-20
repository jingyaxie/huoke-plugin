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

    <el-table v-loading="loading" :data="manualJobs" class="panel-block table-card" empty-text="暂无手动获客任务">
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
      <el-table-column label="采集评论" width="88" align="right">
        <template #default="{ row }">{{ row.comment_count || 0 }}</template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag size="small" :type="statusTagType(row.status)">{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="创建时间" width="160">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="260" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openJobDetail(row)">详情</el-button>
          <el-button
            link
            type="primary"
            :disabled="row.status === 'running' || row.status === 'completed'"
            @click="onStartCollect(row)"
          >
            开始采集
          </el-button>
          <el-button
            link
            type="success"
            :disabled="row.comment_count <= 0"
            @click="openOutreachDialog(row)"
          >
            创建触达
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <CreateExtensionManualTaskDialog v-model="createOpen" @created="refreshAll" />

    <el-dialog v-model="createOutreachOpen" title="创建评论触达" width="560px">
      <el-form label-width="120px">
        <el-form-item label="来源任务">
          <el-input :model-value="outreachForm.source_name" disabled />
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
          <el-input v-model="outreachForm.reply_text" type="textarea" :rows="4" />
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

    <el-drawer v-model="detailOpen" :title="detailTitle" size="720px">
      <div v-loading="detailLoading" class="detail-body">
        <p v-if="detailJob?.input_url" class="detail-url">{{ detailJob.input_url }}</p>
        <h4>采集视频 ({{ detailVideos.length }})</h4>
        <el-table :data="detailVideos" size="small" max-height="220" @row-click="selectVideo">
          <el-table-column prop="title" label="标题" min-width="200" show-overflow-tooltip />
          <el-table-column prop="author" label="作者" width="120" show-overflow-tooltip />
        </el-table>
        <h4 class="detail-comments-title">评论 ({{ detailComments.length }})</h4>
        <el-table :data="detailComments" size="small" max-height="360" empty-text="暂无评论">
          <el-table-column prop="username" label="用户" width="120" show-overflow-tooltip />
          <el-table-column prop="content" label="内容" min-width="220" show-overflow-tooltip />
          <el-table-column prop="digg_count" label="赞" width="64" align="right" />
        </el-table>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import CreateExtensionManualTaskDialog from "../../components/CreateExtensionManualTaskDialog.vue";
import {
  createOutreachTask,
  fetchBridgeStatus,
  listCollectComments,
  listCollectJobs,
  listCollectVideos,
  startCollectJob,
} from "../../api/localService";
import {
  avatarInitial,
  manualAccountLabel,
  manualIntentLabel,
} from "../../utils/acquisitionJobs";
import { loadReplyPresetOptions } from "../../utils/localPresets";

const loading = ref(false);
const submitting = ref(false);
const allJobs = ref([]);
const bridgeStatus = ref({ connected_clients: 0 });
const createOpen = ref(false);
const createOutreachOpen = ref(false);
const replyPresets = ref([]);
const selectedPresetId = ref("");
let pollTimer = null;

const outreachForm = reactive({
  source_job_id: "",
  source_name: "",
  reply_text: "",
  max_items: 10,
  min_digg_count: 0,
});

const detailOpen = ref(false);
const detailLoading = ref(false);
const detailJob = ref(null);
const detailVideos = ref([]);
const detailComments = ref([]);

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

const detailTitle = computed(() => {
  if (!detailJob.value) return "任务详情";
  return detailJob.value.name || manualAccountLabel(detailJob.value);
});

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

function openOutreachDialog(row) {
  outreachForm.source_job_id = row.id;
  outreachForm.source_name = row.name || manualAccountLabel(row);
  outreachForm.reply_text = "";
  outreachForm.max_items = 10;
  outreachForm.min_digg_count = 0;
  selectedPresetId.value = "";
  createOutreachOpen.value = true;
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
      name: `${outreachForm.source_name} 评论触达`,
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

async function openJobDetail(row) {
  detailJob.value = row;
  detailOpen.value = true;
  detailLoading.value = true;
  detailVideos.value = [];
  detailComments.value = [];
  try {
    const videoResp = await listCollectVideos(row.id);
    detailVideos.value = videoResp.videos || [];
    const commentResp = await listCollectComments(row.id, { limit: 200 });
    detailComments.value = commentResp.comments || [];
  } catch (err) {
    ElMessage.error(err?.response?.data?.error || err?.message || "加载详情失败");
  } finally {
    detailLoading.value = false;
  }
}

async function selectVideo(row) {
  if (!detailJob.value || !row?.aweme_id) return;
  detailLoading.value = true;
  try {
    const commentResp = await listCollectComments(detailJob.value.id, {
      aweme_id: row.aweme_id,
      limit: 200,
    });
    detailComments.value = commentResp.comments || [];
  } catch (err) {
    ElMessage.error(err?.response?.data?.error || err?.message || "加载评论失败");
  } finally {
    detailLoading.value = false;
  }
}

onMounted(async () => {
  await Promise.all([refreshAll(), loadReplyPresets()]);
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
  gap: 20px;
}

.page-header {
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
  padding: 12px;
  background: #fff;
  border-radius: 12px;
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
