import { getAccessToken } from "../api/http";
import { isPortalAuthenticated } from "../portal";
import { loadCollectJobForModal } from "../utils/extensionCollectJobs";
import { listCloudLeadTasks, listCloudLeads } from "./api";
import {
  buildAgentJobFromCloudCollectJob,
  cloudTaskToCollectJobRow,
  isAutoCloudTask,
  isDesktopCloudTask,
  isManualCloudTask,
} from "./mappers";

const MAX_TASK_PAGES = 20;
const MAX_LEAD_PAGES = 100;
const PAGE_SIZE = 50;

function localCloudLinkKeys(localJobs) {
  const cloudTaskIds = new Set();
  const localJobIds = new Set();
  for (const job of localJobs || []) {
    if (job?.id) localJobIds.add(String(job.id));
    const desktop = job?.config?.huoke_desktop;
    if (desktop?.cloud_task_id) cloudTaskIds.add(String(desktop.cloud_task_id));
  }
  return { cloudTaskIds, localJobIds };
}

function shouldSkipCloudTask(task, { cloudTaskIds, localJobIds }) {
  const cloudId = String(task?.id || "");
  if (cloudTaskIds.has(cloudId)) return true;
  const linkedLocalId = String(task?.config?.huoke_desktop?.local_job_id || "").trim();
  if (linkedLocalId && localJobIds.has(linkedLocalId)) return true;
  return false;
}

export async function fetchAllCloudDesktopTasks() {
  const tasks = [];
  for (let page = 1; page <= MAX_TASK_PAGES; page += 1) {
    const data = await listCloudLeadTasks({ page, size: PAGE_SIZE });
    const items = Array.isArray(data?.items) ? data.items : [];
    for (const task of items) {
      if (isDesktopCloudTask(task)) tasks.push(task);
    }
    const total = Number(data?.total ?? items.length);
    if (page * PAGE_SIZE >= total || items.length < PAGE_SIZE) break;
  }
  return tasks;
}

export function mergeLocalAndCloudJobs(localJobs, cloudTasks, { cloudTaskFilter } = {}) {
  const links = localCloudLinkKeys(localJobs);
  const merged = [...(localJobs || [])];
  let cloudOnlyCount = 0;

  for (const task of cloudTasks || []) {
    if (cloudTaskFilter && !cloudTaskFilter(task)) continue;
    if (shouldSkipCloudTask(task, links)) continue;
    merged.push(cloudTaskToCollectJobRow(task));
    cloudOnlyCount += 1;
  }

  merged.sort((a, b) => {
    const aTs = Number(a.created_at || 0);
    const bTs = Number(b.created_at || 0);
    return bTs - aTs;
  });

  return { merged, cloudOnlyCount };
}

export function detectRecoveryState(localJobs, cloudOnlyCount, { error = "" } = {}) {
  const localCount = Array.isArray(localJobs) ? localJobs.length : 0;
  return {
    showBanner: localCount === 0 && cloudOnlyCount > 0,
    cloudOnlyCount,
    error: String(error || "").trim(),
    needsLogin: !getAccessToken() && localCount === 0,
  };
}

export async function loadCloudRecoveryJobs(localJobs, { cloudTaskFilter } = {}) {
  const token = getAccessToken();
  if (!token) {
    return {
      merged: localJobs || [],
      recovery: detectRecoveryState(localJobs, 0, {
        error: isPortalAuthenticated()
          ? "云端登录态未同步，请退出后重新登录"
          : "请先登录云端账号以恢复历史任务",
      }),
    };
  }
  try {
    const cloudTasks = await fetchAllCloudDesktopTasks();
    const { merged, cloudOnlyCount } = mergeLocalAndCloudJobs(localJobs, cloudTasks, {
      cloudTaskFilter,
    });
    return {
      merged,
      recovery: detectRecoveryState(localJobs, cloudOnlyCount),
    };
  } catch (err) {
    const message = err?.response?.data?.message
      || err?.response?.data?.detail
      || err?.message
      || "拉取云端任务失败";
    return {
      merged: localJobs || [],
      recovery: detectRecoveryState(localJobs, 0, { error: message }),
    };
  }
}

async function fetchAllCloudLeads(taskId) {
  const leads = [];
  for (let page = 1; page <= MAX_LEAD_PAGES; page += 1) {
    const data = await listCloudLeads({
      task_id: taskId,
      page,
      size: PAGE_SIZE,
      include_raw: 1,
    });
    const items = Array.isArray(data?.items) ? data.items : [];
    leads.push(...items);
    const total = Number(data?.total ?? items.length);
    if (page * PAGE_SIZE >= total || items.length < PAGE_SIZE) break;
  }
  return leads;
}

export async function loadCloudTaskForModal(collectJobRow) {
  const cloudTaskId = collectJobRow?.cloud_task_id
    || String(collectJobRow?.id || "").replace(/^cloud:/, "");
  if (!cloudTaskId) {
    throw new Error("cloud_task_id_missing");
  }
  const leads = await fetchAllCloudLeads(cloudTaskId);
  return buildAgentJobFromCloudCollectJob(collectJobRow, leads);
}

export async function loadTaskForModal(collectJobRow) {
  if (collectJobRow?._cloud_only) {
    return loadCloudTaskForModal(collectJobRow);
  }
  return loadCollectJobForModal(collectJobRow);
}

export { isAutoCloudTask, isManualCloudTask };
