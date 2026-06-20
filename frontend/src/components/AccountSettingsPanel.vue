<template>
  <section class="account-settings-panel panel">
    <AccountHealthAlerts
      :issues="healthIssues"
      :resolving-key="resolvingKey"
      @resolve="resolveHealthIssue"
    />

    <el-table v-loading="loading" :data="pageRows" size="default" class="account-table" style="width: 100%">
      <el-table-column label="账号名称" min-width="200">
        <template #default="{ row }">
          <div class="name-cell">
            <div class="name-row">
              <span class="nickname">{{ row.nickname }}</span>
              <el-tag
                v-if="findIssue(row)"
                size="small"
                :type="findIssue(row).severity === 'error' ? 'danger' : 'warning'"
                class="issue-tag"
                @click="resolveHealthIssue(findIssue(row))"
              >
                {{ issueBadgeLabel(findIssue(row)) }}
              </el-tag>
              <el-tag v-else-if="!row.is_bound" size="small" type="info">未绑定</el-tag>
            </div>
            <p v-if="findIssue(row)" class="issue-message">{{ findIssue(row).message }}</p>
          </div>
        </template>
      </el-table-column>

      <el-table-column label="头像" width="80" align="center">
        <template #default="{ row }">
          <el-avatar :size="32" :src="row.avatar_url || undefined">
            {{ avatarInitial(row.nickname) }}
          </el-avatar>
        </template>
      </el-table-column>

      <el-table-column label="渠道" width="110">
        <template #default="{ row }">
          <PlatformChannelTag :platform="row.platform" />
        </template>
      </el-table-column>

      <el-table-column label="授权延时时间" width="170">
        <template #default="{ row }">
          {{ row.is_bound ? formatAuthExpires(row.auth_expires_at) : "—" }}
        </template>
      </el-table-column>

      <el-table-column label="操作" min-width="360">
        <template #default="{ row }">
          <div class="action-row">
            <template v-if="findIssue(row)">
              <el-button link type="primary" size="small" :disabled="actingKey === row.key" @click="resolveHealthIssue(findIssue(row))">
                重新登录
              </el-button>
              <span class="action-sep">|</span>
            </template>
            <el-button
              link
              type="primary"
              size="small"
              :disabled="!row.is_bound || actingKey === row.key"
              :loading="actingKey === row.key && actingAction === 'pull'"
              @click="handlePull(row)"
            >
              拉取会话
            </el-button>
            <span class="action-sep">|</span>
            <el-button
              link
              type="success"
              size="small"
              :disabled="!row.is_bound || monitorEnabled(row) || actingKey === row.key"
              @click="toggleMonitor(row, true)"
            >
              开启监听
            </el-button>
            <span class="action-sep">|</span>
            <el-button
              link
              type="danger"
              size="small"
              :disabled="!row.is_bound || !monitorEnabled(row) || actingKey === row.key"
              @click="toggleMonitor(row, false)"
            >
              关闭监听
            </el-button>
            <span class="action-sep">|</span>
            <el-button
              link
              type="danger"
              size="small"
              :disabled="!row.is_bound || actingKey === row.key"
              :loading="actingKey === row.key && actingAction === 'delete'"
              @click="handleDelete(row)"
            >
              删除
            </el-button>
          </div>
        </template>
      </el-table-column>

      <template #empty>
        <div class="empty-text">
          {{ loading ? "加载中…" : "暂无授权账号，请点击右上角「+ 授权账号」绑定" }}
        </div>
      </template>
    </el-table>

    <div v-if="error" class="error-bar">{{ error }}</div>

    <div v-if="rows.length > 0" class="pagination-row">
      <el-pagination
        v-model:current-page="page"
        :page-size="pageSize"
        :total="rows.length"
        layout="total, prev, pager, next"
        background
        small
      />
    </div>

    <el-collapse v-if="showAdvanced" class="advanced-collapse">
      <el-collapse-item title="高级：多账号管理" name="multi-account">
        <p class="hint-text">
          当前租户：<strong>{{ tenantId }}</strong> · 活跃账号 <strong>{{ activeAccountId }}</strong>
        </p>
        <div class="field-block">
          <label class="field-label">切换活跃账号</label>
          <el-select v-model="activeAccountId" style="width: 100%; max-width: 420px" @change="onAccountChange">
            <el-option v-for="item in accounts" :key="item.id" :label="item.label" :value="item.id" />
          </el-select>
        </div>
        <div class="toolbar-row">
          <el-input v-model="newAccountId" size="default" placeholder="账号 ID" style="width: 160px" />
          <el-input v-model="newAccountLabel" size="default" placeholder="显示名称" style="width: 160px" />
          <el-button type="primary" :loading="accountCreating" @click="createAccountEntry">新建账号</el-button>
        </div>
      </el-collapse-item>
    </el-collapse>

    <AuthorizeAccountModal
      v-model="authorizeOpen"
      :account-id="activeAccountId"
      :health-issues="healthIssues"
      :resolving-key="resolvingKey"
      @bound="load"
      @resolve-health="resolveHealthIssue"
    />
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import AccountHealthAlerts from "./AccountHealthAlerts.vue";
import AuthorizeAccountModal from "./AuthorizeAccountModal.vue";
import PlatformChannelTag from "./PlatformChannelTag.vue";
import {
  clearAccountPlatformLoginSession,
  enrichRowsWithAuthExpiry,
  loadAllAccountBindingSnapshots,
  triggerAccountPlatformLogin,
} from "../api/accounts";
import { getTenantId } from "../api/http";
import { useAgentAccounts } from "../composables/useAgentAccounts";
import { setPlatformMonitorEnabled } from "../utils/accountMonitorPreference";
import {
  avatarInitial,
  buildAccountSettingsRows,
  collectAccountHealthIssues,
  findHealthIssueForRow,
  formatAuthExpires,
  isPlatformMonitorEnabled,
  issueBadgeLabel,
  PLATFORM_LABEL,
} from "../utils/accountSettings";
import { pullPlatformSession } from "../utils/platformBindFlow";

