<template>
  <div class="filters-bar">
    <el-input
      v-model="local.keyword"
      placeholder="搜索任务名称 / 产品关键词 / 账号"
      clearable
      class="filter-keyword"
      @keyup.enter="submit"
      @clear="submit"
    />
    <el-select v-model="local.platform" placeholder="全部平台" style="width: 140px" @change="submit">
      <el-option
        v-for="item in platformOptions"
        :key="item.value || 'all'"
        :label="item.label"
        :value="item.value"
      />
    </el-select>
    <el-select v-model="local.status" placeholder="全部状态" style="width: 140px" @change="submit">
      <el-option
        v-for="item in statusOptions"
        :key="item.value || 'all-status'"
        :label="item.label"
        :value="item.value"
      />
    </el-select>
    <el-date-picker
      v-model="local.dateRange"
      type="daterange"
      range-separator="至"
      start-placeholder="开始日期"
      end-placeholder="结束日期"
      placeholder="创建时间"
      value-format="YYYY-MM-DD"
      class="filter-date"
      @change="submit"
    />
    <el-button link type="primary" class="reset-btn" @click="reset">重置</el-button>
  </div>
</template>

<script setup>
import { reactive, watch } from "vue";
import {
  ACQUISITION_PLATFORM_OPTIONS,
  ACQUISITION_STATUS_OPTIONS,
  DEFAULT_ACQUISITION_FILTER,
} from "../utils/acquisitionJobs";

const props = defineProps({
  modelValue: {
    type: Object,
    default: () => ({ ...DEFAULT_ACQUISITION_FILTER }),
  },
});

const emit = defineEmits(["update:modelValue", "submit"]);

const platformOptions = ACQUISITION_PLATFORM_OPTIONS;
const statusOptions = ACQUISITION_STATUS_OPTIONS;
const local = reactive({ ...DEFAULT_ACQUISITION_FILTER });

watch(
  () => props.modelValue,
  (value) => {
    Object.assign(local, DEFAULT_ACQUISITION_FILTER, value || {});
  },
  { immediate: true, deep: true },
);

function submit() {
  const next = { ...local };
  emit("update:modelValue", next);
  emit("submit", next);
}

function reset() {
  Object.assign(local, DEFAULT_ACQUISITION_FILTER);
  submit();
}
</script>

<style scoped>
.filters-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  padding: 12px 16px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}

.filter-keyword {
  flex: 1 1 280px;
  min-width: 220px;
}

.filter-date {
  width: 260px;
}

.reset-btn {
  margin-left: auto;
}
</style>
