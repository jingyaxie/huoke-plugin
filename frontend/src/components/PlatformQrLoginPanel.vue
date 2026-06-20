<template>
  <div class="qr-login-panel">
    <div class="qr-login-header">
      <div>
        <div class="qr-login-title">{{ platformLabel }} 扫码登录</div>
        <div class="qr-login-meta">
          租户 <strong>{{ tenantId }}</strong> · 账号 <strong>{{ accountId }}</strong>
        </div>
      </div>
      <el-button link type="primary" @click="handleClose">关闭</el-button>
    </div>

    <div v-loading="loading" class="qr-login-body">
      <div v-if="qrImageSrc" class="qr-login-image-wrap">
        <img :src="qrImageSrc" alt="登录二维码" class="qr-login-image" />
      </div>
      <el-empty v-else-if="!loading" description="未获取到二维码，请刷新重试" />

      <el-alert
        v-if="statusMessage"
        class="qr-login-alert"
        :title="statusMessage"
        :type="alertType"
        :closable="false"
        show-icon
      />

      <p v-if="validityHint" class="qr-login-hint">{{ validityHint }}</p>

      <div class="qr-login-actions">
        <el-button :loading="loading" @click="refreshQr">刷新二维码</el-button>
        <el-button @click="$emit('open-browser-login')">打开浏览器登录</el-button>
        <el-button @click="handleClose">取消</el-button>
      </div>
      <p class="qr-login-hint">
        若二维码无法显示、或状态「已登录」但任务仍提示未登录，请点「打开浏览器登录」在本机 Chrome 完成验证。
      </p>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from "vue";
import {
  cancelAccountPlatformQrLogin,
  createAccountPlatformQrLogin,
  fetchAccountPlatformQrLoginStatus,
} from "../api/accounts";

const props = defineProps({
  accountId: { type: String, required: true },
  platform: { type: String, required: true },
  platformLabel: { type: String, default: "" },
  tenantId: { type: String, default: "" },
});

const emit = defineEmits(["close", "success", "open-browser-login"]);

const loading = ref(false);
const sessionId = ref("");
const qrImageSrc = ref("");
const statusMessage = ref("");
const validityHint = ref("");
const loginStatus = ref("pending");
const pollTimer = ref(null);

const alertType = computed(() => {
  if (loginStatus.value === "confirmed") return "success";
  if (loginStatus.value === "scanned") return "info";
  if (["expired", "error", "cancelled"].includes(loginStatus.value)) return "warning";
  return "info";
});

function stopPolling() {
  if (pollTimer.value) {
    clearInterval(pollTimer.value);
    pollTimer.value = null;
  }
}

function applySession(data) {
  sessionId.value = data.session_id || "";
  loginStatus.value = data.status || "pending";
  validityHint.value = data.validity_hint || data.diagnostic || "";
  statusMessage.value = data.message || data.diagnostic || "请使用手机 App 扫描二维码";

  if (data.qr_image_base64) {
    qrImageSrc.value = data.qr_image_base64;
  } else if (data.qr_image_url) {
    qrImageSrc.value = data.qr_image_url;
  }
}

async function pollOnce() {
  if (!sessionId.value) return;
  try {
    const data = await fetchAccountPlatformQrLoginStatus(
      props.accountId,
      props.platform,
      sessionId.value,
    );
    loginStatus.value = data.status || loginStatus.value;
    validityHint.value = data.validity_hint || validityHint.value;
    statusMessage.value = data.message || statusMessage.value;

    const authStatus = data.login_status?.auth_status || data.login_status?.status;
    const loginReady =
      (data.login_ready || data.status === "confirmed") &&
      (!props.platform || props.platform !== "xiaohongshu" || authStatus === "authenticated");

    if (loginReady) {
      loginStatus.value = "confirmed";
      statusMessage.value = data.message || data.login_status?.message || "登录成功";
      stopPolling();
      window.setTimeout(() => emit("success", data), 400);
      return;
    }

    if (data.status === "confirmed" && props.platform === "xiaohongshu") {
      loginStatus.value = "error";
      statusMessage.value =
        data.message ||
        data.login_status?.message ||
        "扫码已完成，但登录态未成功写入，请刷新二维码或打开浏览器登录";
      stopPolling();
      return;
    }

    if (["expired", "error", "cancelled"].includes(data.status)) {
      stopPolling();
      statusMessage.value = data.message || "二维码已失效，请刷新后重试";
    }
  } catch (err) {
    statusMessage.value = err.message || "查询登录状态失败";
    loginStatus.value = "error";
  }
}

function startPolling(intervalSeconds = 2) {
  stopPolling();
  pollTimer.value = setInterval(() => {
    pollOnce();
  }, Math.max(1, intervalSeconds) * 1000);
}

async function refreshQr() {
  loading.value = true;
  stopPolling();
  try {
    if (sessionId.value) {
      try {
        await cancelAccountPlatformQrLogin(props.accountId, props.platform, sessionId.value);
      } catch {
        // ignore stale session cancel errors
      }
    }
    const data = await createAccountPlatformQrLogin(props.accountId, props.platform, {
      refresh: true,
    });
    applySession(data);
    if (!qrImageSrc.value) {
      statusMessage.value = data.diagnostic || "未获取到二维码图片";
      loginStatus.value = "error";
      return;
    }
    statusMessage.value = data.diagnostic || "请使用手机 App 扫描二维码";
    loginStatus.value = data.status || "pending";
    startPolling(data.poll_interval_seconds || 2);
  } catch (err) {
    qrImageSrc.value = "";
    sessionId.value = "";
    statusMessage.value = err.message || "获取登录二维码失败";
    loginStatus.value = "error";
  } finally {
    loading.value = false;
  }
}

async function handleClose() {
  stopPolling();
  if (sessionId.value) {
    try {
      await cancelAccountPlatformQrLogin(props.accountId, props.platform, sessionId.value);
    } catch {
      // ignore
    }
  }
  emit("close");
}

watch(
  () => [props.accountId, props.platform],
  () => {
    refreshQr();
  },
  { immediate: true },
);

onBeforeUnmount(() => {
  stopPolling();
  if (sessionId.value && loginStatus.value !== "confirmed") {
    cancelAccountPlatformQrLogin(props.accountId, props.platform, sessionId.value).catch(() => {});
  }
});
</script>

<style scoped>
.qr-login-panel {
  margin-top: 16px;
  padding: 16px;
  border: 1px solid var(--el-border-color-light, #e5e7eb);
  border-radius: 12px;
  background: #fafbfc;
}

.qr-login-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.qr-login-title {
  font-size: 15px;
  font-weight: 600;
  color: #1f2937;
}

.qr-login-meta {
  margin-top: 4px;
  font-size: 12px;
  color: #6b7280;
}

.qr-login-body {
  min-height: 120px;
}

.qr-login-image-wrap {
  display: flex;
  justify-content: center;
  padding: 12px 0 8px;
}

.qr-login-image {
  width: 220px;
  height: 220px;
  object-fit: contain;
  border-radius: 8px;
  background: #fff;
  border: 1px solid #e5e7eb;
}

.qr-login-alert {
  margin-top: 12px;
}

.qr-login-hint {
  margin: 10px 0 0;
  font-size: 12px;
  color: #6b7280;
  text-align: center;
}

.qr-login-actions {
  display: flex;
  justify-content: center;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 14px;
}

.qr-login-vnc-hint {
  margin: 12px 0 0;
  font-size: 12px;
  color: #64748b;
  line-height: 1.6;
  text-align: center;
}
</style>
