<template>
  <el-dialog
    v-model="visible"
    title="创建手动获客任务"
    width="760px"
    destroy-on-close
    class="create-task-dialog"
    @closed="resetForm"
  >
    <div class="dialog-body">
      <el-form label-width="120px">
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

        <el-form-item label="获客方式" required>
          <el-radio-group v-model="form.intent">
            <el-radio
              v-for="item in manualModeOptions"
              :key="item.value"
              :value="item.value"
            >
              {{ item.label }}
            </el-radio>
          </el-radio-group>
          <p v-if="selectedMode?.description" class="field-hint">{{ selectedMode.description }}</p>
        </el-form-item>

        <TaskAcquisitionStrategyField
          v-if="form.platform === 'douyin'"
          v-model="form.agentStrategy"
          :platform="form.platform"
        />

        <BrowserModeField v-model="form.browserMode" />

        <el-form-item :label="urlLabel" required>
          <el-input v-model="form.inputUrl" :placeholder="urlPlaceholder" />
          <p v-if="urlHint" class="field-hint">{{ urlHint }}</p>
          <p v-if="urlError" class="field-hint error">{{ urlError }}</p>
        </el-form-item>

        <el-form-item v-if="showManualTargetCount" label="目标精准线索">
          <el-input-number v-model="form.targetCount" :min="1" :max="100" />
          <p class="field-hint">要凑够多少条精准线索；与下方「扫描视频数」无关。</p>
        </el-form-item>

        <el-form-item v-if="effectiveIntent === 'account_home'" label="扫描视频数">
          <el-input-number v-model="form.crawlVideoLimit" :min="1" :max="200" />
          <p class="field-hint">主页模式下每轮最多点进多少个作品抓评论；未凑够精准线索会继续扫。</p>
        </el-form-item>

        <el-form-item v-if="hasScopeField(manualTaskType, 'publish_time_range', capabilities)" label="视频发布时间">
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

        <el-form-item v-if="hasScopeField(manualTaskType, 'comment_days', capabilities)" label="采集几天内评论">
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
import { setPlatformId } from "../api/http";
import {
  buildManualTaskPayload,
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
import {
  FALLBACK_COMMENT_DAYS_OPTIONS,
  FALLBACK_PUBLISH_TIME_OPTIONS,
  applyDefaultCommentDays,
  browserModeToHeadless,
  buildEvaluationPayload,
  getFieldOptions,
  hasScopeField,
  listManualModeOptions,
  listSupportedPlatforms,
  platformLabel,
  validateRequiredScopeFields,
} from "../utils/huokeTaskForm";
import { buildManualPreflightPayload } from "../utils/huokeTaskPreflight";
import { isStandaloneDouyinStrategy } from "../utils/acquisitionStrategy";
import { deriveManualTaskName, detectManualUrlIntent, manualUrlIntentHint, normalizeManualInputUrl, validateManualTaskUrl } from "../utils/manualTaskForm";
import { validateTaskPresetSelection } from "../utils/presetSelection";

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
const commentPresets = ref([]);
const dmPresets = ref([]);
const selectedCommentPresetIds = ref([]);
const selectedDmPresetIds = ref([]);
const settings = ref({ ...DEFAULT_INTERACTION_SETTINGS });

const form = reactive({
  intent: "account_home",
  platform: "douyin",
  agentStrategy: "",
  browserMode: "headed",
  inputUrl: "",
  crawlVideoLimit: 10,
  targetCount: 5,
  publishTimeRange: "unlimited",
  commentDays: 3,
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
const manualModeOptions = computed(() => listManualModeOptions(capabilities.value));
const selectedMode = computed(() => manualModeOptions.value.find((row) => row.value === form.intent));
const manualTaskType = computed(() => (form.intent === "account_home" ? "home_manual" : "video_manual"));
const publishOptions = computed(() =>
  getFieldOptions(capabilities.value, "publish_time_range", FALLBACK_PUBLISH_TIME_OPTIONS),
);
const commentOptions = computed(() =>
  getFieldOptions(capabilities.value, "comment_days", FALLBACK_COMMENT_DAYS_OPTIONS),
);
const evaluationTemplates = computed(() => capabilities.value?.evaluation_templates || []);
const urlError = computed(() => validateManualTaskUrl(form.inputUrl, form.intent, form.platform));
const urlHint = computed(() => manualUrlIntentHint(form.inputUrl, form.intent, form.platform));
const effectiveIntent = computed(
  () => detectManualUrlIntent(form.inputUrl, form.platform) || form.intent,
);
const urlLabel = computed(() => (effectiveIntent.value === "single_video" ? "视频链接" : "主页链接"));
const urlPlaceholder = computed(() =>
  effectiveIntent.value === "account_home"
    ? "粘贴博主账号主页链接（支持 v.douyin.com 短链），系统将从主页获取视频列表并抓取评论"
    : "粘贴单条视频详情页链接",
);
const isStandalone = computed(() => isStandaloneDouyinStrategy(form.agentStrategy));
const showManualTargetCount = computed(() => isStandalone.value);

const canSubmit = computed(() => {
  if (submitting.value || preflightLoading.value) return false;
  if (!preflight.value?.ready) return false;
  if (preflight.value.warning_count > 0 && !preflightAcknowledged.value) return false;
  return true;
});

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
    form.commentDays = Number(applyDefaultCommentDays(manualTaskType.value, capabilities.value)) || 3;
  } catch {
    capabilities.value = null;
  }
  await reloadPresets();
}

async function reloadPresets() {
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
  () => [form.inputUrl, form.platform],
  () => {
    if (!visible.value) return;
    const detected = detectManualUrlIntent(form.inputUrl, form.platform);
    if (detected) form.intent = detected;
  },
);

watch(
  () => form.platform,
  async () => {
    if (!visible.value) return;
    syncRequestContext();
    try {
      capabilities.value = await fetchExternalCapabilities(form.platform);
      form.commentDays = Number(applyDefaultCommentDays(manualTaskType.value, capabilities.value)) || 3;
    } catch {
      capabilities.value = null;
    }
    await reloadPresets();
  },
);

watch(
  () => form.intent,
  () => {
    if (!visible.value) return;
    form.commentDays = Number(applyDefaultCommentDays(manualTaskType.value, capabilities.value)) || 3;
  },
);

watch(
  () => [
    form.platform,
    form.intent,
    form.inputUrl,
    form.crawlVideoLimit,
    form.commentDays,
    form.publishTimeRange,
    form.browserMode,
    form.agentStrategy,
    form.targetCount,
    form.evalTemplateId,
    form.targetCustomer,
    form.acceptDescription,
    form.rejectSignals,
    settings.value,
    selectedCommentPresetIds.value,
    selectedDmPresetIds.value,
  ],
  () => {
    if (!visible.value) return;
    if (urlError.value || !form.inputUrl.trim()) {
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
        const intent = effectiveIntent.value;
        const inputUrl = normalizeManualInputUrl(form.inputUrl.trim(), intent, form.platform);
        const payload = buildManualPreflightPayload({
          intent,
          name: deriveManualTaskName(inputUrl, intent),
          platform: form.platform,
          inputUrl,
          commentDays: String(form.commentDays),
          publishTime: form.publishTimeRange,
          crawlVideoLimit: intent === "account_home" ? form.crawlVideoLimit : undefined,
          headless: browserModeToHeadless(form.browserMode),
          settings: settings.value,
          commentPresetIds: selectedCommentPresetIds.value,
          dmPresetIds: selectedDmPresetIds.value,
          evaluation: evaluationPayload(),
          agentStrategy: form.agentStrategy,
          targetCount: form.targetCount,
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
  form.intent = "account_home";
  form.platform = "douyin";
  form.agentStrategy = "";
  form.browserMode = "headed";
  form.inputUrl = "";
  form.crawlVideoLimit = 10;
  form.targetCount = 5;
  form.publishTimeRange = "unlimited";
  form.commentDays = 3;
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
  if (urlError.value) {
    ElMessage.warning(urlError.value);
    return;
  }
  const taskName = deriveManualTaskName(form.inputUrl, effectiveIntent.value);
  const validationError = validateRequiredScopeFields(
    effectiveIntent.value === "account_home" ? "home_manual" : "video_manual",
    {
      input_url: form.inputUrl.trim(),
      comment_days: form.commentDays,
      publish_time_range: form.publishTimeRange,
    },
    capabilities.value,
  );
  if (validationError) {
    ElMessage.warning(validationError);
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
    await putInteractionSettings(settings.value).catch(() => {});
    const intent = effectiveIntent.value;
    const inputUrl = normalizeManualInputUrl(form.inputUrl.trim(), intent, form.platform);
    const payload = buildManualTaskPayload({
      intent,
      name: taskName,
      platform: form.platform,
      inputUrl,
      commentDays: form.commentDays,
      publishTimeRange: form.publishTimeRange,
      crawlVideoLimit: intent === "account_home" ? form.crawlVideoLimit : undefined,
      headless: browserModeToHeadless(form.browserMode),
      settings: settings.value,
      commentPresetIds: selectedCommentPresetIds.value,
      dmPresetIds: selectedDmPresetIds.value,
      commentPresets: commentPresets.value,
      dmPresets: dmPresets.value,
      evaluation: evaluationPayload(),
      agentStrategy: form.agentStrategy,
      targetCount: form.targetCount,
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

.field-hint {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.field-hint.error {
  color: var(--el-color-danger);
}
</style>
