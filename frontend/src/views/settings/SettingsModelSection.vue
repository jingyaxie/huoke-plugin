<template>
  <section class="settings-section panel">
    <header class="section-head">
      <h2 class="section-title">评论评估</h2>
      <p class="section-desc">
        线索精准度评估统一走盈小蚁后台默认 LLM。登录后会自动同步访问令牌，无需在本机填写 API Key。
      </p>
    </header>

    <el-alert
      v-if="loaded && !form.evaluation_ready"
      type="warning"
      :closable="false"
      show-icon
      class="status-alert"
      title="评估未就绪：请先登录盈小蚁，系统会自动写入本机 Sidecar。"
    />
    <el-alert
      v-else-if="loaded && form.evaluation_ready"
      type="success"
      :closable="false"
      show-icon
      class="status-alert"
      title="后台评估已就绪，将使用盈小蚁默认 LLM 识别精准客户。"
    />

    <div class="provider-card">
      <div class="field-block">
        <label class="field-label">后台 API 地址</label>
        <el-input v-model="form.backend_base_url" placeholder="/api 或 https://your-domain.com/api" />
      </div>
      <p v-if="form.backend.configured" class="hint-text">
        已同步令牌：{{ form.backend.access_token_masked || "已设置" }}
      </p>
      <p v-else-if="portalAccessToken" class="hint-text">
        已检测到登录令牌，保存后将写入 Sidecar。
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
import {
  defaultBackendBaseUrl,
  ensureEvaluationCredentialsSynced,
  isEvaluationReady,
  loadEvaluationSettings,
  saveEvaluationSettings,
} from "../../api/commentEvaluation";
import { getAccessToken } from "../../api/http";

const loading = ref(false);
const saving = ref(false);
const loaded = ref(false);
const envFile = ref("");

const form = reactive({
  evaluation_ready: false,
  backend_base_url: "",
  backend: { configured: false, access_token_masked: null, base_url: "" },
});

const portalAccessToken = computed(() => getAccessToken());

function applyPayload(data) {
  form.evaluation_ready = isEvaluationReady(data);
  form.backend = data.backend || form.backend;
  form.backend_base_url = data.backend?.base_url || defaultBackendBaseUrl();
  envFile.value = data.env_file || "";
}

async function load() {
  loading.value = true;
  try {
    await ensureEvaluationCredentialsSynced();
    const data = await loadEvaluationSettings();
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
    const result = await saveEvaluationSettings({
      backendBaseUrl: form.backend_base_url,
    });
    ElMessage.success(result.message || "已保存");
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
