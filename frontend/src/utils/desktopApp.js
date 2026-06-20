export async function isDesktopMode() {
  try {
    const response = await fetch("/api/health");
    if (!response.ok) return false;
    const payload = await response.json();
    return Boolean(payload?.desktop_mode);
  } catch {
    return false;
  }
}

export async function restartDesktopApp() {
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    await invoke("restart_desktop_app");
    return true;
  } catch {
    return false;
  }
}

export function saveBlobDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.style.display = "none";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
