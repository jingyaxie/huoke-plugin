import { getAccountId, getPlatformId, getTenantId, setTenantId } from "./http";
import {
  fetchAccountPlatformLoginStatus,
  triggerAccountPlatformLogin,
} from "./accounts";

export { getTenantId, setTenantId };

export function fetchLoginStatus() {
  return fetchAccountPlatformLoginStatus(getAccountId(), getPlatformId());
}

export function triggerServerLogin() {
  return triggerAccountPlatformLogin(getAccountId(), getPlatformId());
}
