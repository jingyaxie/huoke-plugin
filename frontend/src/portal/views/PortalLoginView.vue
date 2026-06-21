<template>
  <div class="portal-login-page">
    <div class="login-shell">
      <section class="login-hero">
        <div class="login-brand">盈小蚁</div>
        <h1 class="login-hero-title">客户增长与服务中台</h1>
        <p class="login-hero-slogan">让 AI 帮你获客、成交、服务，一站式增长。</p>
      </section>

      <section class="login-card">
        <div class="login-card-header">
          <h2>欢迎登录</h2>
          <p class="login-card-subtitle">登录您的盈小蚁客户账号</p>
        </div>

        <div class="login-tabs">
          <button
            type="button"
            :class="{ active: loginMethod === 'sms' }"
            @click="loginMethod = 'sms'"
          >
            验证码登录
          </button>
          <button
            type="button"
            :class="{ active: loginMethod === 'password' }"
            @click="loginMethod = 'password'"
          >
            密码登录
          </button>
        </div>

        <el-form class="login-form" label-position="top" @submit.prevent="onSubmit">
          <template v-if="loginMethod === 'sms'">
            <el-form-item label="手机号">
              <el-input
                v-model="smsPhone"
                placeholder="请输入手机号"
                inputmode="numeric"
                autocomplete="tel"
                maxlength="11"
              />
            </el-form-item>
            <el-form-item label="验证码">
              <div class="captcha-row">
                <el-input
                  v-model="smsCode"
                  placeholder="请输入6位验证码"
                  inputmode="numeric"
                  maxlength="6"
                  autocomplete="one-time-code"
                />
                <el-button
                  :disabled="smsCountdown > 0 || sendingSms"
                  :loading="sendingSms"
                  @click="onSendSms"
                >
                  {{ smsCountdown > 0 ? `${smsCountdown}s` : "获取验证码" }}
                </el-button>
              </div>
            </el-form-item>
          </template>

          <template v-else>
            <el-form-item label="账号">
              <el-input
                v-model="username"
                placeholder="请输入账号或手机号"
                autocomplete="username"
              />
            </el-form-item>
            <el-form-item label="密码">
              <el-input
                v-model="password"
                type="password"
                show-password
                placeholder="请输入密码"
                autocomplete="current-password"
              />
            </el-form-item>
          </template>

          <el-alert
            v-if="errorMessage"
            :title="errorMessage"
            type="error"
            show-icon
            :closable="false"
            class="login-alert"
          />

          <el-button
            type="primary"
            native-type="submit"
            class="login-submit"
            :loading="submitting"
          >
            登 录
          </el-button>
        </el-form>

        <div class="login-support">
          <div class="support-title">官方支持</div>
          <div class="support-item">电话：400-178-3839</div>
          <div class="support-item">商务合作：331375777@qq.com</div>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { sendPortalSmsCode } from "../api/portalAuth";
import { mapH5PathToCloudRoute } from "../config/cloudNav";
import { probePortalSession, submitPortalLoginForm, syncPortalDisplayName } from "../utils/portalLoginBridge";
import { isPortalAuthenticated, readPortalAuth, setPortalAuthenticated } from "../utils/portalShell";

const router = useRouter();
const route = useRoute();

const loginMethod = ref("sms");
const smsPhone = ref("");
const smsCode = ref("");
const username = ref("");
const password = ref("");
const submitting = ref(false);
const sendingSms = ref(false);
const errorMessage = ref("");
const smsCountdown = ref(0);

let countdownTimer = null;

function resolveRedirectTarget() {
  if (typeof route.query.redirect === "string" && route.query.redirect) {
    return route.query.redirect;
  }
  const authPath = readPortalAuth()?.path;
  if (authPath) return mapH5PathToCloudRoute(authPath);
  return "/cloud/dashboard";
}

function redirectAfterLogin() {
  router.replace(resolveRedirectTarget()).catch(() => {});
}

async function tryExistingSession() {
  if (isPortalAuthenticated()) {
    redirectAfterLogin();
    return true;
  }
  const ok = await probePortalSession();
  if (ok) {
    redirectAfterLogin();
    return true;
  }
  return false;
}

function startSmsCountdown() {
  smsCountdown.value = 60;
  countdownTimer = window.setInterval(() => {
    smsCountdown.value -= 1;
    if (smsCountdown.value <= 0) {
      smsCountdown.value = 0;
      window.clearInterval(countdownTimer);
      countdownTimer = null;
    }
  }, 1000);
}

async function onSendSms() {
  const phone = smsPhone.value.trim();
  if (!phone) {
    ElMessage.warning("请输入手机号");
    return;
  }
  sendingSms.value = true;
  errorMessage.value = "";
  try {
    await sendPortalSmsCode(phone);
    ElMessage.success("验证码已发送");
    startSmsCountdown();
  } catch (err) {
    errorMessage.value = err?.message || "发送验证码失败";
  } finally {
    sendingSms.value = false;
  }
}

