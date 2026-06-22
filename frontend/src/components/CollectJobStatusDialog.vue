<template>
  <el-dialog
    v-model="visible"
    :title="brief?.title || '任务状态'"
    width="560px"
    destroy-on-close
    class="collect-status-dialog"
    @closed="onClosed"
  >
    <div v-if="brief" class="status-body" :class="`status-body--${brief.tone || 'info'}`">
      <div class="status-section">
        <div class="section-label">概况</div>
        <p class="section-summary">{{ brief.summary }}</p>
      </div>

      <div v-if="brief.reason && brief.reason !== brief.summary" class="status-section">
        <div class="section-label">原因说明</div>
        <p class="section-text">{{ brief.reason }}</p>
      </div>

      <div v-if="statsLines.length" class="status-section stats-section">
        <div class="section-label">采集进度</div>
        <ul class="stats-list">
          <li v-for="(line, idx) in statsLines" :key="idx">{{ line }}</li>
        </ul>
      </div>

      <div v-if="brief.next_actions?.length" class="status-section next-section">
        <div class="section-label">建议下一步</div>
        <ol class="next-list">
          <li v-for="(action, idx) in brief.next_actions" :key="idx">{{ action }}</li>
        </ol>
      </div>
    </div>

    <template #footer>
      <el-button @click="visible = false">关闭</el-button>
      <el-button v-if="brief?.can_continue" type="primary" @click="onContinue">
        继续采集
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed } from "vue";

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  brief: { type: Object, default: null },
});

const emit = defineEmits(["update:modelValue", "continue", "closed"]);

const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit("update:modelValue", value),
});

const statsLines = computed(() => {
  const stats = props.brief?.stats;
  if (!stats) return [];
  const lines = [];
  if (stats.precise > 0 || stats.comments > 0) {
    if (stats.precise > 0) lines.push(`精准线索：${stats.precise} 条`);
    if (stats.comments > 0) lines.push(`评论总数：${stats.comments} 条`);
  }
  if (stats.target > 0) {
    lines.push(`目标：${stats.progress}/${stats.target}`);
  }
  return lines;
});

function onContinue() {
  emit("continue");
  visible.value = false;
}

function onClosed() {
  emit("closed");
}
</script>

<style scoped>
.status-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.status-section {
  padding: 12px 14px;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
  background: #f8fafc;
}

.status-body--error .status-section:first-child {
  background: #fef2f2;
  border-color: #fecaca;
}

.status-body--warning .status-section:first-child {
  background: #fffbeb;
  border-color: #fde68a;
}

.status-body--primary .status-section:first-child {
  background: #eff6ff;
  border-color: #bfdbfe;
}

.next-section {
  background: #f0fdf4;
  border-color: #bbf7d0;
}

.section-label {
  font-size: 12px;
  font-weight: 600;
  color: #64748b;
  margin-bottom: 6px;
}

.section-summary,
.section-text {
  margin: 0;
  font-size: 14px;
  line-height: 1.6;
  color: #334155;
  white-space: pre-wrap;
}

.stats-list,
.next-list {
  margin: 0;
  padding-left: 18px;
  font-size: 13px;
  line-height: 1.6;
  color: #475569;
}

.next-list li + li {
  margin-top: 6px;
}
</style>
