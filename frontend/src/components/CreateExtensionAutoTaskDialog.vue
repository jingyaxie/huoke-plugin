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

        <el-form-item label="产品关键词" required>
          <el-input v-model="form.keywords" placeholder="输入产品或服务关键词，例如：团餐配送" />
          <p v-if="composedSearchKeyword" class="field-hint">
            实际搜索词：<strong>{{ composedSearchKeyword }}</strong>
            <span v-if="regionName">（{{ regionName }} + 关键词）</span>
          </p>
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

        <el-form-item label="单批扫描视频上限" required>
          <el-input-number v-model="form.crawlVideoLimit" :min="1" :max="20" />
          <p class="field-hint">每轮最多扫描多少个视频采集评论；扫满上限或搜索结果不足时即视为完成。</p>
        </el-form-item>

        <TaskPresetSelect
          label="私信模板"
          :options="dmPresets"
          :selected-ids="selectedDmPresetIds"
          @update:selected-ids="selectedDmPresetIds = $event"
        />

        <TaskInteractionFields v-model="settings" />

        <TaskEvaluationSection
          v-model:eval-template-id="form.evalTemplateId"
          v-model:target-customer="form.targetCustomer"
          v-model:accept-description="form.acceptDescription"
          v-model:reject-signals="form.rejectSignals"
          v-model:expanded="form.evaluationExpanded"
        />

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
import TaskEvaluationSection from "./TaskEvaluationSection.vue";
import { createCollectJob, fetchCollectCapabilities } from "../api/localService";
import { registerCollectJobToCloud } from "../cloud-sync";
import { mergeExtensionCapabilities, isExtensionCollectPlatform } from "../config/extensionPlatformCapabilities";
import { DEFAULT_INTERACTION_SETTINGS, listPlatformPresets } from "../api/presets";
import {
  REGION_PRESETS,
  FALLBACK_COMMENT_DAYS_OPTIONS,
  computeAutoOutreach,
  buildEvaluationPayload,
  defaultEvaluation,
  composeSearchKeyword,
  loadExtensionAutoStartPref,
  saveExtensionAutoStartPref,
} from "../utils/huokeTaskForm";
import { validateTaskPresetSelection } from "../utils/presetSelection";
import { listLocalPresets } from "../utils/localPresets";

const props = defineProps({
  modelValue: { type: Boolean, default: false },
});

const emit = defineEmits(["update:modelValue", "created"]);

const visible = ref(false);
const submitting = ref(false);
const dmPresets = ref([]);
const selectedDmPresetIds = ref([]);
const settings = ref({ ...DEFAULT_INTERACTION_SETTINGS });
const platformOptions = ref(mergeExtensionCapabilities());

const form = reactive({
  name: "",
  regionCode: "",
  platform: "douyin",
  keywords: "",
  commentDays: 3,
  crawlVideoLimit: 10,
  autoStart: loadExtensionAutoStartPref(true),
  evalTemplateId: "",
  targetCustomer: "",
  acceptDescription: "",
  rejectSignals: "",
  evaluationExpanded: false,
});

const commentOptions = FALLBACK_COMMENT_DAYS_OPTIONS;

const regionName = computed(
  () => REGION_PRESETS.find((row) => row.code === form.regionCode)?.name || "",
);
const composedSearchKeyword = computed(() => {
  const keyword = keywordList()[0] || "";
  if (!keyword) return "";
  return composeSearchKeyword(keyword, regionName.value);
});
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

function keywordList() {
  return form.keywords
    .split(/[,，\s]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function evaluationPayload() {
  const custom = buildEvaluationPayload({
    evalTemplateId: form.evalTemplateId,
    targetCustomer: form.targetCustomer,
    acceptDescription: form.acceptDescription,
    rejectSignals: form.rejectSignals,
  });
  return defaultEvaluation(keywordList()[0] || form.name, custom);
}

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
    dmPresets.value = presets.dmOpeners;
  } catch {
    dmPresets.value = listLocalPresets("dm-openers").items || [];
  }
  selectedDmPresetIds.value = dmPresets.value.map((row) => row.id);
}

function resetForm() {
  form.name = "";
  form.regionCode = "";
  form.platform = "douyin";
  form.keywords = "";
  form.commentDays = 3;
  form.crawlVideoLimit = 10;
  form.autoStart = loadExtensionAutoStartPref(true);
  form.evalTemplateId = "";
  form.targetCustomer = "";
  form.acceptDescription = "";
  form.rejectSignals = "";
  form.evaluationExpanded = false;
}

async function submit() {
  if (!isExtensionCollectPlatform(form.platform)) {
    ElMessage.warning("该平台插件采集尚未开放");
    return;
  }
  const keywords = keywordList();
  if (!form.name.trim()) {
    ElMessage.warning("请填写任务名称");
    return;
  }
  if (!keywords.length) {
    ElMessage.warning("请填写产品关键词");
    return;
  }
  if (!form.crawlVideoLimit || form.crawlVideoLimit < 1) {
    ElMessage.warning("单批扫描视频上限必须大于 0");
    return;
  }
  const presetError = validateTaskPresetSelection(
    { ...settings.value, comment_dm_percentage: 0 },
    [],
    selectedDmPresetIds.value,
  );
  if (presetError) {
    ElMessage.warning(presetError);
    return;
  }

  const limitVideos = Math.min(20, Math.max(1, form.crawlVideoLimit));

  submitting.value = true;
  try {
    const dmPresetPayload = selectedDmPresetIds.value
      .map((id) => {
        const row = dmPresets.value.find((item) => item.id === id);
        return { id, content: row?.content || "" };
      })
      .filter((row) => row.content);

    const result = await createCollectJob({
      job_type: "keyword",
      name: form.name.trim(),
      platform: form.platform,
      keyword: keywords[0],
      limit_videos: limitVideos,
      max_comments_per_video: 50,
      region_code: form.regionCode || undefined,
      region_name: regionName.value || undefined,
      comment_days: form.commentDays,
      interaction: { ...settings.value, comment_dm_percentage: 0 },
      comment_presets: [],
      dm_presets: dmPresetPayload,
      auto_outreach: computeAutoOutreach({
        commentPresetPayload: [],
        dmPresetPayload,
        followPerDay: settings.value.follow_per_day,
        dmPerDay: settings.value.dm_per_day,
      }),
      evaluation: evaluationPayload(),
      auto_start: form.autoStart,
    });
    const cloudLink = await registerCollectJobToCloud({
      localJob: result?.job,
      jobType: "keyword",
      keyword: keywords[0],
      regionCode: form.regionCode || undefined,
      regionName: regionName.value || undefined,
      commentDays: form.commentDays,
      publishTimeRange: "unlimited",
      targetCount: limitVideos,
      evaluation: evaluationPayload(),
      interaction: { ...settings.value, comment_dm_percentage: 0 },
      commentPresets: [],
      dmPresets: dmPresetPayload,
    });
    ElMessage.success(
      result?.started
        ? cloudLink.linked
          ? "任务已创建并开始采集，已同步到云端"
          : "任务已创建并开始采集"
        : cloudLink.linked
          ? "任务已创建并同步到云端，请在列表中点击「开始采集」"
          : "任务已创建，请在列表中点击「开始采集」",
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

.dialog-body {
  padding-right: 4px;
}

.field-hint {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
</style>
