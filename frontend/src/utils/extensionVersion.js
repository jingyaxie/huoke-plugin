function parseVersionParts(value) {
  if (!value) return [];
  return String(value)
    .split(/[^0-9]+/)
    .filter(Boolean)
    .map((part) => Number(part));
}

export function compareVersions(left, right) {
  const leftParts = parseVersionParts(left);
  const rightParts = parseVersionParts(right);
  const maxLen = Math.max(leftParts.length, rightParts.length);
  for (let i = 0; i < maxLen; i += 1) {
    const lv = leftParts[i] ?? 0;
    const rv = rightParts[i] ?? 0;
    if (lv > rv) return 1;
    if (lv < rv) return -1;
  }
  return 0;
}

export function resolveExtensionVersionStatus(bridgeStatus = {}, extensionSetup = {}) {
  const expected =
    bridgeStatus.expectedExtensionVersion ??
    bridgeStatus.expected_extension_version ??
    extensionSetup.expectedExtensionVersion ??
    extensionSetup.expected_extension_version ??
    "";
  const connected =
    bridgeStatus.connectedExtensionVersion ??
    bridgeStatus.connected_extension_version ??
    extensionSetup.connectedExtensionVersion ??
    extensionSetup.connected_extension_version ??
    "";
  const installed =
    bridgeStatus.installedExtensionVersion ??
    bridgeStatus.installed_extension_version ??
    extensionSetup.installedExtensionVersion ??
    extensionSetup.installed_extension_version ??
    "";
  const appVersion =
    bridgeStatus.appVersion ??
    bridgeStatus.app_version ??
    extensionSetup.appVersion ??
    extensionSetup.app_version ??
    "";

  const matched =
    bridgeStatus.extensionVersionMatched ??
    bridgeStatus.extension_version_matched ??
    extensionSetup.extensionVersionMatched ??
    extensionSetup.extension_version_matched ??
    true;

  const message =
    bridgeStatus.extensionVersionMessage ??
    bridgeStatus.extension_version_message ??
    extensionSetup.extensionVersionMessage ??
    extensionSetup.extension_version_message ??
    "";

  let computedMessage = message;
  let computedMatched = matched;

  if (expected) {
    if (connected) {
      const diff = compareVersions(connected, expected);
      if (diff < 0) {
        computedMatched = false;
        computedMessage = `当前 Chrome 插件 v${connected} 低于 App 要求 v${expected}，请更新插件。`;
      } else if (diff !== 0) {
        computedMatched = false;
        computedMessage = `当前 Chrome 插件 v${connected} 与 App 要求 v${expected} 不一致，请更新插件。`;
      }
    } else if (installed) {
      const diff = compareVersions(installed, expected);
      if (diff !== 0) {
        computedMatched = false;
        computedMessage = `本地插件目录仍为 v${installed}，App 要求 v${expected}，请重启 App 或点击「启动浏览器插件」。`;
      }
    }
  }

  return {
    appVersion,
    expectedExtensionVersion: expected,
    connectedExtensionVersion: connected,
    installedExtensionVersion: installed,
    matched: computedMatched,
    message: computedMatched ? "" : computedMessage,
  };
}
