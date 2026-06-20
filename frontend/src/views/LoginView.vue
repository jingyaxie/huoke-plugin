<template>
  <section class="panel login-page">
      <div class="page-title">登录中心</div>
      <p class="page-subtitle">系统账号登录，用于获取 JWT 并自动同步租户信息。</p>

      <el-form label-width="90px" class="login-form" @submit.prevent="onAccountLogin">
        <el-form-item label="用户名">
          <el-input v-model="username" placeholder="请输入用户名" @keyup.enter="onAccountLogin" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="password"
            show-password
            type="password"
            placeholder="请输入密码"
            @keyup.enter="onAccountLogin"
          />
        </el-form-item>
        <el-form-item>
          <el-button :loading="accountLoading" type="primary" @click="onAccountLogin">登录</el-button>
          <el-button :loading="meLoading" @click="loadMe">查询当前登录</el-button>
          <el-button v-if="isLoggedIn" @click="onLogout">退出登录</el-button>
        </el-form-item>
      </el-form>

      <el-alert
        v-if="meText"
        :title="meText"
        type="success"
        show-icon
        :closable="false"
        class="status-alert"
      />
      <el-alert
        title="默认管理员：admin / admin123（首次启动自动创建，密码至少 8 位；可通过 BOOTSTRAP_ADMIN_USERNAME / BOOTSTRAP_ADMIN_PASSWORD 修改）"
        type="info"
        :closable="false"
        class="hint-alert"
      />

      <div class="platform-section">
        <div class="section-title">平台登录（抖音 / 小红书 / 快手）</div>
        <p class="section-subtitle">
          平台「已登录」表示 Cookie 文件存在；若浏览器 Profile 与 Cookie 不同步，或 Cookie 已过期，页面仍可能弹出登录框。
          遇到此情况请先<strong>清除登录记录</strong>，再重新扫码登录。
          也可点击 <strong>打开浏览器</strong> 在本机 Chrome 完成登录或排查登录态。
        </p>

        <div class="platform-toolbar">
          <span class="platform-meta">
            租户 <strong>{{ tenantId }}</strong> · 账号 <strong>{{ activeAccountId }}</strong>
          </span>
          <el-button size="small" :loading="bindingsLoading" @click="loadPlatformBindings">刷新状态</el-button>
        </div>

        <el-table v-loading="bindingsLoading" :data="platformBindings" stripe size="small" class="platform-table">
          <el-table-column prop="platform_label" label="平台" width="100" />
          <el-table-column prop="status" label="状态" width="100">
            <template #default="{ row }">
              <el-tag
                size="small"
                :type="row.status === 'ready' ? 'success' : row.status === 'missing' ? 'info' : 'warning'"
              >
                {{ statusLabel(row.status) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="message" label="说明" min-width="200" show-overflow-tooltip />
          <el-table-column label="操作" width="320" fixed="right">
            <template #default="{ row }">
              <el-button
                link
                type="primary"
                size="small"
                @click="openQrLogin(row)"
              >
                {{ qrLoginTarget?.platform === row.platform ? "扫码中" : "扫码登录" }}
              </el-button>
              <el-button
                link
                type="primary"
                size="small"
                :loading="browserLoginLoading === row.platform"
                @click="openBrowserLogin(row)"
              >
                打开浏览器
              </el-button>
              <el-button
                link
                type="danger"
                size="small"
                :disabled="row.status === 'missing'"
                :loading="clearingPlatform === row.platform"
                @click="clearPlatformLogin(row)"
              >
                清除登录记录
              </el-button>
            </template>
          </el-table-column>
        </el-table>

        <PlatformQrLoginPanel
          v-if="qrLoginTarget"
          :account-id="activeAccountId"
          :tenant-id="tenantId"
          :platform="qrLoginTarget.platform"
          :platform-label="qrLoginTarget.platformLabel"
          @close="qrLoginTarget = null"
          @success="onQrLoginSuccess"
          @open-browser-login="openBrowserLoginFromQr"
        />
      </div>
    </section>
</template>

<script setup>
import { onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import PlatformQrLoginPanel from "../components/PlatformQrLoginPanel.vue";
import { usePlatformBrowserLogin } from "../composables/usePlatformBrowserLogin";
import { fetchAuthMe, loginUser, logoutUser } from "../api/auth";
import {
  clearAccountPlatformLoginSession,
  createAccount,
  fetchAccountBindings,
  fetchAccounts,
} from "../api/accounts";
import { getAccessToken, getTenantId, setPlatformId } from "../api/http";

const route = useRoute();
const router = useRouter();

const username = ref("admin");
const password = ref("");
const meText = ref("");
const accountLoading = ref(false);
const meLoading = ref(false);
const isLoggedIn = ref(Boolean(getAccessToken()));
const tenantId = ref(getTenantId());
const activeAccountId = ref("default");
const platformBindings = ref([]);
const bindingsLoading = ref(false);
const qrLoginTarget = ref(null);
const clearingPlatform = ref("");

const { browserLoginLoading, openBrowserLogin } = usePlatformBrowserLogin(() => activeAccountId.value);

function statusLabel(status) {
  return (
    {
      ready: "已登录",
      missing: "未登录",
      incomplete: "不完整",
      error: "错误",
    }[status] || status
  );
}

async function ensureDefaultAccount() {
  try {
    const data = await fetchAccounts();
    if (data.items?.length) {
      activeAccountId.value = data.active_account_id || data.items[0].id;
      return;
    }
    await createAccount("default", "默认账号");
    activeAccountId.value = "default";
  } catch {
    activeAccountId.value = "default";
  }
}

async function loadPlatformBindings() {
  bindingsLoading.value = true;
  try {
    await ensureDefaultAccount();
    const data = await fetchAccountBindings(activeAccountId.value);
    platformBindings.value = data.platforms || [];
  } catch (err) {
    platformBindings.value = [];
    ElMessage.error(err?.message || "加载平台登录状态失败");
  } finally {
    bindingsLoading.value = false;
  }
}

function openQrLogin(row) {
  qrLoginTarget.value = {
    platform: row.platform,
    platformLabel: row.platform_label,
  };
}

function openBrowserLoginFromQr() {
  if (!qrLoginTarget.value) return;
  openBrowserLogin(
    {
      platform: qrLoginTarget.value.platform,
      platform_label: qrLoginTarget.value.platformLabel,
    },
    { restore: false },
  );
}

function redirectAfterAuth() {
  const target = typeof route.query.redirect === "string" ? route.query.redirect.trim() : "";
  if (target && target.startsWith("/") && !target.startsWith("//")) {
    router.push(target);
    return true;
  }
  return false;
}

async function onQrLoginSuccess(data) {
  const platform = data?.platform || qrLoginTarget.value?.platform;
  ElMessage.success("平台登录成功");
  await loadPlatformBindings();
  qrLoginTarget.value = null;
  if (platform) {
    setPlatformId(platform);
  }
  if (redirectAfterAuth()) return;
  if (route.query.from === "agent") {
    router.push("/agent");
  }
}

async function clearPlatformLogin(row) {
  try {
    await ElMessageBox.confirm(
      `将删除 ${row.platform_label} 的 Cookie 文件与浏览器 Profile，解决「已登录仍弹登录框」问题。清除后需重新扫码登录，是否继续？`,
      "清除登录记录",
      { type: "warning", confirmButtonText: "清除", cancelButtonText: "取消" }
    );
  } catch {
    return;
  }
  clearingPlatform.value = row.platform;
  try {
    await clearAccountPlatformLoginSession(activeAccountId.value, row.platform);
    ElMessage.success(`${row.platform_label} 登录记录已清除，请重新扫码登录`);
    if (qrLoginTarget.value?.platform === row.platform) {
      qrLoginTarget.value = null;
    }
    await loadPlatformBindings();
  } catch (err) {
    ElMessage.error(err?.message || "清除失败");
  } finally {
    clearingPlatform.value = "";
  }
}

async function onAccountLogin() {
  if (!username.value || !password.value) {
    ElMessage.warning("请先输入用户名和密码");
    return;
  }
  accountLoading.value = true;
  try {
    const data = await loginUser(username.value, password.value);
    isLoggedIn.value = true;
    tenantId.value = data.tenant?.id || data.user?.tenant_id || getTenantId();
    ElMessage.success(`登录成功：${data.user?.username || username.value}`);
    meText.value = `当前用户：${data.user?.username || "-"}，租户：${tenantId.value}`;
    await loadPlatformBindings();
    if (redirectAfterAuth()) return;
  } catch (err) {
    meText.value = "";
    isLoggedIn.value = false;
    ElMessage.error(err?.message || "登录失败");
  } finally {
    accountLoading.value = false;
  }
}

async function loadMe() {
  if (!getAccessToken()) {
    meText.value = "";
    isLoggedIn.value = false;
    ElMessage.warning("当前未登录，请先输入账号密码登录");
    return;
  }
  meLoading.value = true;
  try {
    const data = await fetchAuthMe();
    isLoggedIn.value = true;
    tenantId.value = data.tenant?.id || data.user?.tenant_id || getTenantId();
    meText.value = `当前用户：${data.user?.username || "-"}，租户：${tenantId.value}`;
    await loadPlatformBindings();
  } catch (err) {
    meText.value = "";
    isLoggedIn.value = false;
    ElMessage.error(err?.message || "查询失败，请重新登录");
  } finally {
    meLoading.value = false;
  }
}

function onLogout() {
  logoutUser();
  isLoggedIn.value = false;
  meText.value = "";
  platformBindings.value = [];
  qrLoginTarget.value = null;
  ElMessage.success("已退出登录");
}

onMounted(async () => {
  if (getAccessToken()) {
    await loadMe();
    if (redirectAfterAuth()) return;
  } else {
    await loadPlatformBindings();
  }
});

</script>

<style scoped>
.login-page {
  padding: 18px;
}

.page-title {
  font-size: 22px;
  font-weight: 700;
  margin-bottom: 8px;
}

.page-subtitle {
  margin: 0 0 16px;
  color: var(--muted);
  font-size: 14px;
}

.login-form {
  max-width: 520px;
}

.status-alert,
.hint-alert {
  max-width: 720px;
  margin-top: 12px;
}

.platform-section {
  margin-top: 28px;
  max-width: 900px;
  padding-top: 20px;
  border-top: 1px solid var(--el-border-color-lighter, #ebeef5);
}

.section-title {
  font-size: 18px;
  font-weight: 600;
  margin-bottom: 8px;
}

.section-subtitle {
  margin: 0 0 14px;
  color: var(--muted);
  font-size: 13px;
  line-height: 1.6;
}

.platform-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.platform-meta {
  font-size: 13px;
  color: #6b7280;
}

.platform-table {
  width: 100%;
}
</style>
