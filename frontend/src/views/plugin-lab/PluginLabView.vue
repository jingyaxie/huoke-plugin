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
        <el-tag v-if="pageSnapshot.detected_context" type="info">
          当前页：{{ contextLabel(pageSnapshot.detected_context) }}
        </el-tag>
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
              <el-checkbox v-model="params.waitPageLoad">等待页面加载</el-checkbox>
              <span class="field-hint">默认新建左侧半屏窗口；勾选则只聚焦已有标签</span>
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
              <span class="field-hint">默认 {{ defaultHints.scrollDistance }}，留空则随机 600~1200</span>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :xs="24" :sm="12" :md="8">
            <el-form-item label="评论滚动轮数">
              <el-input-number v-model="params.scrollRounds" :min="1" :max="30" controls-position="right" />
              <span class="field-hint">步骤 11</span>
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12" :md="8">
            <el-form-item label="最多评论数">
              <el-input-number v-model="params.maxComments" :min="1" :max="200" controls-position="right" />
              <span class="field-hint">步骤 11</span>
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
                :disabled="isActionDisabled({ id: 'click_filter_overlay' })"
              >
                <el-option v-for="item in filterOptions" :key="item" :label="item" :value="item" />
              </el-select>
              <span class="field-hint">步骤 5；抖音专用，小红书/快手自动跳过</span>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :xs="24" :sm="12" :md="8">
            <el-form-item label="搜索关键词">
              <el-input
                v-model="params.searchText"
                :placeholder="`默认：${defaultHints.searchText}`"
                clearable
              />
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
              <el-input
                v-model="params.dmText"
                type="textarea"
                :rows="2"
                placeholder="步骤 17 使用（仅抖音）"
                :disabled="isActionDisabled({ id: 'input_dm_text' })"
              />
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
      <p class="defaults-hint">
        当前平台默认值：搜索「{{ defaultHints.searchText }}」· 视频序号 {{ defaultHints.videoIndex }} ·
        评论 {{ defaultHints.scrollRounds }} 轮 / 最多 {{ defaultHints.maxComments }} 条
        <template v-if="params.platform === 'douyin'">
          · 筛选「{{ defaultHints.filterOption }}」
        </template>
        <span class="field-hint">（修改后会自动记住）</span>
      </p>
    </el-card>

    <el-card shadow="never" class="panel-block">
      <template #header>
        <div class="card-header">
          <span>自动化检测</span>
          <div class="header-actions-inline">
            <el-button size="small" @click="applyDefaults">恢复默认参数</el-button>
            <el-button
              size="small"
              type="primary"
              :loading="autoChecking"
              :disabled="autoRunning || bridgeStatus.connected_clients === 0"
              @click="runReadinessBatch"
            >
              检测就绪
            </el-button>
            <el-button
              size="small"
              type="warning"
              :loading="autoRunning"
              :disabled="autoChecking || bridgeStatus.connected_clients === 0"
              @click="runAutoFlow"
            >
              串联测试
            </el-button>
          </div>
        </div>
      </template>
      <p class="auto-hint">
        「检测就绪」只检查当前页面能否执行各步骤；「串联测试」会按顺序实际执行步骤 1→11（筛选/私信在
        小红书、快手自动跳过；这两平台不支持私信）。
      </p>
      <el-table v-if="autoResults.length" :data="autoResults" size="small" max-height="280">
        <el-table-column prop="label" label="步骤" min-width="180" />
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="autoStatusTag(row.status)" size="small">{{ autoStatusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="message" label="说明" min-width="240" show-overflow-tooltip />
      </el-table>
      <el-empty v-else description="点击「检测就绪」或「串联测试」查看各方法是否正常" />
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
            :disabled="(runningAction !== null && runningAction !== action.id) || isActionDisabled(action)"
            @click="runAction(action)"
          >
            {{ action.label }}
          </el-button>
          <p v-if="actionSkipReason(action)" class="action-skip">{{ actionSkipReason(action) }}</p>
          <p v-else class="action-desc">{{ action.description }}</p>
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
import { computed, onMounted, reactive, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import { fetchBridgeStatus, getLocalServiceBaseUrl } from "../../api/localService";
import {
  KNOWN_FILTER_OPTIONS,
  PLUGIN_LAB_ACTIONS,
  fetchPluginLabSnapshot,
  getActionSkipReason,
  runLabAutoFlow,
  runLabReadinessBatch,
  runPluginLabAction,
} from "../../api/pluginLab";
import {
  loadLastPluginLabPlatform,
  loadPluginLabParams,
  platformDefaultHints,
  resolveLabField,
  savePluginLabParams,
} from "../../utils/pluginLabParams";

const actions = PLUGIN_LAB_ACTIONS;
const filterOptions = KNOWN_FILTER_OPTIONS;
const localServiceUrl = getLocalServiceBaseUrl();

const statusLoading = ref(false);
const bridgeStatus = ref({ connected_clients: 0 });
const runningAction = ref(null);
const lastActionId = ref("");
const lastResult = ref(null);
const lastSearchItems = ref([]);
const lastError = ref("");
const actionLog = ref([]);
const displayRows = ref([]);
const pageSnapshot = ref({});
const autoChecking = ref(false);
const autoRunning = ref(false);
const autoResults = ref([]);

const CONTEXT_LABELS = {
  platform: "平台页",
  search: "搜索结果",
  video: "视频/Feed",
  profile: "用户主页",
};

function contextLabel(ctx) {
  return CONTEXT_LABELS[ctx] || ctx || "—";
}

const params = reactive(loadPluginLabParams(loadLastPluginLabPlatform()));

const defaultHints = computed(() => platformDefaultHints(params.platform));

function applyDefaults() {
  Object.assign(params, loadPluginLabParams(params.platform));
  savePluginLabParams(params.platform, params);
}

watch(
  () => params.platform,
  (platform, prev) => {
    if (platform === prev) return;
    Object.assign(params, loadPluginLabParams(platform));
  },
);

watch(
  () => ({ ...params }),
  () => {
    savePluginLabParams(params.platform, params);
  },
  { deep: true },
);

function actionSkipReason(action) {
  return getActionSkipReason(action.id, params.platform);
}

function isActionDisabled(action) {
  return Boolean(actionSkipReason(action));
}

function autoStatusTag(status) {
  if (status === "pass" || status === "ready") return "success";
  if (status === "skipped") return "info";
  if (status === "not_ready" || status === "fail") return "warning";
  return "danger";
}

function autoStatusLabel(status) {
  const map = {
    pass: "通过",
    ready: "就绪",
    skipped: "跳过",
    not_ready: "未就绪",
    fail: "失败",
    error: "错误",
  };
  return map[status] || status;
}

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
  const platform = params.platform;
  const payload = {};
  if (action.id === "swipe_page") {
    payload.direction = params.scrollDirection;
    const distance = resolveLabField(platform, "scrollDistance", params.scrollDistance);
    if (distance) payload.distance = Number(distance);
  }
  if (action.id === "open_browser") {
    payload.platform = platform;
    payload.reuse_existing = params.reuseExisting;
    if (params.waitPageLoad) payload.wait_load = true;
  }
  if (action.id === "find_search_box" || action.id === "input_search_text") {
    payload.platform = platform;
  }
  if (action.id === "click_filter_overlay") {
    const raw = resolveLabField(platform, "filterOption", params.filterOption).trim();
    if (raw.includes(",")) {
      payload.option_labels = raw.split(",").map((item) => item.trim()).filter(Boolean);
    } else if (raw) {
      payload.option_label = raw;
    }
  }
  if (action.needsSearchText) {
    payload.search_text = resolveLabField(platform, "searchText", params.searchText);
  }
  if (action.needsVideoIndex) {
    payload.video_index = Number(resolveLabField(platform, "videoIndex", params.videoIndex)) || 1;
    const cached = lastSearchItems.value[payload.video_index - 1];
    if (cached?.rect) payload.rect = cached.rect;
  }
  if (action.needsReplyText) {
    payload.reply_text = resolveLabField(platform, "replyText", params.replyText);
    payload.comment_index = Number(resolveLabField(platform, "commentIndex", params.commentIndex)) || 1;
  }
  if (action.needsDmText) {
    payload.dm_text = resolveLabField(platform, "dmText", params.dmText);
  }
  if (action.id === "send_dm") {
    const dmText = resolveLabField(platform, "dmText", params.dmText).trim();
    if (dmText) payload.dm_text = dmText;
  }
  if (action.id === "click_comment_avatar") {
    payload.comment_index = Number(resolveLabField(platform, "commentIndex", params.commentIndex)) || 1;
  }
  if (action.id === "scroll_and_collect_comments") {
    payload.scroll_rounds = Number(resolveLabField(platform, "scrollRounds", params.scrollRounds)) || 4;
    payload.max_comments = Number(resolveLabField(platform, "maxComments", params.maxComments)) || 20;
  }
  if (action.id === "fetch_search_results") {
    payload.limit = 20;
    payload.api_timeout_ms = 12000;
  }
  return payload;
}

function validateParams(action) {
  if (isActionDisabled(action)) {
    ElMessage.info(actionSkipReason(action));
    return false;
  }
  if (action.needsSearchText && !resolveLabField(params.platform, "searchText", params.searchText).trim()) {
    ElMessage.warning("请先填写搜索关键词");
    return false;
  }
  if (action.needsFilterOption && !resolveLabField(params.platform, "filterOption", params.filterOption).trim()) {
    ElMessage.warning("请先填写筛选选项");
    return false;
  }
  if (action.needsReplyText && !resolveLabField(params.platform, "replyText", params.replyText).trim()) {
    ElMessage.warning("请先填写回复文案");
    return false;
  }
  if (action.needsDmText && !resolveLabField(params.platform, "dmText", params.dmText).trim()) {
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

async function runReadinessBatch() {
  autoChecking.value = true;
  autoResults.value = [];
  try {
    const results = await runLabReadinessBatch(params.platform, actions, (_row, all) => {
      autoResults.value = [...all];
    });
    autoResults.value = results;
    const failed = results.filter((row) => row.status === "not_ready" || row.status === "error").length;
    if (failed === 0) {
      ElMessage.success("就绪检测完成，当前页面可执行已标记步骤");
    } else {
      ElMessage.warning(`就绪检测完成，${failed} 个步骤当前不可执行（可能需先执行前置步骤）`);
    }
  } catch (err) {
    ElMessage.error(err?.message || "就绪检测失败");
  } finally {
    autoChecking.value = false;
  }
}

async function runAutoFlow() {
  if (bridgeStatus.value.connected_clients === 0) {
    ElMessage.warning("请先连接 Chrome 插件");
    return;
  }
  autoRunning.value = true;
  autoResults.value = [];
  try {
    const results = await runLabAutoFlow(
      params.platform,
      buildPayload,
      actions,
      (_row, all) => {
        autoResults.value = [...all];
      },
    );
    autoResults.value = results;
    const failed = results.find((row) => row.status === "fail" || row.status === "error");
    if (!failed) {
      ElMessage.success("串联测试完成");
    } else {
      ElMessage.warning(`串联测试在「${failed.label}」停止：${failed.message}`);
    }
  } catch (err) {
    ElMessage.error(err?.message || "串联测试失败");
  } finally {
    autoRunning.value = false;
  }
}

async function refreshStatus() {
  statusLoading.value = true;
  try {
    bridgeStatus.value = await fetchBridgeStatus();
    if (bridgeStatus.value.connected_clients > 0) {
      void fetchPluginLabSnapshot()
        .then((snap) => {
          pageSnapshot.value = snap?.data ?? {};
        })
        .catch(() => {
          pageSnapshot.value = {};
        });
    } else {
      pageSnapshot.value = {};
    }
  } catch {
    bridgeStatus.value = { connected_clients: 0 };
    pageSnapshot.value = {};
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

    const searchItems = resultBody?.items || resultBody?.results;
    if (Array.isArray(searchItems) && searchItems.length > 0) {
      lastSearchItems.value = searchItems;
    }

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
    if (bridgeStatus.value.connected_clients > 0) {
      void fetchPluginLabSnapshot()
        .then((snap) => {
          pageSnapshot.value = snap?.data ?? {};
        })
        .catch(() => {});
    }
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

.action-skip {
  margin: 0;
  font-size: 12px;
  color: var(--el-color-warning);
  line-height: 1.4;
}

.header-actions-inline {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.auto-hint {
  margin: 0 0 12px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
}

.defaults-hint {
  margin: 12px 0 0;
  padding-top: 12px;
  border-top: 1px solid var(--el-border-color-lighter);
  font-size: 13px;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
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
