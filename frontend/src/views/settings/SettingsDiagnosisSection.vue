<template>
  <section class="settings-section panel">
    <header class="section-head">
      <h2 class="section-title">抓取诊断</h2>
      <p class="section-desc">
        任务因登录、验证码或风控挂起时，自动分析页面并给出操作指引。配置保存在本机数据目录，保存后立即生效。
      </p>
    </header>

    <div class="pref-row">
      <div class="pref-copy">
        <strong>启用页面诊断</strong>
        <p>关闭后挂起任务不再自动分析，仅保留原有失败摘要。</p>
      </div>
      <el-switch v-model="form.enabled" size="large" />
    </div>

    <div class="pref-row" :class="{ disabled: !form.enabled }">
      <div class="pref-copy">
        <strong>LLM 精判</strong>
        <p>规则无法确定时调用大模型分析 DOM 文本；需先在「模型」页配置 DeepSeek。</p>
      </div>
      <el-switch v-model="form.llm_enabled" size="large" :disabled="!form.enabled" />
    </div>

    <div class="pref-row" :class="{ disabled: !form.enabled }">
      <div class="pref-copy">
        <strong>失败时截图</strong>
        <p>挂起时保存页面截图，可在任务详情查看；Vision 精判需配置 OpenAI Key。</p>
      </div>
      <el-switch v-model="form.screenshot_enabled" size="large" :disabled="!form.enabled" />
    </div>

    <div class="field-block" :class="{ disabled: !form.enabled || !form.llm_enabled }">
      <label class="field-label">LLM 超时（秒）</label>
      <el-input-number
        v-model="form.llm_timeout_seconds"
        :min="1"
        :max="120"
        :disabled="!form.enabled || !form.llm_enabled"
      />
    </div>

    <div class="field-block" :class="{ disabled: !form.enabled || !form.llm_enabled }">
      <label class="field-label">规则置信度跳过 LLM</label>
      <el-slider
        v-model="form.rule_confidence_skip_llm"
        :min="0.5"
        :max="1"
        :step="0.01"
        :format-tooltip="formatConfidence"
        :disabled="!form.enabled || !form.llm_enabled"
        show-input
      />
      <p class="hint-text">规则判断置信度 ≥ 该值时不再调用 LLM，默认 0.92。</p>
    </div>

    <div class="toolbar-row">
      <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      <el-button :loading="loading" @click="load">刷新</el-button>
    </div>
  </section>
</template>

<script setup>
import { onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import { fetchPageDiagnosisSettings, savePageDiagnosisSettings } from "../../api/pageDiagnosisSettings";

const loading = ref(false);
const saving = ref(false);

const form = reactive({
  enabled: true,
  llm_enabled: true,
  screenshot_enabled: true,
  llm_timeout_seconds: 8,
  rule_confidence_skip_llm: 0.92,
});

function formatConfidence(value) {
  return Number(value).toFixed(2);
}

function applyPayload(data) {
  form.enabled = !!data.enabled;
  form.llm_enabled = !!data.llm_enabled;
  form.screenshot_enabled = !!data.screenshot_enabled;
  form.llm_timeout_seconds = Number(data.llm_timeout_seconds) || 8;
  form.rule_confidence_skip_llm = Number(data.rule_confidence_skip_llm) || 0.92;
}

async function load() {
  loading.value = true;
  try {
    const data = await fetchPageDiagnosisSettings();
    applyPayload(data);
  } catch (err) {
    ElMessage.error(err.message || "加载失败");
  } finally {
    loading.value = false;
  }
}

async function save() {
  saving.value = true;
  try {
    const data = await savePageDiagnosisSettings({
      enabled: form.enabled,
      llm_enabled: form.llm_enabled,
      screenshot_enabled: form.screenshot_enabled,
      llm_timeout_seconds: form.llm_timeout_seconds,
      rule_confidence_skip_llm: form.rule_confidence_skip_llm,
    });
    applyPayload(data);
    ElMessage.success("已保存，立即生效");
  } catch (err) {
    ElMessage.error(err.message || "保存失败");
  } finally {
    saving.value = false;
  }
}

onMounted(() => {
  void load();
});
</script>

<style scoped>
.pref-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  padding: 14px 0;
  border-bottom: 1px solid var(--border, #e2e8f0);
  max-width: 640px;
}

.pref-row.disabled {
  opacity: 0.55;
}

.pref-copy strong {
  display: block;
  margin-bottom: 4px;
  font-size: 14px;
}

.pref-copy p {
  margin: 0;
  font-size: 12px;
  color: var(--muted);
  line-height: 1.5;
}

.field-block.disabled {
  opacity: 0.55;
}
</style>
