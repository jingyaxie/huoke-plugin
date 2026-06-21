export function extensionVersion(): string {
  try {
    const getManifest = chrome.runtime?.getManifest;
    if (typeof getManifest !== "function") return "unknown";
    return getManifest.call(chrome.runtime).version ?? "unknown";
  } catch {
    return "unknown";
  }
}

export function extensionBuildId(): string {
  return typeof __HUOKE_BUILD_ID__ === "string" ? __HUOKE_BUILD_ID__ : "dev";
}

export function hasExtensionRuntime(): boolean {
  return typeof chrome.runtime?.id === "string";
}
