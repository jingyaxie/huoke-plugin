import http, { getApiBaseUrl } from "./http";

export function getSwaggerDocsUrl() {
  const base = getApiBaseUrl();
  if (base.startsWith("/")) {
    return `${window.location.origin}/docs`;
  }
  if (base.endsWith("/api")) {
    return base.replace(/\/api$/, "/docs");
  }
  return "http://localhost:8000/docs";
}

export async function checkHealth() {
  const resp = await http.get("/health");
  return resp.data;
}

export async function runKeywordVideoComments(payload) {
  const timeoutMs = payload.async_job
    ? 30000
    : Math.min((payload.timeout_seconds || 1200) * 1000 + 10000, 3600000);
  const resp = await http.post("/agent/pipeline/keyword-video-comments", payload, {
    timeout: timeoutMs,
  });
  return resp.data;
}
