<template>
  <div class="plugin-lab-page">
    <header class="page-header">
      <div>
        <h1 class="page-title">插件实验室</h1>
        <p class="page-subtitle">
          逐步测试 Chrome 插件对浏览器的控制能力。先点单步按钮联调元素，再串联完整获客流程。
        </p>
      </div>
      <div class="header-actions">
        <el-tag :type="bridgeTagType">{{ bridgeLabel }}</el-tag>
        <el-button @click="refreshStatus" :loading="statusLoading">刷新状态</el-button>
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
        请确认插件已加载且角标为 <strong>OK</strong>，本地服务运行在
        <code>{{ localServiceUrl }}</code>。
      </template>
    </el-alert>

    <el-card shadow="never" class="panel-block">
      <template #header>
        <span>测试参数</span>
      </template>
      <el-form label-width="120px" class="params-form">
        <el-row :gutter="16">
          <el-col :xs="24" :sm="12" :md="8">
            <el-form-item label="目标平台">
              <el-select v-model="params.platform" style="width: 100%">
                <el-option label="抖音" value="douyin" />
                <el-option label="小红书" value="xiaohongshu" />
                <el-option label="快手" value="kuaishou" />
              </el-select>
              <span class="field-hint">步骤 1 使用</span>
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12" :md="8">
            <el-form-item label="打开方式">
              <el-checkbox v-model="params.reuseExisting">复用已有窗口</el-checkbox>
              <span class="field-hint">未勾选时新建独立 Chrome 窗口</span>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :xs="24" :sm="12" :md="8">
            <el-form-item label="滚动方向">
              <el-select v-model="params.scrollDirection" style="width: 100%">
                <el-option label="向下" value="down" />
                <el-option label="向上" value="up" />
              </el-select>
              <span class="field-hint">步骤 2 使用</span>
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12" :md="8">
            <el-form-item label="滚动距离(px)">
              <el-input-number
                v-model="params.scrollDistance"
                :min="120"
                :max="4000"
                :step="100"
                controls-position="right"
              />
              <span class="field-hint">留空则随机 600~1200</span>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :xs="24" :sm="12" :md="8">
            <el-form-item label="筛选选项">
              <el-select
                v-model="params.filterOption"
                filterable
                allow-create
                clearable
                placeholder="选择或输入，如：一天内"
                style="width: 100%"
              >
                <el-option v-for="item in filterOptions" :key="item" :label="item" :value="item" />
              </el-select>
              <span class="field-hint">步骤 5；多个用英文逗号，如 一天内,视频</span>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :xs="24" :sm="12" :md="8">
            <el-form-item label="搜索关键词">
              <el-input v-model="params.searchText" placeholder="步骤 6 使用" clearable />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12" :md="8">
            <el-form-item label="视频序号">
              <el-input-number v-model="params.videoIndex" :min="1" :max="50" controls-position="right" />
              <span class="field-hint">步骤 9，从 1 开始</span>
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12" :md="8">
            <el-form-item label="评论序号">
              <el-input-number v-model="params.commentIndex" :min="1" :max="50" controls-position="right" />
              <span class="field-hint">步骤 12/14，从 1 开始</span>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :xs="24" :sm="12">
            <el-form-item label="回复文案">
              <el-input v-model="params.replyText" type="textarea" :rows="2" placeholder="步骤 12 使用" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="私信文案">
              <el-input v-model="params.dmText" type="textarea" :rows="2" placeholder="步骤 17 使用" />
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
    </el-card>

    <el-card shadow="never" class="panel-block">
      <template #header>
        <div class="card-header">
          <span>单步测试</span>
          <el-button size="small" :disabled="runningAction !== null" @click="clearLog">清空日志</el-button>
        </div>
      </template>

      <div class="action-grid">
        <div v-for="action in actions" :key="action.id" class="action-item">
          <el-button
            class="action-btn"
            :type="lastActionId === action.id && !lastError ? 'success' : 'default'"
            :loading="runningAction === action.id"
            :disabled="runningAction !== null && runningAction !== action.id"
            @click="runAction(action)"
          >
            {{ action.label }}
          </el-button>
          <p class="action-desc">{{ action.description }}</p>
        </div>
      </div>
    </el-card>

    <el-row :gutter="16" class="panel-block">
      <el-col :xs="24" :lg="12">
        <el-card shadow="never">
          <template #header>
            <span>最近响应</span>
          </template>
          <div v-if="lastError" class="result-error">
            <el-alert type="error" :title="lastError" :closable="false" show-icon />
          </div>
          <pre v-if="lastResult" class="result-json">{{ formatJson(lastResult) }}</pre>
          <el-empty v-if="!lastResult && !lastError" description="点击上方按钮开始测试" />
        </el-card>
      </el-col>

      <el-col :xs="24" :lg="12">
        <el-card shadow="never">
          <template #header>
            <div class="card-header">
              <span>搜索结果 / 评论数据</span>
            </div>
          </template>
          <el-table
            v-if="displayRows.length"
            :data="displayRows"
            size="small"
            max-height="360"
            empty-text="暂无数据"
          >
            <el-table-column type="index" label="#" width="48" />
            <el-table-column prop="title" label="标题/内容" min-width="180" show-overflow-tooltip />
            <el-table-column prop="author" label="作者" width="100" show-overflow-tooltip />
            <el-table-column prop="extra" label="附加" width="80" show-overflow-tooltip />
          </el-table>
          <el-empty v-else description="步骤 8 或 11 执行后会展示数据" />
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never" class="panel-block">
      <template #header>
        <span>操作日志</span>
      </template>
      <el-timeline v-if="actionLog.length">
        <el-timeline-item
          v-for="entry in actionLog"
          :key="entry.id"
          :type="entry.ok ? 'success' : 'danger'"
          :timestamp="entry.time"
        >
          <strong>{{ entry.label }}</strong>
          <span v-if="entry.message" class="log-message"> — {{ entry.message }}</span>
        </el-timeline-item>
      </el-timeline>
      <el-empty v-else description="暂无操作记录" />
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import { fetchBridgeStatus, getLocalServiceBaseUrl } from "../../api/localService";
import {
  KNOWN_FILTER_OPTIONS,
  PLUGIN_LAB_ACTIONS,
  runPluginLabAction,
} from "../../api/pluginLab";

