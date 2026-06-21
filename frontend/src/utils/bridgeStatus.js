/** 统一解析 local-service / Tauri 返回的插件连接数 */
export function resolveBridgeClientCount(bridgeStatus = {}, extensionSetup = {}) {
  const fromApi = Number(
    bridgeStatus.extension_clients ??
      bridgeStatus.extensionClients ??
      bridgeStatus.connected_clients ??
      bridgeStatus.connectedClients ??
      0,
  );
  if (fromApi > 0) return fromApi;

  const fromTauri = Number(extensionSetup.connectedClients ?? extensionSetup.connected_clients ?? 0);
  if (fromTauri > 0) return fromTauri;

  if (extensionSetup.bridgeConnected || extensionSetup.bridge_connected) return 1;
  return 0;
}

export function bridgeConnectedLabel(count, { checking = false, known = true } = {}) {
  if (checking) return "检测中…";
  if (!known) return "状态未知";
  if (count > 0) return `插件已连接 (${count})`;
  return "插件未连接";
}

export function bridgeConnectedTagType(count, { checking = false, known = true } = {}) {
  if (checking || !known) return "info";
  return count > 0 ? "success" : "warning";
}
