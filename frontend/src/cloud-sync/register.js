import { getAccessToken } from "../api/http";
import { linkLocalJobCloud, mapCollectJobToLeadTaskType, registerCloudTask } from "./api";

/**
 * 本地 collect_job 创建成功后，可选注册云端任务并建立关联。
 * 云端失败不阻塞本地流程。
 */
export async function registerCollectJobToCloud({
  localJob,
  jobType,
  intent,
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
  if (!getAccessToken() || !localJob?.id) {
    return { linked: false, reason: "not_logged_in" };
  }
  try {
    const cloudTask = await registerCloudTask({
      localJobId: localJob.id,
      platform: localJob.platform,
      taskType: mapCollectJobToLeadTaskType(jobType, intent),
      name: localJob.name,
      keyword: keyword || localJob.keyword,
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
    });
    const cloudTaskId = cloudTask?.id;
    if (!cloudTaskId) {
      return { linked: false, reason: "missing_cloud_task_id" };
    }
    await linkLocalJobCloud(localJob.id, cloudTaskId);
    return { linked: true, cloudTaskId, cloudTask };
  } catch (err) {
    return {
      linked: false,
      reason: "cloud_create_failed",
      error: err?.response?.data?.message || err?.message || String(err),
    };
  }
}
