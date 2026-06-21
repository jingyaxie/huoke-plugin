<template>
  <section class="settings-section panel">
    <header class="section-head">
      <h2 class="section-title">大模型</h2>
      <p class="section-desc">
        配置 DeepSeek API，用于评论评估与线索筛选。密钥保存在本机 .env.local，不会上传云端。
      </p>
    </header>

    <el-alert
      v-if="loaded && !form.llm_configured"
      type="warning"
      :closable="false"
      show-icon
      class="status-alert"
      title="尚未配置 DeepSeek API Key，智能编排与线索评估将无法使用 LLM。"
    />
    <el-alert
      v-else-if="loaded && form.llm_configured"
      type="success"
      :closable="false"
      show-icon
      class="status-alert"
      title="DeepSeek 已就绪，配置保存在本机。"
    />

    <div class="provider-card">
      <div class="field-block">
        <label class="field-label">API Key</label>
        <el-input
          v-model="form.deepseek_api_key"
          type="password"
          show-password
          :placeholder="deepseekKeyPlaceholder"
          autocomplete="off"
        />
      </div>
      <div class="field-block">
        <label class="field-label">Base URL</label>
        <el-input v-model="form.deepseek_base_url" placeholder="https://api.deepseek.com/v1" />
      </div>
      <div class="field-block">
        <label class="field-label">模型</label>
        <el-input v-model="form.deepseek_model" placeholder="deepseek-chat" />
      </div>
      <p v-if="form.deepseek.configured" class="hint-text">
        当前已配置：{{ form.deepseek.api_key_masked || "已设置" }} · {{ form.deepseek.model }}
      </p>
    </div>

    <p v-if="envFile" class="hint-text env-path">本机配置文件：{{ envFile }}</p>

    <div class="toolbar-row">
      <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      <el-button :loading="loading" @click="load">刷新</el-button>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import { fetchLlmSettings, saveLlmSettings } from "../../api/llmSettings";
import { useAgentPreferences } from "../../composables/useAgentPreferences";

const { provider } = useAgentPreferences();

const loading = ref(false);
const saving = ref(false);
const loaded = ref(false);
const envFile = ref("");

const form = reactive({
  llm_configured: false,
  deepseek_api_key: "",
  deepseek_base_url: "",
  deepseek_model: "",
  deepseek: { configured: false, api_key_masked: null, model: "" },
});

const deepseekKeyPlaceholder = computed(() =>
  form.deepseek.configured ? "留空表示不修改已保存的 Key" : "sk-...",
);

function applyPayload(data) {
  form.llm_configured = !!data.llm_configured;
  form.deepseek = data.deepseek || form.deepseek;
  form.deepseek_base_url = data.deepseek?.base_url || "";
  form.deepseek_model = data.deepseek?.model || "";
  form.deepseek_api_key = "";
  envFile.value = data.env_file || "";
  provider.value = "deepseek";
}

async function load() {
  loading.value = true;
  try {
    const data = await fetchLlmSettings();
    applyPayload(data);
    loaded.value = true;
  } catch (err) {
    ElMessage.error(err.message || "加载失败");
  } finally {
    loading.value = false;
  }
}

async function save() {
  saving.value = true;
  try {
    const payload = {
      deepseek_base_url: form.deepseek_base_url,
      deepseek_model: form.deepseek_model,
    };
    if (form.deepseek_api_key.trim()) {
      payload.deepseek_api_key = form.deepseek_api_key.trim();
    }
    const result = await saveLlmSettings(payload);
    ElMessage.success(result.message || "已保存");
    provider.value = "deepseek";
    await load();
    window.dispatchEvent(new CustomEvent("huoke-agent-prefs-changed"));
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
.status-alert {
  margin-bottom: 14px;
  max-width: 640px;
}

.provider-card {
  margin: 16px 0;
  padding: 14px 16px;
  max-width: 640px;
  border: 1px solid var(--border, #e2e8f0);
  border-radius: 10px;
  background: #f8fafc;
}

.env-path {
  word-break: break-all;
  max-width: 640px;
}
</style>
