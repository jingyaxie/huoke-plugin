<template>
  <el-dialog
    v-model="visible"
    title="授权账号"
    width="560px"
    :close-on-click-modal="false"
    @closed="handleClosed"
  >
    <p class="modal-subtitle">
      在本机 Chrome 完成平台登录（含扫码、短信验证）；系统将自动检测并同步绑定。
    </p>

    <AccountHealthAlerts
      v-if="healthIssues.length"
      class="modal-health"
      title="绑定前请先处理以下账号异常"
      :issues="healthIssues"
      :resolving-key="resolvingKey"
      @resolve="(issue) => $emit('resolve-health', issue)"
    />

    <div class="field-block">
      <label class="field-label">选择渠道</label>
      <div class="platform-grid">
        <button
          v-for="opt in platformOptions"
          :key="opt.key"
          type="button"
          class="platform-btn"
          :class="{ active: platform === opt.key }"
          :disabled="loading || bound"
          @click="platform = opt.key"
        >
          {{ opt.label }}
        </button>
      </div>
    </div>

    <div class="field-block">
      <label class="field-label" for="bind-nickname">自定义名称（可选）</label>
      <el-input
        id="bind-nickname"
        v-model="customNickname"
        maxlength="32"
        placeholder="例如：门店主号、运营小号"
        :disabled="loading || bound"
      />
    </div>

    <el-alert
      class="bind-hint"
      type="info"
      :closable="false"
      show-icon
      :title="`点击「开始绑定」后，会弹出独立 Chrome 窗口（${platformHost}）。请在该窗口完成所有验证，不要关闭 Chrome，直到下方步骤全部完成。`"
    />

    <ol class="bind-steps">
      <li
        v-for="step in steps"
        :key="step.id"
        class="bind-step"
        :class="`bind-step--${step.status}`"
      >
        <span class="bind-step-icon">{{ stepIcon(step.status) }}</span>
        <div class="bind-step-body">
          <div class="bind-step-label">{{ step.label }}</div>
          <div v-if="step.detail" class="bind-step-detail">{{ step.detail }}</div>
        </div>
      </li>
    </ol>

    <el-alert v-if="bound" type="success" :closable="false" show-icon title="绑定成功，账号列表将自动刷新。" />
    <el-alert v-else-if="activeHint" type="info" :closable="false" :title="activeHint" />
    <el-alert v-if="error" type="error" :closable="false" :title="error" />

    <template #footer>
      <el-button @click="handleClose">关闭</el-button>
      <el-button type="primary" :loading="loading" :disabled="bound" @click="start">
        {{ loading ? "绑定中…" : bound ? "已完成" : "开始绑定" }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref, watch } from "vue";
import AccountHealthAlerts from "./AccountHealthAlerts.vue";
import { BINDABLE_PLATFORMS, PLATFORM_LABEL } from "../utils/accountSettings";
import { initialBindSteps, runBrowserPlatformBindFlow } from "../utils/platformBindFlow";

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  accountId: { type: String, required: true },
  healthIssues: { type: Array, default: () => [] },
  resolvingKey: { type: String, default: "" },
});

const emit = defineEmits(["update:modelValue", "bound", "resolve-health"]);

const platformOptions = BINDABLE_PLATFORMS.map((key) => ({
  key,
  label: PLATFORM_LABEL[key] || key,
}));

const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit("update:modelValue", value),
});

const platform = ref("douyin");
const customNickname = ref("");
const loading = ref(false);
const bound = ref(false);
const error = ref("");
const steps = ref(initialBindSteps());
const stopRef = ref(false);

const platformHost = computed(() =>
  platform.value === "xiaohongshu" ? "xiaohongshu.com" : "douyin.com",
);

const activeHint = computed(() => {
  const reversed = [...steps.value].reverse();
  const hit = reversed.find((s) => s.detail);
  return hit?.detail || "";
});

watch(
  () => props.modelValue,
  (open) => {
    if (!open) {
      stopRef.value = true;
      loading.value = false;
      bound.value = false;
      error.value = "";
      steps.value = initialBindSteps();
      customNickname.value = "";
      return;
    }
    stopRef.value = false;
  },
);

function stepIcon(status) {
  if (status === "done") return "✓";
  if (status === "error") return "✕";
  if (status === "skipped") return "–";
  if (status === "active") return "…";
  return "○";
}

function handleClose() {
  stopRef.value = true;
  visible.value = false;
}

function handleClosed() {
  stopRef.value = true;
}

async function start() {
  if (!props.accountId) {
    error.value = "请先选择或创建 Huoke 账号";
    return;
  }
  loading.value = true;
  error.value = "";
  bound.value = false;
  steps.value = initialBindSteps();
  try {
    const ok = await runBrowserPlatformBindFlow(props.accountId, platform.value, {
      nickname: customNickname.value,
      shouldStop: () => stopRef.value,
      onSteps: (next) => {
        steps.value = next;
      },
    });
    if (ok) {
      bound.value = true;
      emit("bound");
    } else if (!stopRef.value) {
      error.value = "绑定未完成，请查看下方步骤说明后重试";
    }
  } catch (e) {
    error.value = e?.message || "绑定失败";
  } finally {
    loading.value = false;
  }
}
</script>

<style scoped>
.modal-subtitle {
  margin: 0 0 16px;
  font-size: 13px;
  color: var(--muted, #6b7280);
}

.modal-health {
  margin-bottom: 16px;
}

.field-block {
  margin-bottom: 16px;
}

.field-label {
  display: block;
  margin-bottom: 8px;
  font-size: 13px;
  font-weight: 500;
}

.platform-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}

.platform-btn {
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 12px 16px;
  text-align: left;
  background: #fff;
  cursor: pointer;
  font-size: 14px;
}

.platform-btn.active {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
}

.platform-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.bind-hint {
  margin-bottom: 16px;
}

.bind-steps {
  list-style: none;
  margin: 0 0 16px;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.bind-step {
  display: flex;
  gap: 12px;
  border: 1px solid #f3f4f6;
  border-radius: 6px;
  padding: 10px 12px;
  font-size: 12px;
}

.bind-step--done {
  border-color: #a7f3d0;
  background: #ecfdf5;
  color: #065f46;
}

.bind-step--error {
  border-color: #fecaca;
  background: #fef2f2;
  color: #991b1b;
}

.bind-step--active {
  border-color: #bfdbfe;
  background: #eff6ff;
  color: #1e40af;
}

.bind-step--skipped {
  border-color: #e5e7eb;
  background: #f9fafb;
  color: #6b7280;
}

.bind-step-icon {
  width: 16px;
  text-align: center;
  font-weight: 600;
}

.bind-step-label {
  font-weight: 500;
}

.bind-step-detail {
  margin-top: 4px;
  line-height: 1.5;
  opacity: 0.9;
}
</style>
