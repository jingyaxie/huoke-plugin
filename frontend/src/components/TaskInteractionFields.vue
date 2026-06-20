<template>
  <div class="interaction-fields">
    <div class="section-title">互动设置</div>
    <div class="interaction-grid">
      <div class="field-block field-block--wide">
        <label class="field-label">评论/私信随机间隔</label>
        <div class="control-row interval-row">
          <el-input-number
            :model-value="modelValue.comment_dm_interval_seconds_min"
            :min="1"
            :max="600"
            controls-position="right"
            @update:model-value="patch({ comment_dm_interval_seconds_min: $event })"
          />
          <span class="sep">至</span>
          <el-input-number
            :model-value="modelValue.comment_dm_interval_seconds_max"
            :min="1"
            :max="600"
            controls-position="right"
            @update:model-value="patch({ comment_dm_interval_seconds_max: $event })"
          />
          <span class="unit">秒</span>
        </div>
      </div>

      <div class="field-block">
        <label class="field-label">评论/私信百分比</label>
        <div class="control-row">
          <el-input-number
            :model-value="modelValue.comment_dm_percentage"
            :min="0"
            :max="100"
            controls-position="right"
            @update:model-value="patch({ comment_dm_percentage: $event })"
          />
          <span class="unit">%</span>
        </div>
      </div>

      <div class="field-block">
        <label class="field-label">每日关注上限</label>
        <div class="control-row">
          <el-input-number
            :model-value="modelValue.follow_per_day"
            :min="0"
            :max="1000"
            controls-position="right"
            @update:model-value="patch({ follow_per_day: $event })"
          />
        </div>
      </div>

      <div class="field-block">
        <label class="field-label">每日私信上限</label>
        <div class="control-row">
          <el-input-number
            :model-value="modelValue.dm_per_day"
            :min="0"
            :max="1000"
            controls-position="right"
            @update:model-value="patch({ dm_per_day: $event })"
          />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
const props = defineProps({
  modelValue: {
    type: Object,
    default: () => ({
      comment_dm_interval_seconds_min: 10,
      comment_dm_interval_seconds_max: 30,
      comment_dm_percentage: 50,
      follow_per_day: 30,
      dm_per_day: 30,
      batch_cooldown_minutes: 8,
    }),
  },
});

const emit = defineEmits(["update:modelValue"]);

function patch(partial) {
  emit("update:modelValue", { ...props.modelValue, ...partial });
}
</script>

<style scoped>
.interaction-fields {
  margin-top: 4px;
  padding-top: 12px;
  border-top: 1px solid var(--el-border-color-lighter);
}

.section-title {
  margin-bottom: 14px;
  font-size: 14px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.interaction-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px 24px;
}

.field-block {
  min-width: 0;
}

.field-block--wide {
  grid-column: 1 / -1;
}

.field-label {
  display: block;
  margin-bottom: 8px;
  font-size: 13px;
  line-height: 1.4;
  color: var(--el-text-color-regular);
  white-space: nowrap;
}

.control-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.interval-row :deep(.el-input-number) {
  width: 120px;
}

.control-row :deep(.el-input-number) {
  width: 140px;
}

.sep {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  flex-shrink: 0;
}

.unit {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  flex-shrink: 0;
}

@media (max-width: 640px) {
  .interaction-grid {
    grid-template-columns: 1fr;
  }

  .field-block--wide {
    grid-column: auto;
  }
}
</style>
