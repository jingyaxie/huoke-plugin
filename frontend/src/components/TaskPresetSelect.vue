<template>
  <el-form-item :label="label">
    <el-alert
      v-if="!options.length"
      type="warning"
      :closable="false"
      :title="emptyHint"
      show-icon
    />
    <div v-else class="preset-select">
      <label
        v-for="item in options"
        :key="item.id"
        class="preset-option"
        :class="{ active: selectedIds.includes(item.id), disabled }"
      >
        <el-checkbox
          :model-value="selectedIds.includes(item.id)"
          :disabled="disabled"
          @change="() => toggle(item.id)"
        />
        <span class="preset-text">
          <span class="preset-name">{{ item.name }}</span>
          <span class="preset-content">{{ item.content }}</span>
        </span>
      </label>
      <p class="preset-hint">可多选，任务执行时将从已选模板中随机抽取</p>
    </div>
  </el-form-item>
</template>

<script setup>
const props = defineProps({
  label: { type: String, required: true },
  options: { type: Array, default: () => [] },
  selectedIds: { type: Array, default: () => [] },
  emptyHint: {
    type: String,
    default: "暂无可用模板，请先在「评论/私信预设」页添加",
  },
  disabled: { type: Boolean, default: false },
});

const emit = defineEmits(["update:selectedIds"]);

function toggle(id) {
  if (props.disabled) return;
  const next = props.selectedIds.includes(id)
    ? props.selectedIds.filter((item) => item !== id)
    : [...props.selectedIds, id];
  emit("update:selectedIds", next);
}
</script>

<style scoped>
.preset-select {
  width: 100%;
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
  background: #fff;
  max-height: 160px;
  overflow-y: auto;
  padding: 6px;
}

.preset-option {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 6px;
  cursor: pointer;
}

.preset-option.active {
  background: var(--el-color-primary-light-9);
}

.preset-option.disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.preset-text {
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.preset-name {
  font-size: 14px;
  font-weight: 500;
}

.preset-content {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.preset-hint {
  margin: 6px 8px 2px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
</style>
