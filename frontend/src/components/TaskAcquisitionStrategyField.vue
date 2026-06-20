<template>
  <el-form-item label="执行策略">
    <el-select
      :model-value="modelValue"
      :loading="loading"
      placeholder="选择获客执行方式"
      style="width: 100%"
      @update:model-value="emit('update:modelValue', $event)"
    >
      <el-option
        v-for="item in options"
        :key="item.id"
        :label="strategyLabel(item)"
        :value="item.id"
      />
    </el-select>
    <p v-if="selected?.description" class="field-hint">{{ selected.description }}</p>
    <p v-else-if="isStandalone" class="field-hint">
      一体化浏览：搜索/主页/单视频 → 点进详情 → 侧栏规则评估 → 同页触达（无需分步入库再重开页）。
    </p>
    <p v-else-if="platform === 'douyin'" class="field-hint">
      类人分步：先抓取评论入库 → LLM 评估 → 再按配额分步触达（稳定默认链路）。
    </p>
  </el-form-item>
</template>

<script setup>
import { computed, ref, watch } from "vue";
import { fetchAgentStrategies } from "../api/agent";
import {
  defaultAgentStrategyForPlatform,
  isStandaloneDouyinStrategy,
  strategyAvailableForPlatform,
} from "../utils/acquisitionStrategy";

const props = defineProps({
  modelValue: { type: String, default: "" },
  platform: { type: String, default: "douyin" },
});

const emit = defineEmits(["update:modelValue"]);

const loading = ref(false);
const options = ref([]);

const selected = computed(() => options.value.find((row) => row.id === props.modelValue));
const isStandalone = computed(() => isStandaloneDouyinStrategy(props.modelValue));

function strategyLabel(item) {
  if (!item) return "";
  return item.is_default ? `${item.label}（默认）` : item.label;
}

async function loadOptions() {
  loading.value = true;
  try {
    const list = await fetchAgentStrategies(props.platform);
    options.value = Array.isArray(list) ? list : [];
  } catch {
    options.value = [];
  } finally {
    loading.value = false;
  }
  ensureValidSelection();
}

function ensureValidSelection() {
  const current = String(props.modelValue || "").trim();
  if (current && strategyAvailableForPlatform(props.platform, current)) {
    return;
  }
  const fallback =
    options.value.find((row) => row.is_default)?.id ||
    options.value[0]?.id ||
    defaultAgentStrategyForPlatform(props.platform);
  if (fallback && fallback !== props.modelValue) {
    emit("update:modelValue", fallback);
  }
}

watch(
  () => props.platform,
  () => {
    void loadOptions();
  },
  { immediate: true },
);
</script>

<style scoped>
.field-hint {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
}
</style>
