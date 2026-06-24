import axios from "axios";

const DEFAULT_BASE = "http://127.0.0.1:18766";

export function getLocalServiceBaseUrl() {
  return import.meta.env.VITE_LOCAL_SERVICE_URL || DEFAULT_BASE;
}

const localService = axios.create({
  timeout: 45000,
});

localService.interceptors.request.use((config) => {
  config.baseURL = getLocalServiceBaseUrl();
  return config;
});

export async function fetchBridgeHealth() {
  const { data } = await localService.get("/health");
  return data;
}

/** 非阻塞：重新初始化 local-service 与插件运行环境（Hub、僵尸任务、插件会话） */
export function initRuntimeEnv() {
  return localService.post("/api/runtime/init", null, { timeout: 10000 });
}

export async function fetchBridgeStatus() {
  const { data } = await localService.get("/bridge/status");
  return data;
}

/** 通知 Chrome 插件执行 chrome.runtime.reload()（须插件 Background 仍在线） */
export async function reloadChromeExtension() {
  const { data } = await localService.post("/bridge/command", {
    action: "huoke.extension.reload",
    payload: {},
    wait: true,
    timeout_ms: 10000,
  });
  if (data.error) {
    throw new Error(data.error);
  }
  return data.result ?? data;
}

/** Reload 后轮询 bridge，直到插件重新连上 local-service */
export async function waitForBridgeReconnect(maxAttempts = 24, intervalMs = 500) {
  for (let i = 0; i < maxAttempts; i += 1) {
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
    try {
      const status = await fetchBridgeStatus();
      if (Number(status.connected_clients || status.extension_clients || 0) > 0) {
        return status;
      }
    } catch {
      // extension reconnecting
    }
  }
  throw new Error(
    "插件重载后未在预期时间内重新连接，请到 chrome://extensions 手动重新加载 Huoke 扩展",
  );
}

export async function fetchReplyQuota() {
  const { data } = await localService.get("/api/douyin/quota");
  return data;
}

export async function fetchCollectCapabilities() {
  const { data } = await localService.get("/api/collect/capabilities");
  return data;
}

export async function evaluateCollectJob(jobId) {
  const { data } = await localService.post(`/api/douyin/jobs/${jobId}/evaluate`);
  return data;
}

export async function listCollectJobs() {
  const { data } = await localService.get("/api/douyin/jobs");
  return data;
}

export async function createCollectJob(payload) {
  const { data } = await localService.post("/api/douyin/jobs", payload);
  return data;
}

export async function startCollectJob(jobId) {
  const { data } = await localService.post(`/api/douyin/jobs/${jobId}/start`);
  return data;
}

export async function pauseCollectJob(jobId) {
  const { data } = await localService.post(`/api/douyin/jobs/${jobId}/pause`);
  return data;
}

export async function getCollectJob(jobId) {
  const { data } = await localService.get(`/api/douyin/jobs/${jobId}`);
  return data;
}

export async function listCollectVideos(jobId) {
  const { data } = await localService.get(`/api/douyin/jobs/${jobId}/videos`);
  return data;
}

export async function listCollectComments(jobId, params = {}) {
  const { data } = await localService.get(`/api/douyin/jobs/${jobId}/comments`, { params });
  return data;
}

export async function listCollectInteractions(jobId, params = {}) {
  const { data } = await localService.get(`/api/douyin/jobs/${jobId}/interactions`, { params });
  return data;
}

/** 兼容未重启的旧 local-service（尚无 interactions 路由） */
export async function listCollectInteractionsOptional(jobId, params = {}) {
  try {
    return await listCollectInteractions(jobId, params);
  } catch (err) {
    if (err?.response?.status === 404) {
      return { job_id: jobId, interactions: [] };
    }
    throw err;
  }
}

export async function deleteCollectJob(jobId) {
  const { data } = await localService.post(`/api/douyin/jobs/${jobId}/delete`);
  return data;
}

export async function listOutreachTasks() {
  const { data } = await localService.get("/api/douyin/outreach/tasks");
  return data;
}

export async function createOutreachTask(payload) {
  const { data } = await localService.post("/api/douyin/outreach/tasks", payload);
  return data;
}

export async function startOutreachTask(taskId) {
  const { data } = await localService.post(`/api/douyin/outreach/tasks/${taskId}/start`);
  return data;
}

export async function pauseOutreachTask(taskId) {
  const { data } = await localService.post(`/api/douyin/outreach/tasks/${taskId}/pause`);
  return data;
}

export async function listOutreachItems(taskId, params = {}) {
  const { data } = await localService.get(`/api/douyin/outreach/tasks/${taskId}/items`, { params });
  return data;
}

export async function replyOnce(payload) {
  const { data } = await localService.post("/api/douyin/reply", payload);
  return data;
}

export default localService;
