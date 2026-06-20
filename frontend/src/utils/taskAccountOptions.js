import { fetchAccountBindings, fetchAccounts } from "../api/accounts";
import { getTenantId } from "../api/http";

export async function loadTaskAccountOptions(platform) {
  const data = await fetchAccounts();
  const options = [];
  for (const account of data.items || []) {
    let bindings;
    try {
      bindings = await fetchAccountBindings(account.id);
    } catch {
      continue;
    }
    const binding = (bindings.platforms || []).find((row) => row.platform === platform);
    if (!binding) continue;
    const nickname = String(binding.nickname || account.label || account.id).trim();
    options.push({
      key: `${account.id}:${platform}`,
      label: binding.cookie_ready ? nickname : `${nickname}（待登录）`,
      platform,
      cookieReady: !!binding.cookie_ready,
      isBound: true,
      huokeTenantId: getTenantId(),
      huokeAccountId: account.id,
      platformUserId: binding.platform_user_id || undefined,
      accountLabel: nickname,
    });
  }
  return options;
}

export function taskAccountOptionToBindingRef(option) {
  if (!option?.isBound) return undefined;
  return {
    huoke_tenant_id: option.huokeTenantId,
    huoke_account_id: option.huokeAccountId,
    platform_user_id: option.platformUserId,
    account_label: option.accountLabel || option.label,
  };
}
