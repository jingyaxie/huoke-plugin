<template>
  <div class="evaluation-section">
    <el-button text type="primary" @click="expanded = !expanded">
      {{ expanded ? "收起" : "展开" }}线索识别标准（可选）
    </el-button>
    <div v-if="expanded" class="evaluation-body">
      <p class="evaluation-hint">
        不填写时由大模型以「使用心得」方式评估；填写后可补充额外约束。
      </p>
      <el-form-item v-if="templates.length" label="行业模板">
        <el-select v-model="localTemplateId" clearable placeholder="不使用模板" style="width: 100%">
          <el-option
            v-for="tpl in templates"
            :key="tpl.id"
            :label="tpl.label || tpl.id"
            :value="tpl.id"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="目标客户">
        <el-input v-model="localTargetCustomer" placeholder="例如：本地准备装修的业主" />
      </el-form-item>
      <el-form-item label="有效线索描述">
        <el-input
          v-model="localAcceptDescription"
          type="textarea"
          :rows="3"
          placeholder="例如：询价、预约量房、咨询安装周期"
        />
      </el-form-item>
      <el-form-item label="排除类型">
        <el-input v-model="localRejectSignals" placeholder="例如：同行,招聘,广告（逗号分隔）" />
      </el-form-item>
    </div>
  </div>
</template>

<script setup>
import { computed } from "vue";

const props = defineProps({
  templates: { type: Array, default: () => [] },
  evalTemplateId: { type: String, default: "" },
  targetCustomer: { type: String, default: "" },
  acceptDescription: { type: String, default: "" },
  rejectSignals: { type: String, default: "" },
  expanded: { type: Boolean, default: false },
});

const emit = defineEmits([
  "update:evalTemplateId",
  "update:targetCustomer",
  "update:acceptDescription",
  "update:rejectSignals",
  "update:expanded",
]);

const expanded = computed({
  get: () => props.expanded,
  set: (value) => emit("update:expanded", value),
});

const localTemplateId = computed({
  get: () => props.evalTemplateId,
  set: (value) => emit("update:evalTemplateId", value || ""),
});

const localTargetCustomer = computed({
  get: () => props.targetCustomer,
  set: (value) => emit("update:targetCustomer", value),
});

const localAcceptDescription = computed({
  get: () => props.acceptDescription,
  set: (value) => emit("update:acceptDescription", value),
});

const localRejectSignals = computed({
  get: () => props.rejectSignals,
  set: (value) => emit("update:rejectSignals", value),
});
</script>

<style scoped>
.evaluation-section {
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
  padding: 8px 12px 0;
}

.evaluation-body {
  padding-bottom: 4px;
}

.evaluation-hint {
  margin: 0 0 8px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
</style>
