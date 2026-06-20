import http, { getTenantId } from "./http";

export function fetchGlobalAntibotConfig() {
  return http.get("/antibot/config").then((res) => res.data);
}

export function fetchTenantAntibotConfig(tenantId = getTenantId()) {
  return http.get(`/tenants/${encodeURIComponent(tenantId)}/antibot`).then((res) => res.data);
}

export function fetchEffectiveAntibotConfig() {
  return http.get("/antibot/config/effective").then((res) => res.data);
}

export function saveTenantAntibotOverride(payload, tenantId = getTenantId()) {
  return http
    .put(`/tenants/${encodeURIComponent(tenantId)}/antibot`, payload)
    .then((res) => res.data);
}

export function deleteTenantAntibotOverride(tenantId = getTenantId()) {
  return http.delete(`/tenants/${encodeURIComponent(tenantId)}/antibot`).then((res) => res.data);
}
