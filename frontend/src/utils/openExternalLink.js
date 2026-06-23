import { ElMessage } from "element-plus";
import { normalizeExternalUrl } from "./douyinLinks";
import { isTauriApp } from "./desktopApp";

export async function openExternalLink(url) {
  const normalized = normalizeExternalUrl(url);
  if (!normalized) return false;

  if (isTauriApp()) {
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      await invoke("open_external_url", { url: normalized });
      return true;
    } catch {
      // Older desktop builds may not expose the command yet.
    }
  }

  const opened = window.open(normalized, "_blank", "noopener,noreferrer");
  if (opened) return true;

  const anchor = document.createElement("a");
  anchor.href = normalized;
  anchor.target = "_blank";
  anchor.rel = "noopener noreferrer";
  anchor.style.display = "none";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  return true;
}

export async function openExternalLinkWithHint(url) {
  const ok = await openExternalLink(url);
  if (!ok) {
    ElMessage.warning("链接无效，无法打开");
    return false;
  }
  return true;
}