defineProps({
  showAdvanced: { type: Boolean, default: true },
});

const REFRESH_INTERVAL_MS = 30_000;
const pageSize = 5;

const tenantId = ref(getTenantId());
const { accounts, activeAccountId, loadAccounts, switchAccount, createNewAccountEntry } = useAgentAccounts();

const rows = ref([]);
const snapshots = ref([]);
const loading = ref(true);
const error = ref("");
const page = ref(1);
const monitorTick = ref(0);
const actingKey = ref("");
const actingAction = ref("");
const resolvingKey = ref("");
const authorizeOpen = ref(false);
const newAccountId = ref("");
const newAccountLabel = ref("");
const accountCreating = ref(false);

let refreshTimer = null;

const healthIssues = computed(() => collectAccountHealthIssues(snapshots.value));

const pageRows = computed(() => {
  void monitorTick.value;
  const start = (page.value - 1) * pageSize;
  return rows.value.slice(start, start + pageSize);
});

watch(
  () => rows.value.length,
  () => {
    const maxPage = Math.max(1, Math.ceil(rows.value.length / pageSize));
    if (page.value > maxPage) page.value = maxPage;
  },
);

function findIssue(row) {
  return findHealthIssueForRow(healthIssues.value, row);
}

function monitorEnabled(row) {
  return isPlatformMonitorEnabled(row.huoke_account_id, row.platform);
}

function toggleMonitor(row, enabled) {
  setPlatformMonitorEnabled(row.huoke_account_id, row.platform, enabled);
  monitorTick.value += 1;
  ElMessage.success(enabled ? "已开启监听" : "已关闭监听");
}

async function load(opts = {}) {
  if (!opts.silent) loading.value = true;
  try {
    await loadAccounts();
    const data = await loadAllAccountBindingSnapshots();
    snapshots.value = data.snapshots;
    const displayRows = buildAccountSettingsRows(data.snapshots);
    rows.value = await enrichRowsWithAuthExpiry(displayRows);
    error.value = "";
  } catch (e) {
    error.value = e?.message || "加载账号失败";
  } finally {
    if (!opts.silent) loading.value = false;
  }
}

