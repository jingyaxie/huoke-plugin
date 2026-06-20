export function extensionVersion(): string {
  try {
    const getManifest = chrome.runtime?.getManifest;
    if (typeof getManifest !== "function") return "unknown";
    const manifestVersion = getManifest.call(chrome.runtime).version ?? "unknown";
    const buildId = typeof __HUOKE_BUILD_ID__ === "string" ? __HUOKE_BUILD_ID__ : "dev";
    return `${manifestVersion}+${buildId}`;
  } catch {
    return "unknown";
  }
}

export function hasExtensionRuntime(): boolean {
  return typeof chrome.runtime?.id === "string";
}
