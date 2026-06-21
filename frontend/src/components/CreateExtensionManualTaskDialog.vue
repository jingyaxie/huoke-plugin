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
              v-for="item in platformOptions"
              :key="item.id"
              :value="item.id"
              :disabled="!item.collect"
            >
              {{ item.label }}
            </el-radio-button>
          </el-radio-group>
          <p v-if="platformHint" class="field-hint">{{ platformHint }}</p>
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

        <el-form-item :label="urlLabel" required>
          <el-input v-model="form.inputUrl" :placeholder="urlPlaceholder" />
          <p v-if="urlHint" class="field-hint">{{ urlHint }}</p>
          <p v-if="urlError" class="field-hint error">{{ urlError }}</p>
        </el-form-item>

        <el-form-item v-if="effectiveIntent === 'account_home'" label="扫描视频数">
          <el-input-number v-model="form.crawlVideoLimit" :min="1" :max="20" />
          <p class="field-hint">主页模式下每轮最多打开多少个作品抓评论（插件模式上限 20）。</p>
        </el-form-item>

        <el-form-item label="视频发布时间">
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

        <el-form-item label="采集几天内评论">
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

        <el-row :gutter="16">
          <el-col :span="12">
            <TaskPresetSelect
              label="评论模板"
              :options="commentPresets"
              :selected-ids="selectedCommentPresetIds"
              @update:selected-ids="selectedCommentPresetIds = $event"
            />
          </el-col>
          <el-col :span="12">
            <TaskPresetSelect
              label="私信模板"
              :options="dmPresets"
              :selected-ids="selectedDmPresetIds"
              @update:selected-ids="selectedDmPresetIds = $event"
            />
          </el-col>
        </el-row>

        <TaskInteractionFields v-model="settings" />

        <el-form-item label="创建后执行">
          <el-switch
            v-model="form.autoStart"
            active-text="立即开始采集"
            inactive-text="仅创建，稍后手动启动"
            @change="onAutoStartChange"
          />
          <p v-if="form.autoStart" class="field-hint">
            需 Chrome 插件已连接（角标 OK），并保持抖音页已登录。
          </p>
        </el-form-item>
      </el-form>
    </div>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="submit">
        {{ submitting ? "创建中…" : "创建任务" }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import TaskInteractionFields from "./TaskInteractionFields.vue";
import TaskPresetSelect from "./TaskPresetSelect.vue";
import { createCollectJob, fetchCollectCapabilities } from "../api/localService";
import { mergeExtensionCapabilities, isExtensionCollectPlatform } from "../config/extensionPlatformCapabilities";
import { DEFAULT_INTERACTION_SETTINGS, listPlatformPresets } from "../api/presets";
import {
  FALLBACK_COMMENT_DAYS_OPTIONS,
  FALLBACK_PUBLISH_TIME_OPTIONS,
  computeAutoOutreach,
  listManualModeOptions,
  loadExtensionAutoStartPref,
  saveExtensionAutoStartPref,
} from "../utils/huokeTaskForm";
import {
  deriveManualTaskName,
  detectManualUrlIntent,
  manualUrlIntentHint,
  validateManualTaskUrl,
} from "../utils/manualTaskForm";
import { validateTaskPresetSelection } from "../utils/presetSelection";
import { listLocalPresets } from "../utils/localPresets";

const props = defineProps({
  modelValue: { type: Boolean, default: false },
});

const emit = defineEmits(["update:modelValue", "created"]);

const visible = ref(false);
const submitting = ref(false);
const commentPresets = ref([]);
const dmPresets = ref([]);
const selectedCommentPresetIds = ref([]);
const selectedDmPresetIds = ref([]);
const settings = ref({ ...DEFAULT_INTERACTION_SETTINGS });
const platformOptions = ref(mergeExtensionCapabilities());

const form = reactive({
  intent: "account_home",
  platform: "douyin",
  inputUrl: "",
  crawlVideoLimit: 10,
  publishTimeRange: "unlimited",
  commentDays: 3,
  autoStart: loadExtensionAutoStartPref(true),
});

const manualModeOptions = listManualModeOptions(null);
const selectedMode = computed(() => manualModeOptions.find((row) => row.value === form.intent));
const publishOptions = FALLBACK_PUBLISH_TIME_OPTIONS;
const commentOptions = FALLBACK_COMMENT_DAYS_OPTIONS;
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
const platformHint = computed(() => {
  const disabled = platformOptions.value.filter((row) => !row.collect).map((row) => row.label);
  const enabled = platformOptions.value.filter((row) => row.collect).map((row) => row.label);
  if (disabled.length === 0 || enabled.length === 0) return "";
  return `${disabled.join(" / ")} 插件采集适配中，当前仅 ${enabled.join(" / ")} 可创建任务。`;
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

watch(
  () => [form.inputUrl, form.platform],
  () => {
    if (!visible.value) return;
    const detected = detectManualUrlIntent(form.inputUrl, form.platform);
    if (detected) form.intent = detected;
  },
);

async function loadDialogData() {
  settings.value = { ...DEFAULT_INTERACTION_SETTINGS };
  form.autoStart = loadExtensionAutoStartPref(true);
  try {
    const remote = await fetchCollectCapabilities();
    platformOptions.value = mergeExtensionCapabilities(remote?.platforms);
  } catch {
    platformOptions.value = mergeExtensionCapabilities();
  }
  await reloadPresets();
}

function onAutoStartChange(value) {
  saveExtensionAutoStartPref(Boolean(value));
}

async function reloadPresets() {
  try {
    const presets = await listPlatformPresets();
    commentPresets.value = presets.comments;
    dmPresets.value = presets.dmOpeners;
  } catch {
    commentPresets.value = listLocalPresets("comments").items || [];
    dmPresets.value = listLocalPresets("dm-openers").items || [];
  }
  selectedCommentPresetIds.value = commentPresets.value.map((row) => row.id);
  selectedDmPresetIds.value = dmPresets.value.map((row) => row.id);
}

function resetForm() {
  form.intent = "account_home";
  form.platform = "douyin";
  form.inputUrl = "";
  form.crawlVideoLimit = 10;
  form.publishTimeRange = "unlimited";
  form.commentDays = 3;
  form.autoStart = loadExtensionAutoStartPref(true);
}

async function submit() {
  if (!isExtensionCollectPlatform(form.platform)) {
    ElMessage.warning("该平台插件采集尚未开放");
    return;
  }
  if (urlError.value) {
    ElMessage.warning(urlError.value);
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

  const intent = effectiveIntent.value;
  const inputUrl = form.inputUrl.trim();
  const taskName = deriveManualTaskName(inputUrl, intent);
  const limitVideos = Math.min(20, Math.max(1, form.crawlVideoLimit));
  const maxCommentsPerVideo = intent === "single_video" ? 200 : 80;

  submitting.value = true;
  try {
    const commentPresetPayload = selectedCommentPresetIds.value
      .map((id) => {
        const row = commentPresets.value.find((item) => item.id === id);
        return { id, content: row?.content || "" };
      })
      .filter((row) => row.content);
    const dmPresetPayload = selectedDmPresetIds.value
      .map((id) => {
        const row = dmPresets.value.find((item) => item.id === id);
        return { id, content: row?.content || "" };
      })
      .filter((row) => row.content);

    const result = await createCollectJob({
      job_type: "manual",
      intent,
      name: taskName,
      platform: form.platform,
      input_url: inputUrl,
      limit_videos: limitVideos,
      max_comments_per_video: maxCommentsPerVideo,
      target_count: limitVideos * maxCommentsPerVideo,
      publish_time_range: form.publishTimeRange,
      comment_days: form.commentDays,
      interaction: settings.value,
      comment_presets: commentPresetPayload,
      dm_presets: dmPresetPayload,
      auto_outreach: computeAutoOutreach({
        commentPresetPayload,
        dmPresetPayload,
        followPerDay: settings.value.follow_per_day,
        dmPerDay: settings.value.dm_per_day,
      }),
      auto_start: form.autoStart,
    });
    ElMessage.success(
      result?.started ? "任务已创建并开始采集" : "任务已创建，请在列表中点击「开始采集」",
    );
    visible.value = false;
    emit("created");
  } catch (err) {
    ElMessage.error(err?.response?.data?.error || err?.message || "创建失败");
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