async function onAccountChange(accountId) {
  const ok = await switchAccount(accountId);
  if (!ok) {
    activeAccountId.value = accounts.value.find((a) => a.id)?.id || activeAccountId.value;
  }
}

async function createAccountEntry() {
  const id = newAccountId.value.trim();
  const label = newAccountLabel.value.trim();
  if (!id || !label) {
    ElMessage.warning("请填写账号 ID 和名称");
    return;
  }
  accountCreating.value = true;
  try {
    await createNewAccountEntry(id, label);
    newAccountId.value = "";
    newAccountLabel.value = "";
    await load();
  } catch (err) {
    ElMessage.error(err.message || "创建失败");
  } finally {
    accountCreating.value = false;
  }
}

async function handlePull(row) {
  actingKey.value = row.key;
  actingAction.value = "pull";
  try {
    await pullPlatformSession(row.huoke_account_id, row.platform);
    ElMessage.success("会话已拉取并同步");
    await load();
  } catch (e) {
    ElMessage.error(e?.message || "拉取会话失败");
  } finally {
    actingKey.value = "";
    actingAction.value = "";
  }
}

async function handleDelete(row) {
  const label = PLATFORM_LABEL[row.platform] || row.platform;
  try {
    await ElMessageBox.confirm(`确定删除 ${label} 账号「${row.nickname}」的本机授权？`, "删除授权", {
      type: "warning",
      confirmButtonText: "删除",
      cancelButtonText: "取消",
    });
  } catch {
    return;
  }
  actingKey.value = row.key;
  actingAction.value = "delete";
  try {
    setPlatformMonitorEnabled(row.huoke_account_id, row.platform, false);
    await clearAccountPlatformLoginSession(row.huoke_account_id, row.platform);
    ElMessage.success("授权已删除");
    await load();
  } catch (e) {
    ElMessage.error(e?.message || "删除失败");
  } finally {
    actingKey.value = "";
    actingAction.value = "";
  }
}

async function resolveHealthIssue(issue) {
  if (!issue) return;
  resolvingKey.value = issue.issueKey;
  try {
    const accountId = issue.issueKey.split(":")[0];
    await triggerAccountPlatformLogin(accountId, issue.platform, { restore: false });
    ElMessage.success("已打开本机 Chrome，请完成登录后返回此页刷新");
    await load();
  } catch (e) {
    ElMessage.error(e?.message || "处理失败");
  } finally {
    resolvingKey.value = "";
  }
}

function openAuthorize() {
  authorizeOpen.value = true;
}

defineExpose({ load, openAuthorize });

onMounted(() => {
  load();
  refreshTimer = setInterval(() => load({ silent: true }), REFRESH_INTERVAL_MS);
});

onBeforeUnmount(() => {
  if (refreshTimer) clearInterval(refreshTimer);
});
</script>

<style scoped>
.account-settings-panel {
  padding: 20px 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.account-table :deep(.el-table__header th) {
  background: #f8fafc;
  color: #64748b;
  font-size: 13px;
  font-weight: 500;
}

.account-table :deep(.el-table__row td) {
  font-size: 13px;
}

.name-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.name-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.nickname {
  font-weight: 500;
}

.issue-tag {
  cursor: pointer;
}

.issue-message {
  margin: 0;
  font-size: 12px;
  color: #6b7280;
  max-width: 360px;
}

.action-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
}

.action-sep {
  color: #e5e7eb;
  user-select: none;
}

.empty-text {
  padding: 40px 0;
  color: #9ca3af;
  text-align: center;
}

.error-bar {
  border-top: 1px solid #fecaca;
  background: #fef2f2;
  color: #b91c1c;
  padding: 10px 16px;
  font-size: 12px;
}

.pagination-row {
  display: flex;
  justify-content: flex-end;
  padding-top: 4px;
}

.advanced-collapse {
  margin-top: 8px;
}

.hint-text {
  margin: 0 0 12px;
  font-size: 13px;
  color: #6b7280;
}

.field-block {
  margin-bottom: 12px;
}

.field-label {
  display: block;
  margin-bottom: 6px;
  font-size: 13px;
}

.toolbar-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}
</style>
