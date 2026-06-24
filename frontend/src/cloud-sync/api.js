import http from "../api/http";
import localService from "../api/localService";

const CONFIG_KEY = "huoke_desktop";

function unwrapResponse(payload) {
  if (payload && typeof payload === "object" && payload.data !== undefined) {
    return payload.data;
  }
  return payload;
}

export function mapCollectJobToLeadTaskType(jobType, intent) {
  if (jobType === "manual") {
    return intent === "single_video" ? "video_manual" : "home_manual";
  }
  return "home_auto";
}

export async function registerCloudTask({
  localJobId,
  platform,
  taskType,
  name,
  keyword,
  inputUrl,
  regionCode,
  regionName,
  commentDays,
  publishTimeRange,
  targetCount,
  evaluation,
  interaction,
  commentPresets,
  dmPresets,
}) {
  const config = {
    keywords: keyword ? [keyword] : [],
    keyword,
    input_url: inputUrl || undefined,
    region_code: regionCode || undefined,
    region_name: regionName || undefined,
    region: regionName || undefined,
    comment_days: commentDays,
    publish_time_range: publishTimeRange || "unlimited",
    target_count: targetCount,
    interaction: interaction || {},
    comment_presets: commentPresets || [],
    dm_presets: dmPresets || [],
    evaluation: evaluation || undefined,
  };
  const payload = {
    type: taskType,
    platform,
    name,
    local_job_id: localJobId,
    input_url: inputUrl || undefined,
    region_code: regionCode || undefined,
    region_name: regionName || undefined,
    config,
  };
  const { data } = await http.post("/cloud-sync/tasks", payload, {
    headers: { "X-Client-Type": "pc" },
  });
  return unwrapResponse(data);
}

export async function linkLocalJobCloud(jobId, cloudTaskId) {
  const { data } = await localService.post(`/api/cloud-sync/jobs/${jobId}/link`, {
    cloud_task_id: cloudTaskId,
  });
  return data;
}

export async function listCloudLeadTasks(params = {}) {
  const { data } = await http.get("/lead-tasks", { params });
  return unwrapResponse(data);
}

export async function listCloudLeads(params = {}) {
  const { data } = await http.get("/leads", { params });
  return unwrapResponse(data);
}

export { CONFIG_KEY };
