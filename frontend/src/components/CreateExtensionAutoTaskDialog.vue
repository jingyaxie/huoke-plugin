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
            <el-radio-button value="douyin">抖音</el-radio-button>
            <el-radio-button value="xiaohongshu" disabled>小红书</el-radio-button>
            <el-radio-button value="kuaishou" disabled>快手</el-radio-button>
          </el-radio-group>
          <p class="field-hint">小红书 / 快手采集能力开放中，当前仅抖音可创建任务。</p>
        </el-form-item>

        <el-form-item label="产品关键词" required>
          <el-input v-model="form.keywords" placeholder="输入产品或服务关键词，例如：团餐配送" />
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

        <el-form-item label="预设抓取数量" required>
          <el-input-number v-model="form.targetCount" :min="1" :max="500" />
          <p class="field-hint">建议单次控制在 30–100 条；采集完成后可在任务详情查看评论线索。</p>
        </el-form-item>

        <el-form-item label="单批扫描视频上限">
          <el-input-number v-model="form.crawlVideoLimit" :min="1" :max="20" />
          <p class="field-hint">每轮最多打开多少个视频采集评论（插件模式上限 20）。</p>
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
import { createCollectJob } from "../api/localService";
import { DEFAULT_INTERACTION_SETTINGS, listPlatformPresets } from "../api/presets";
import {
  REGION_PRESETS,
  FALLBACK_COMMENT_DAYS_OPTIONS,
  FALLBACK_PUBLISH_TIME_OPTIONS,
} from "../utils/huokeTaskForm";
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

const form = reactive({
  name: "",
  regionCode: "",
  platform: "douyin",
  keywords: "",
  publishTimeRange: "unlimited",
  commentDays: 3,
  targetCount: 50,
  crawlVideoLimit: 10,
});

const publishOptions = FALLBACK_PUBLISH_TIME_OPTIONS;
const commentOptions = FALLBACK_COMMENT_DAYS_OPTIONS;

const regionName = computed(
  () => REGION_PRESETS.find((row) => row.code === form.regionCode)?.name || "",
);

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

async function loadDialogData() {
  settings.value = { ...DEFAULT_INTERACTION_SETTINGS };
  await reloadPresets();
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
  form.name = "";
  form.regionCode = "";
  form.platform = "douyin";
  form.keywords = "";
  form.publishTimeRange = "unlimited";
  form.commentDays = 3;
  form.targetCount = 50;
  form.crawlVideoLimit = 10;
}

async function submit() {
  const keywords = keywordList();
  if (!form.name.trim()) {
    ElMessage.warning("请填写任务名称");
    return;
  }
  if (!keywords.length) {
    ElMessage.warning("请填写产品关键词");
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

  const limitVideos = Math.min(20, Math.max(1, form.crawlVideoLimit));
  const maxCommentsPerVideo = Math.min(
    500,
    Math.max(1, Math.ceil(form.targetCount / limitVideos)),
  );

  submitting.value = true;
  try {
    await createCollectJob({
      job_type: "keyword",
      name: form.name.trim(),
      platform: form.platform,
      keyword: keywords[0],
      limit_videos: limitVideos,
      max_comments_per_video: maxCommentsPerVideo,
      target_count: form.targetCount,
      region_code: form.regionCode || undefined,
      region_name: regionName.value || undefined,
      publish_time_range: form.publishTimeRange,
      comment_days: form.commentDays,
      interaction: settings.value,
      comment_preset_ids: selectedCommentPresetIds.value,
      dm_preset_ids: selectedDmPresetIds.value,
    });
    ElMessage.success("任务已创建");
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
