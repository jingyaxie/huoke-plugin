<template>
  <div class="readiness-panel">
    <div class="readiness-header">
      <div>
        <div class="readiness-title">执行就绪检查</div>
        <div class="readiness-subtitle">创建前确认编排、登录态、大模型与线索评估是否可用</div>
      </div>
      <span v-if="loading" class="readiness-loading">检查中…</span>
    </div>

    <el-alert
      :type="summaryType"
      :closable="false"
      :title="loading ? '正在检查任务是否可执行…' : summaryText"
      show-icon
      class="readiness-summary"
    />

    <el-alert
      v-if="error"
      type="error"
      :closable="false"
      :title="`预检请求失败：${error}`"
      show-icon
      class="readiness-error"
    />

    <ul v-if="result?.checks?.length" class="readiness-checks">
      <li
        v-for="item in result.checks"
        :key="item.id"
        class="readiness-check"
        :class="`status-${item.status}`"
      >
        <span class="check-icon">{{ statusIcon(item.status) }}</span>
        <div>
          <div class="check-label">{{ item.label }}</div>
          <div class="check-message">{{ item.message }}</div>
        </div>
      </li>
    </ul>

    <el-collapse v-if="result?.orchestration?.steps?.length" class="readiness-orchestration">
      <el-collapse-item
        :title="`编排预览（${result.orchestration.steps.length} 步）`"
        name="orchestration"
      >
        <p v-if="result.orchestration.summary" class="orchestration-summary">
          {{ result.orchestration.summary }}
        </p>
        <ol class="orchestration-steps">
          <li v-for="(step, idx) in result.orchestration.steps" :key="`${step.action || 'step'}-${idx}`">
            {{ step.label || step.action }}
          </li>
        </ol>
      </el-collapse-item>
    </el-collapse>

    <p v-if="result?.evaluation?.accept_preview" class="evaluation-preview">
      评估规则预览：{{ result.evaluation.accept_preview
      }}{{ result.evaluation.accept_preview.length >= 160 ? "…" : "" }}
    </p>

    <el-checkbox
      v-if="result?.ready && result.warning_count > 0"
      :model-value="acknowledged"
      class="readiness-ack"
      @update:model-value="$emit('update:acknowledged', $event)"
    >
      我已了解上述提醒，仍要创建任务
    </el-checkbox>
  </div>
</template>

<script setup>
import { computed } from "vue";
import { preflightSummary } from "../utils/huokeTaskPreflight";

const props = defineProps({
  loading: { type: Boolean, default: false },
  error: { type: String, default: "" },
  result: { type: Object, default: null },
  acknowledged: { type: Boolean, default: false },
});

defineEmits(["update:acknowledged"]);

const summaryText = computed(() => preflightSummary(props.result));

const summaryType = computed(() => {
  if (props.loading) return "info";
  if (!props.result) return "info";
  if (!props.result.ready) return "error";
  if (props.result.warning_count > 0) return "warning";
  return "success";
});

function statusIcon(status) {
  if (status === "ok") return "✓";
  if (status === "warning") return "!";
  return "×";
}
</script>

<style scoped>
.readiness-panel {
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
  background: var(--el-fill-color-light);
  padding: 12px;
}

.readiness-header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}

.readiness-title {
  font-size: 14px;
  font-weight: 600;
}

.readiness-subtitle {
  margin-top: 2px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.readiness-loading {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.readiness-summary,
.readiness-error {
  margin-bottom: 8px;
}

.readiness-checks {
  list-style: none;
  margin: 8px 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.readiness-check {
  display: flex;
  gap: 8px;
  border-radius: 6px;
  border: 1px solid var(--el-border-color);
  padding: 8px 10px;
  font-size: 12px;
}

.readiness-check.status-ok {
  background: var(--el-color-success-light-9);
  border-color: var(--el-color-success-light-7);
}

.readiness-check.status-warning {
  background: var(--el-color-warning-light-9);
  border-color: var(--el-color-warning-light-7);
}

.readiness-check.status-error {
  background: var(--el-color-danger-light-9);
  border-color: var(--el-color-danger-light-7);
}

.check-icon {
  font-weight: 700;
}

.check-label {
  font-weight: 600;
}

.check-message {
  margin-top: 2px;
  opacity: 0.9;
}

.readiness-orchestration {
  margin-top: 8px;
}

.orchestration-summary {
  margin: 0 0 8px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.orchestration-steps {
  margin: 0;
  padding-left: 18px;
  font-size: 12px;
}

.evaluation-preview {
  margin: 8px 0 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.readiness-ack {
  margin-top: 10px;
}
</style>
