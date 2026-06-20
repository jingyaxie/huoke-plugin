import { ref } from "vue";
import { ElMessage } from "element-plus";
import { triggerAccountPlatformLogin } from "../api/accounts";

/** 本机 Sidecar：server-login 弹出 Chrome，不再走 noVNC。 */
export function usePlatformBrowserLogin(getAccountId) {
  const browserLoginLoading = ref("");

  function resolveAccountId() {
    if (typeof getAccountId === "function") {
      return getAccountId();
    }
    return getAccountId?.value || getAccountId || "default";
  }

  async function openBrowserLogin(row, { restore = false } = {}) {
    if (!row?.platform) return;
    browserLoginLoading.value = row.platform;
    try {
      const data = await triggerAccountPlatformLogin(resolveAccountId(), row.platform, { restore });
      ElMessage.success(
        data.message || "已打开本机浏览器窗口，请在弹出的 Chrome 完成登录",
      );
    } catch (err) {
      ElMessage.error(err?.message || "打开浏览器登录失败");
    } finally {
      browserLoginLoading.value = "";
    }
  }

  return {
    browserLoginLoading,
    openBrowserLogin,
  };
}