async function onSubmit() {
  errorMessage.value = "";
  submitting.value = true;
  try {
    const fields =
      loginMethod.value === "sms"
        ? {
            login_method: "sms",
            sms_phone: smsPhone.value.trim(),
            code: smsCode.value.trim(),
          }
        : {
            login_method: "password",
            username: username.value.trim(),
            password: password.value,
          };

    if (loginMethod.value === "sms") {
      if (!fields.sms_phone || !fields.code) {
        throw new Error("请输入手机号和验证码");
      }
    } else if (!fields.username || !fields.password) {
      throw new Error("请输入账号和密码");
    }

    const redirect = resolveRedirectTarget();
    if (redirect.startsWith("/")) {
      fields.next = redirect.startsWith("/cloud/")
        ? redirect.replace(/^\/cloud/, "/customer")
        : redirect;
    }

    await submitPortalLoginForm(fields);
    const loginLabel = loginMethod.value === "sms" ? fields.sms_phone : fields.username;
    setPortalAuthenticated({ displayName: loginLabel, username: loginLabel });
    ElMessage.success("登录成功");
    redirectAfterLogin();
    void syncPortalDisplayName().catch(() => {});
  } catch (err) {
    errorMessage.value = err?.message || "登录失败，请检查账号信息";
  } finally {
    submitting.value = false;
  }
}

onMounted(async () => {
  await tryExistingSession();
});

onUnmounted(() => {
  if (countdownTimer) {
    window.clearInterval(countdownTimer);
    countdownTimer = null;
  }
});
</script>

<style scoped>
.portal-login-page {
  width: 100%;
  min-height: 100vh;
  box-sizing: border-box;
  overflow: auto;
  background: linear-gradient(160deg, #f0f9ff 0%, #f8fafc 48%, #eff6ff 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 32px 16px;
}

.login-shell {
  display: grid;
  grid-template-columns: minmax(240px, 1fr) minmax(300px, 420px);
  width: 100%;
  max-width: 860px;
  overflow: hidden;
  background: #fff;
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 18px;
  box-shadow: 0 18px 48px rgba(15, 23, 42, 0.08);
}

.login-hero {
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 36px 28px;
  color: #334155;
  border-right: 1px solid rgba(148, 163, 184, 0.16);
  background:
    radial-gradient(circle at 88% 18%, rgba(22, 93, 255, 0.08), transparent 46%),
    radial-gradient(circle at 0% 100%, rgba(54, 211, 153, 0.06), transparent 42%),
    linear-gradient(165deg, #f7faff 0%, #f3f7ff 52%, #f8fafc 100%);
}

.login-brand {
  font-size: 28px;
  font-weight: 700;
  letter-spacing: 1px;
  background: linear-gradient(135deg, #165dff, #36d399);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}

.login-hero-title {
  margin: 18px 0 0;
  font-size: 22px;
  color: #0f172a;
}

.login-hero-slogan {
  margin: 14px 0 0;
  font-size: 15px;
  line-height: 1.6;
  color: #64748b;
}

.login-card {
  padding: 32px 28px 24px;
}

.login-card-header h2 {
  margin: 0;
  font-size: 24px;
  color: #0f172a;
}

.login-card-subtitle {
  margin: 8px 0 0;
  font-size: 14px;
  color: #64748b;
}

.login-tabs {
  display: flex;
  gap: 20px;
  margin: 24px 0 8px;
  border-bottom: 1px solid #e2e8f0;
}

.login-tabs button {
  position: relative;
  padding: 0 0 12px;
  border: none;
  background: transparent;
  font: inherit;
  font-size: 15px;
  color: #64748b;
  cursor: pointer;
}

.login-tabs button.active {
  color: #165dff;
  font-weight: 600;
}

.login-tabs button.active::after {
  content: "";
  position: absolute;
  left: 0;
  right: 0;
  bottom: -1px;
  height: 2px;
  border-radius: 999px;
  background: linear-gradient(135deg, #165dff, #36d399);
}

.login-form {
  margin-top: 8px;
}

.captcha-row {
  display: flex;
  gap: 10px;
  width: 100%;
}

.captcha-row .el-input {
  flex: 1;
}

.login-alert {
  margin-bottom: 12px;
}

.login-submit {
  width: 100%;
  height: 46px;
  margin-top: 4px;
  border: none;
  border-radius: 10px;
  background: linear-gradient(135deg, #165dff, #36d399);
  box-shadow: 0 10px 24px rgba(22, 93, 255, 0.22);
}

.login-support {
  margin-top: 24px;
  padding-top: 16px;
  border-top: 1px solid #eef2f7;
  font-size: 12px;
  color: #94a3b8;
}

.support-title {
  margin-bottom: 6px;
  font-weight: 600;
  color: #64748b;
}

.support-item + .support-item {
  margin-top: 4px;
}

@media (max-width: 760px) {
  .login-shell {
    grid-template-columns: 1fr;
  }

  .login-hero {
    border-right: none;
    border-bottom: 1px solid rgba(148, 163, 184, 0.16);
    padding: 24px 20px;
  }

  .login-card {
    padding: 24px 20px;
  }
}
</style>