const actions = PLUGIN_LAB_ACTIONS;
const filterOptions = KNOWN_FILTER_OPTIONS;
const localServiceUrl = getLocalServiceBaseUrl();

const statusLoading = ref(false);
const bridgeStatus = ref({ connected_clients: 0 });
const runningAction = ref(null);
const lastActionId = ref("");
const lastResult = ref(null);
const lastError = ref("");
const actionLog = ref([]);
const displayRows = ref([]);

const params = reactive({
  platform: "douyin",
  reuseExisting: false,
  scrollDirection: "down",
  scrollDistance: null,
  filterOption: "一天内",
  searchText: "",
  videoIndex: 1,
  commentIndex: 1,
  replyText: "",
  dmText: "",
});

let logSeq = 0;

const bridgeLabel = computed(() => {
  const count = Number(bridgeStatus.value.connected_clients || 0);
  return count > 0 ? `插件已连接 (${count})` : "插件未连接";
});

const bridgeTagType = computed(() =>
  Number(bridgeStatus.value.connected_clients || 0) > 0 ? "success" : "warning",
);

function formatJson(value) {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function buildPayload(action) {
  const payload = {};
  if (action.id === "swipe_page") {
    payload.direction = params.scrollDirection;
    if (params.scrollDistance) payload.distance = params.scrollDistance;
  }
  if (action.id === "open_browser") {
    payload.platform = params.platform;
    payload.reuse_existing = params.reuseExisting;
    payload.wait_load = true;
  }
  if (action.id === "find_search_box" || action.id === "input_search_text") {
    payload.platform = params.platform;
  }
  if (action.id === "click_filter_overlay") {
    const raw = params.filterOption.trim();
    if (raw.includes(",")) {
      payload.option_labels = raw.split(",").map((item) => item.trim()).filter(Boolean);
    } else {
      payload.option_label = raw;
    }
  }
  if (action.needsSearchText) payload.search_text = params.searchText;
  if (action.needsVideoIndex) payload.video_index = params.videoIndex;
  if (action.needsReplyText) {
    payload.reply_text = params.replyText;
    payload.comment_index = params.commentIndex;
  }
  if (action.needsDmText) payload.dm_text = params.dmText;
  if (action.id === "click_comment_avatar") payload.comment_index = params.commentIndex;
  return payload;
}

function validateParams(action) {
  if (action.needsSearchText && !params.searchText.trim()) {
    ElMessage.warning("请先填写搜索关键词");
    return false;
  }
  if (action.needsFilterOption && !params.filterOption.trim()) {
    ElMessage.warning("请先填写筛选选项");
    return false;
  }
  if (action.needsReplyText && !params.replyText.trim()) {
    ElMessage.warning("请先填写回复文案");
    return false;
  }
  if (action.needsDmText && !params.dmText.trim()) {
    ElMessage.warning("请先填写私信文案");
    return false;
  }
  return true;
}

function normalizeDisplayData(actionId, data) {
  if (!data) return [];
  if (actionId === "click_filter_overlay" && Array.isArray(data.available_options)) {
    return data.available_options.map((text) => ({
      title: text,
      author: data.clicked_labels?.includes(text) ? "已点击" : "可选",
      extra: "",
    }));
  }
  const items = data.items || data.results || data.videos || data.comments || data.data || [];
  if (!Array.isArray(items)) return [];

  return items.map((row, index) => ({
    title: row.title || row.content || row.desc || row.text || `条目 ${index + 1}`,
    author: row.author || row.username || row.nickname || row.user || "—",
    extra: row.id || row.aweme_id || row.index || row.comment_id || "",
  }));
}

function appendLog(action, ok, message) {
  actionLog.value.unshift({
    id: ++logSeq,
    label: action.label,
    ok,
    message,
    time: new Date().toLocaleTimeString(),
  });
  if (actionLog.value.length > 50) {
    actionLog.value.length = 50;
  }
}

async function refreshStatus() {
  statusLoading.value = true;
  try {
    bridgeStatus.value = await fetchBridgeStatus();
  } catch {
    bridgeStatus.value = { connected_clients: 0 };
  } finally {
    statusLoading.value = false;
  }
}

async function runAction(action) {
  if (!validateParams(action)) return;

  runningAction.value = action.id;
  lastActionId.value = action.id;
  lastError.value = "";
  lastResult.value = null;

  const payload = buildPayload(action);

  try {
    const data = await runPluginLabAction(action.id, payload);
    lastResult.value = data;
    const resultBody = data?.data ?? data;
    const actionOk = resultBody?.ok !== false;

    if (action.returnsData || action.id === "click_filter_overlay") {
      displayRows.value = normalizeDisplayData(action.id, resultBody);
    }

    if (!actionOk) {
      const failMessage = resultBody?.message || data?.message || "操作未成功";
      lastError.value = failMessage;
      appendLog(action, false, failMessage);
      ElMessage.warning(failMessage);
      return;
    }

    appendLog(action, true, data?.message || resultBody?.message || "成功");
    ElMessage.success(`${action.label} 完成`);
  } catch (err) {
    const message =
      err?.response?.data?.error ||
      err?.response?.data?.detail ||
      err?.message ||
      "请求失败";
    lastError.value = message;
    appendLog(action, false, message);
    ElMessage.error(message);
  } finally {
    runningAction.value = null;
  }
}

function clearLog() {
  actionLog.value = [];
  lastResult.value = null;
  lastError.value = "";
  displayRows.value = [];
  lastActionId.value = "";
}

onMounted(() => {
  void refreshStatus();
});
</script>

<style scoped>
.plugin-lab-page {
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

.page-subtitle {
  margin: 6px 0 0;
  color: var(--el-text-color-secondary);
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.panel-block {
  width: 100%;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.params-form {
  max-width: 960px;
}

.field-hint {
  margin-left: 8px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.action-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px 16px;
}

.action-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.action-btn {
  width: 100%;
  justify-content: flex-start;
  text-align: left;
}

.action-desc {
  margin: 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.4;
}

.result-json {
  margin: 0;
  padding: 12px;
  background: var(--el-fill-color-light);
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.5;
  overflow: auto;
  max-height: 360px;
}

.result-error {
  margin-bottom: 12px;
}

.log-message {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
</style>
