<template>
  <el-dialog
    v-model="visible"
    title="创建自动获客任务"
    width="760px"
    destroy-on-close
    class="create-task-dialog"
    @closed="resetForm"
  >
    <div class="dialog-body">
      <el-form label-width="120px">
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="选择地区">
              <el-select v-model="form.regionCode" placeholder="请选择地区" style="width: 100%">
                <el-option
                  v-for="item in REGION_PRESETS"
                  :key="item.code || 'any'"
                  :label="item.name"
                  :value="item.code"
                />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="任务名称" required>
              <el-input v-model="form.name" placeholder="例如：深圳餐饮老板线索" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-form-item label="选择账号">
          <el-select v-model="form.selectedAccountKey" placeholder="请选择执行账号" style="width: 100%">
            <el-option
              v-for="option in accountOptions"
              :key="option.key"
              :label="option.label"
              :value="option.key"
            />
          </el-select>
          <p v-if="!accountOptions.length" class="field-hint warning">
            当前渠道尚未完成绑定，请先在「账号设置」完成浏览器绑定。
          </p>
        </el-form-item>

        <el-form-item label="选择渠道" required>
          <el-radio-group v-model="form.platform">
            <el-radio-button
              v-for="item in supportedPlatforms"
              :key="item"
              :value="item"
            >
              {{ platformLabel(item) }}
            </el-radio-button>
          </el-radio-group>
        </el-form-item>

        <TaskAcquisitionStrategyField
          v-if="form.platform === 'douyin'"
          v-model="form.agentStrategy"
          :platform="form.platform"
        />

        <BrowserModeField v-model="form.browserMode" />

        <el-form-item :label="keywordLabel" required>
          <el-input
            v-model="form.keywords"
            placeholder="输入产品或服务关键词，例如：团餐配送"
          />
          <p v-if="composedSearchKeyword" class="field-hint">
            实际搜索词：<strong>{{ composedSearchKeyword }}</strong>
            <span v-if="regionName">（{{ regionName }} + 关键词）</span>
          </p>
        </el-form-item>

        <el-form-item v-if="hasAutoScopeField('publish_time_range', capabilities)" label="视频发布时间">
          <el-radio-group v-model="form.publishTimeRange">
            <el-radio-button
              v-for="item in publishOptions"
              :key="item.value"
              :value="item.value"
            >
              {{ item.label }}
            </el-radio-button>
          </el-radio-group>
        </el-form-item>

        <el-form-item v-if="hasScopeField('home_auto', 'comment_days', capabilities)" label="采集几天内评论">
          <el-radio-group v-model="form.commentDays">
            <el-radio-button
              v-for="item in commentOptions"
              :key="item.value"
              :value="Number(item.value)"
            >
              {{ item.label }}
            </el-radio-button>
          </el-radio-group>
        </el-form-item>

        <el-form-item v-if="hasScopeField('home_auto', 'target_count', capabilities)" :label="targetCountLabel" required>
          <el-input-number v-model="form.targetCount" :min="1" :max="500" />
          <p class="field-hint">{{ targetCountHint }}</p>
        </el-form-item>

        <el-form-item v-if="isStandalone && hasScopeField('home_auto', 'target_count', capabilities)" label="单批扫描视频上限">
          <el-input-number v-model="form.crawlVideoLimit" :min="1" :max="500" />
          <p class="field-hint">{{ crawlVideoLimitHint }}</p>
        </el-form-item>

        <TaskEvaluationSection
          v-model:expanded="form.evalExpanded"
          v-model:eval-template-id="form.evalTemplateId"
          v-model:target-customer="form.targetCustomer"
          v-model:accept-description="form.acceptDescription"
          v-model:reject-signals="form.rejectSignals"
          :templates="evaluationTemplates"
        />

        <el-row v-if="settings.comment_dm_percentage > 0 || settings.comment_dm_percentage < 100" :gutter="16">
          <el-col v-if="settings.comment_dm_percentage > 0" :span="12">
            <TaskPresetSelect
              label="评论模板"
              :options="commentPresets"
              :selected-ids="selectedCommentPresetIds"
              @update:selected-ids="selectedCommentPresetIds = $event"
            />
          </el-col>
          <el-col v-if="settings.comment_dm_percentage < 100" :span="12">
            <TaskPresetSelect
              label="私信模板"
              :options="dmPresets"
              :selected-ids="selectedDmPresetIds"
              @update:selected-ids="selectedDmPresetIds = $event"
            />
          </el-col>
        </el-row>

        <TaskInteractionFields v-model="settings" />

        <TaskReadinessPanel
          :loading="preflightLoading"
          :error="preflightError"
          :result="preflight"
          v-model:acknowledged="preflightAcknowledged"
        />
      </el-form>
    </div>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="submitting" :disabled="!canSubmit" @click="submit">
        {{ submitting ? "创建中…" : preflightLoading ? "检查中…" : "创建任务" }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import BrowserModeField from "./BrowserModeField.vue";
import TaskAcquisitionStrategyField from "./TaskAcquisitionStrategyField.vue";
import TaskEvaluationSection from "./TaskEvaluationSection.vue";
import TaskInteractionFields from "./TaskInteractionFields.vue";
import TaskPresetSelect from "./TaskPresetSelect.vue";
import TaskReadinessPanel from "./TaskReadinessPanel.vue";
import { setAccountId, setPlatformId } from "../api/http";
import {
  buildAutoTaskPayload,
  createExternalTask,
  fetchExternalCapabilities,
  preflightExternalTask,
} from "../api/externalTasks";
import {
  DEFAULT_INTERACTION_SETTINGS,
  getInteractionSettings,
  listPlatformPresets,
  putInteractionSettings,
} from "../api/presets";
import { setActiveAccount } from "../api/accounts";
import {
  REGION_PRESETS,
  FALLBACK_COMMENT_DAYS_OPTIONS,
  FALLBACK_PUBLISH_TIME_OPTIONS,
  applyDefaultCommentDays,
  browserModeToHeadless,
  buildEvaluationPayload,
  composeSearchKeyword,
  getFieldOptions,
  getScopeFieldLabel,
  hasAutoScopeField,
  hasScopeField,
  listSupportedPlatforms,
  platformLabel,
  validateRequiredScopeFields,
} from "../utils/huokeTaskForm";
import { buildAutoPreflightPayload } from "../utils/huokeTaskPreflight";
import { isStandaloneDouyinStrategy } from "../utils/acquisitionStrategy";
import { validateTaskPresetSelection } from "../utils/presetSelection";
import { loadTaskAccountOptions, taskAccountOptionToBindingRef } from "../utils/taskAccountOptions";

const props = defineProps({
  modelValue: { type: Boolean, default: false },
});

const emit = defineEmits(["update:modelValue", "created"]);

const visible = ref(false);
const submitting = ref(false);
const preflightLoading = ref(false);
const preflightError = ref("");
const preflight = ref(null);
const preflightAcknowledged = ref(false);
const capabilities = ref(null);
const accountOptions = ref([]);
const commentPresets = ref([]);
const dmPresets = ref([]);
const selectedCommentPresetIds = ref([]);
const selectedDmPresetIds = ref([]);
const settings = ref({ ...DEFAULT_INTERACTION_SETTINGS });

const form = reactive({
  name: "",
  regionCode: "",
  selectedAccountKey: "",
  platform: "douyin",
  agentStrategy: "",
  browserMode: "headed",
  keywords: "",
  publishTimeRange: "unlimited",
  commentDays: 3,
  targetCount: 50,
  crawlVideoLimit: 50,
  evalExpanded: false,
  evalTemplateId: "",
  targetCustomer: "",
  acceptDescription: "",
  rejectSignals: "",
});

watch(
  () => props.modelValue,
  (value) => {
    visible.value = value;
    if (value) void loadDialogData();
  },
  { immediate: true },
);

watch(visible, (value) => {
  emit("update:modelValue", value);
});

const supportedPlatforms = computed(() => listSupportedPlatforms(capabilities.value));
const publishOptions = computed(() =>
  getFieldOptions(capabilities.value, "publish_time_range", FALLBACK_PUBLISH_TIME_OPTIONS),
);
const commentOptions = computed(() =>
  getFieldOptions(capabilities.value, "comment_days", FALLBACK_COMMENT_DAYS_OPTIONS),
);
const evaluationTemplates = computed(() => capabilities.value?.evaluation_templates || []);
const regionName = computed(() => REGION_PRESETS.find((row) => row.code === form.regionCode)?.name || "");
const composedSearchKeyword = computed(() => {
  const keyword = keywordList()[0] || "";
  if (!keyword) return "";
  return composeSearchKeyword(keyword, regionName.value);
});
const keywordLabel = computed(() => getScopeFieldLabel("home_auto", "keyword", capabilities.value, "产品关键词"));
const isStandalone = computed(() => isStandaloneDouyinStrategy(form.agentStrategy));
const targetCountLabel = computed(() => (isStandalone.value ? "目标精准线索" : "预设抓取数量"));
const targetCountHint = computed(() =>
  isStandalone.value
    ? "要凑够多少条「精准线索」任务才算达标；与下面扫描视频数无关。"
    : "建议单次预设抓取数量控制在 30-100 条，系统将用 LLM 评估评论是否符合线索标准。",
);
const crawlVideoLimitHint = computed(() =>
  "每轮最多浏览多少个视频；未凑够精准线索会自动续扫下一批。留空概念上等同较大默认值（约 200）。",
);

const canSubmit = computed(() => {
  if (submitting.value || preflightLoading.value) return false;
  if (!preflight.value?.ready) return false;
  if (preflight.value.warning_count > 0 && !preflightAcknowledged.value) return false;
  return true;
});

function keywordList() {
  return form.keywords
    .split(/[,，\s]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function evaluationPayload() {
  return buildEvaluationPayload({
    evalTemplateId: form.evalTemplateId,
    targetCustomer: form.targetCustomer,
    acceptDescription: form.acceptDescription,
    rejectSignals: form.rejectSignals,
  });
}

function syncRequestContext() {
  setPlatformId(form.platform);
  const accountId = form.selectedAccountKey.split(":")[0];
  if (accountId) setAccountId(accountId);
}

async function loadDialogData() {
  preflight.value = null;
  preflightError.value = "";
  preflightAcknowledged.value = false;
  try {
    const interaction = await getInteractionSettings();
    settings.value = { ...DEFAULT_INTERACTION_SETTINGS, ...interaction };
  } catch {
    settings.value = { ...DEFAULT_INTERACTION_SETTINGS };
  }
  try {
    capabilities.value = await fetchExternalCapabilities(form.platform);
    form.commentDays = Number(applyDefaultCommentDays("home_auto", capabilities.value)) || 3;
  } catch {
    capabilities.value = null;
  }
  await reloadAccountsAndPresets();
}

async function reloadAccountsAndPresets() {
  try {
    accountOptions.value = await loadTaskAccountOptions(form.platform);
    if (accountOptions.value.length === 1) {
      form.selectedAccountKey = accountOptions.value[0].key;
    } else if (!accountOptions.value.some((row) => row.key === form.selectedAccountKey)) {
      form.selectedAccountKey = "";
    }
  } catch {
    accountOptions.value = [];
    form.selectedAccountKey = "";
  }
  try {
    const presets = await listPlatformPresets();
    commentPresets.value = presets.comments;
    dmPresets.value = presets.dmOpeners;
    selectedCommentPresetIds.value = presets.comments.map((row) => row.id);
    selectedDmPresetIds.value = presets.dmOpeners.map((row) => row.id);
  } catch {
    commentPresets.value = [];
    dmPresets.value = [];
    selectedCommentPresetIds.value = [];
    selectedDmPresetIds.value = [];
  }
}

watch(
  () => form.platform,
  async () => {
    if (!visible.value) return;
    syncRequestContext();
    try {
      capabilities.value = await fetchExternalCapabilities(form.platform);
      form.commentDays = Number(applyDefaultCommentDays("home_auto", capabilities.value)) || 3;
    } catch {
      capabilities.value = null;
    }
    await reloadAccountsAndPresets();
  },
);

watch(
  () => [
    form.platform,
    form.keywords,
    form.targetCount,
    form.commentDays,
    form.publishTimeRange,
    form.regionCode,
    form.browserMode,
    form.name,
    form.agentStrategy,
    form.evalTemplateId,
    form.targetCustomer,
    form.acceptDescription,
    form.rejectSignals,
    settings.value,
    selectedCommentPresetIds.value,
    selectedDmPresetIds.value,
    form.selectedAccountKey,
  ],
  () => {
    if (!visible.value) return;
    const keywords = keywordList();
    if (!keywords.length || !form.targetCount || form.targetCount < 1) {
      preflight.value = null;
      preflightError.value = "";
      preflightAcknowledged.value = false;
      return;
    }
    syncRequestContext();
    const timer = window.setTimeout(async () => {
      preflightLoading.value = true;
      preflightError.value = "";
      preflightAcknowledged.value = false;
      try {
        const payload = buildAutoPreflightPayload({
          platform: form.platform,
          keywords,
          publishTime: form.publishTimeRange,
          commentDays: form.commentDays,
          target: form.targetCount,
          crawlVideoLimit: isStandalone.value ? form.crawlVideoLimit : undefined,
          regionName: regionName.value || undefined,
          regionCode: form.regionCode || undefined,
          headless: browserModeToHeadless(form.browserMode),
          settings: settings.value,
          commentPresetIds: selectedCommentPresetIds.value,
          dmPresetIds: selectedDmPresetIds.value,
          evaluation: evaluationPayload(),
          agentStrategy: form.agentStrategy,
          taskName: form.name.trim() || `关键词获客-${keywords[0]}`,
        });
        preflight.value = await preflightExternalTask(payload);
      } catch (err) {
        preflight.value = null;
        preflightError.value = err.message || "预检失败";
      } finally {
        preflightLoading.value = false;
      }
    }, 700);
    return () => window.clearTimeout(timer);
  },
  { deep: true },
);

function resetForm() {
  form.name = "";
  form.regionCode = "";
  form.selectedAccountKey = "";
  form.platform = "douyin";
  form.agentStrategy = "";
  form.browserMode = "headed";
  form.keywords = "";
  form.publishTimeRange = "unlimited";
  form.commentDays = 3;
  form.targetCount = 50;
  form.crawlVideoLimit = 50;
  form.evalExpanded = false;
  form.evalTemplateId = "";
  form.targetCustomer = "";
  form.acceptDescription = "";
  form.rejectSignals = "";
  preflight.value = null;
  preflightError.value = "";
  preflightAcknowledged.value = false;
}

async function submit() {
  const keywords = keywordList();
  if (!form.name.trim()) {
    ElMessage.warning("请填写任务名称");
    return;
  }
  const validationError = validateRequiredScopeFields(
    "home_auto",
    {
      keyword: keywords[0] || "",
      target_count: form.targetCount,
      comment_days: form.commentDays,
      publish_time_range: form.publishTimeRange,
      region: regionName.value || form.regionCode,
    },
    capabilities.value,
  );
  if (validationError) {
    ElMessage.warning(validationError);
    return;
  }
  if (!form.targetCount || form.targetCount < 1) {
    ElMessage.warning("预设抓取数量必须大于 0");
    return;
  }
  const presetError = validateTaskPresetSelection(
    settings.value,
    selectedCommentPresetIds.value,
    selectedDmPresetIds.value,
  );
  if (presetError) {
    ElMessage.warning(presetError);
    return;
  }
  if (!preflight.value?.ready) {
    ElMessage.warning("任务预检未通过，请先解决「执行就绪检查」中的阻塞项");
    return;
  }
  if (preflight.value.warning_count > 0 && !preflightAcknowledged.value) {
    ElMessage.warning("请先勾选「我已了解上述提醒，仍要创建任务」");
    return;
  }

  submitting.value = true;
  try {
    syncRequestContext();
    const accountId = form.selectedAccountKey.split(":")[0];
    if (accountId) {
      await setActiveAccount(accountId).catch(() => {});
    }
    await putInteractionSettings(settings.value).catch(() => {});

    const selectedOption = accountOptions.value.find((row) => row.key === form.selectedAccountKey);
    const binding = taskAccountOptionToBindingRef(selectedOption);
    const payload = buildAutoTaskPayload({
      name: form.name.trim(),
      platform: form.platform,
      keyword: keywords[0],
      regionName: regionName.value,
      targetCount: form.targetCount,
      crawlVideoLimit: isStandalone.value ? form.crawlVideoLimit : undefined,
      commentDays: form.commentDays,
      publishTimeRange: form.publishTimeRange,
      headless: browserModeToHeadless(form.browserMode),
      settings: settings.value,
      commentPresetIds: selectedCommentPresetIds.value,
      dmPresetIds: selectedDmPresetIds.value,
      commentPresets: commentPresets.value,
      dmPresets: dmPresets.value,
      evaluation: evaluationPayload(),
      binding,
      agentStrategy: form.agentStrategy,
    });
    const job = await createExternalTask(payload);
    ElMessage.success("任务已创建");
    visible.value = false;
    emit("created", job);
  } catch (err) {
    ElMessage.error(err.message || "创建失败");
  } finally {
    submitting.value = false;
  }
}
</script>

<style scoped>
.create-task-dialog :deep(.el-dialog__body) {
  max-height: 70vh;
  overflow-y: auto;
}

.dialog-body {
  padding-right: 4px;
}

.field-hint {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.field-hint.warning {
  color: var(--el-color-warning);
}
</style>
