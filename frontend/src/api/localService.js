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

export async function fetchBridgeStatus() {
  const { data } = await localService.get("/bridge/status");
  return data;
}

export async function fetchReplyQuota() {
  const { data } = await localService.get("/api/douyin/quota");
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
