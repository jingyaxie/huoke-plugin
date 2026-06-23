import { ElMessage } from "element-plus";
import { normalizeExternalUrl } from "./douyinLinks";
import { isTauriApp } from "./desktopApp";

async function invokeOpenExternalUrl(url) {
  if (typeof window.__TAURI__?.core?.invoke === "function") {
    return window.__TAURI__.core.invoke("open_external_url", { url });
  }
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke("open_external_url", { url });
}

export async function openExternalLink(url) {
  const normalized = normalizeExternalUrl(url);
  if (!normalized) return { ok: false, reason: "invalid" };

  if (isTauriApp()) {
    try {
      await invokeOpenExternalUrl(normalized);
      return { ok: true };
    } catch (err) {
      console.warn("open_external_url failed:", err);
      return { ok: false, reason: "desktop" };
    }
  }

  const opened = window.open(normalized, "_blank", "noopener,noreferrer");
  if (opened) return { ok: true };

  const anchor = document.createElement("a");
  anchor.href = normalized;
  anchor.target = "_blank";
  anchor.rel = "noopener noreferrer";
  anchor.style.display = "none";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  return { ok: true };
}

export async function openExternalLinkWithHint(url) {
  const result = await openExternalLink(url);
  if (result.ok) return true;

  if (result.reason === "desktop") {
    ElMessage.warning("无法打开链接，请更新到最新版桌面客户端后重试");
    return false;
  }

  ElMessage.warning("链接无效，无法打开");
  return false;
}
