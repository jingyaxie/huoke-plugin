<template>
  <el-dialog
    :model-value="visible"
    title="创建编排任务"
    width="640px"
    destroy-on-close
    :close-on-click-modal="false"
    @update:model-value="$emit('update:visible', $event)"
  >
    <p class="dialog-desc">
      描述获客或自动化需求（自然语言 / JSON 均可）。点击提交后系统会先调用大模型理解并生成编排方案，再创建任务。
    </p>
    <el-form label-width="96px" class="job-form">
      <el-form-item label="执行策略">
        <el-select
          v-model="form.agent_strategy"
          style="width: 100%"
          placeholder="选择抓取/执行策略"
          :loading="strategiesLoading"
        >
          <el-option
            v-for="item in strategyOptions"
            :key="item.id"
            :label="strategyLabel(item)"
            :value="item.id"
          />
        </el-select>
        <p v-if="selectedStrategy?.description" class="field-hint block-hint">
          {{ selectedStrategy.description }}
        </p>
      </el-form-item>
      <el-form-item label="任务需求" required>
        <el-input
          v-model="form.message"
          type="textarea"
          :rows="6"
          placeholder="示例（自然语言）：帮我抓取抖音关键词「团餐配送」近3天评论，目标20条线索&#10;示例（JSON）：{&quot;keyword&quot;:&quot;团餐配送&quot;,&quot;platform&quot;:&quot;douyin&quot;,&quot;agent_strategy&quot;:&quot;skill-flow-douyin&quot;,&quot;target_count&quot;:20,&quot;comment_match&quot;:{&quot;keywords&quot;:[&quot;团餐&quot;,&quot;配送&quot;]}}"
        />
      </el-form-item>
      <el-form-item label="运行模式">
        <el-radio-group v-model="form.mode">
          <el-radio value="agent">Agent</el-radio>
          <el-radio value="plan">Plan</el-radio>
          <el-radio value="ask">Ask</el-radio>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="审批策略">
        <el-radio-group v-model="form.run_mode">
          <el-radio value="auto">工具自动批准</el-radio>
          <el-radio value="confirm">工具需审批</el-radio>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="自动执行">
        <el-switch v-model="form.auto_execute" active-text="创建后立即入队执行" inactive-text="仅创建，稍后手动启动" />
      </el-form-item>
      <el-form-item label="自动重启">
        <el-switch v-model="form.auto_restart" active-text="失败时自动重试" inactive-text="失败即停止" />
        <span v-if="form.auto_restart" class="field-hint">最多重试 {{ form.max_retries }} 次</span>
      </el-form-item>
      <el-form-item label="调度参数">
        <div class="param-row">
          <div class="param-item">
            <span class="param-label">优先级</span>
            <el-input-number v-model="form.priority" :min="1" :max="10" size="small" />
          </div>
          <div class="param-item">
            <span class="param-label">重试</span>
            <el-input-number v-model="form.max_retries" :min="0" :max="5" size="small" />
          </div>
          <div class="param-item">
            <span class="param-label">超时(秒)</span>
            <el-input-number v-model="form.timeout_seconds" :min="60" :max="3600" :step="60" size="small" />
          </div>
        </div>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="$emit('update:visible', false)">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="onSubmit">
        {{ submitting ? "大模型理解中…" : "提交任务" }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref, watch } from "vue";
import { fetchAgentStrategies } from "../api/agent";
import { getPlatformId } from "../api/http";

const props = defineProps({
  visible: { type: Boolean, default: false },
  submitting: { type: Boolean, default: false },
});

const emit = defineEmits(["update:visible", "submit"]);

const strategiesLoading = ref(false);
const strategyOptions = ref([]);

const defaultForm = () => ({
  message: "",
  agent_strategy: "",
  provider: "deepseek",
  mode: "agent",
  run_mode: "auto",
  auto_execute: true,
  auto_restart: true,
  timeout_seconds: 600,
  max_retries: 1,
  priority: 5,
});

const form = ref(defaultForm());

const selectedStrategy = computed(() =>
  strategyOptions.value.find((s) => s.id === form.value.agent_strategy),
);

function strategyLabel(item) {
  return item.is_default ? `${item.label}（默认）` : item.label;
}

async function loadStrategies() {
  strategiesLoading.value = true;
  try {
    const platform = getPlatformId() || "douyin";
    const list = await fetchAgentStrategies(platform);
    strategyOptions.value = Array.isArray(list) ? list : [];
    const defaultItem = strategyOptions.value.find((s) => s.is_default) || strategyOptions.value[0];
    if (defaultItem && !form.value.agent_strategy) {
      form.value.agent_strategy = defaultItem.id;
    }
  } catch {
    strategyOptions.value = [];
  } finally {
    strategiesLoading.value = false;
  }
}

watch(
  () => props.visible,
  (open) => {
    if (open) {
      form.value = defaultForm();
      loadStrategies();
    }
  },
);

function onSubmit() {
  if (!form.value.message.trim()) return;
  const payload = { ...form.value, message: form.value.message.trim() };
  if (!payload.agent_strategy) delete payload.agent_strategy;
  emit("submit", payload);
}
</script>

<style scoped>
.dialog-desc {
  margin: 0 0 16px;
  font-size: 13px;
  color: #64748b;
  line-height: 1.5;
}

.param-row {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
}

.param-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.param-label {
  font-size: 12px;
  color: #94a3b8;
}

.field-hint {
  margin-left: 10px;
  font-size: 12px;
  color: #94a3b8;
}

.block-hint {
  margin: 6px 0 0;
  margin-left: 0;
  line-height: 1.4;
}
</style>
