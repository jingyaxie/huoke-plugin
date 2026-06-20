import { computed, ref } from "vue";
import { ElMessage } from "element-plus";
import { createAccount, fetchAccounts, setActiveAccount } from "../api/accounts";
import { getAccountId, setAccountId } from "../api/http";

export function useAgentAccounts() {
  const accounts = ref([]);
  const activeAccountId = ref(getAccountId());

  const activeAccountLabel = computed(() => {
    const row = accounts.value.find((item) => item.id === activeAccountId.value);
    return row?.label || activeAccountId.value || "default";
  });

  async function loadAccounts() {
    try {
      const data = await fetchAccounts();
      accounts.value = data.items || [];
      const active = data.active_account_id || getAccountId();
      activeAccountId.value = active;
      setAccountId(active);
    } catch {
      accounts.value = [];
    }
  }

  async function switchAccount(accountId, { blockIfRunning = false, running = false } = {}) {
    if (blockIfRunning && running) {
      ElMessage.warning("任务运行中，请先停止再切换账号");
      return false;
    }
    try {
      await setActiveAccount(accountId);
      setAccountId(accountId);
      activeAccountId.value = accountId;
      ElMessage.success("已切换账号");
      window.dispatchEvent(new CustomEvent("huoke-account-changed", { detail: accountId }));
      return true;
    } catch (err) {
      ElMessage.error(err.message || "切换账号失败");
      return false;
    }
  }

  async function createNewAccountEntry(id, label) {
    await createAccount(id, label);
    await loadAccounts();
    ElMessage.success("账号已创建");
  }

  return {
    accounts,
    activeAccountId,
    activeAccountLabel,
    loadAccounts,
    switchAccount,
    createNewAccountEntry,
  };
}
