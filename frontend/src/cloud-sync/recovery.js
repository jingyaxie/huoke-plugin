import { getAccessToken } from "../api/http";
import { clearAccessToken, isTokenExpiredError } from "../api/token";
import { isPortalAuthenticated } from "../portal";
import { refreshAccessTokenFromPortalSession } from "../portal/utils/portalLoginBridge";
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

export function cloudTaskLocalJobId(task) {
  const desktop = task?.config?.huoke_desktop;
  if (desktop && typeof desktop === "object") {
    const linked = String(desktop.local_job_id || "").trim();
    if (linked) return linked;
  }
  return String(task?.local_job_id || task?.huoke_local_job_id || "").trim();
}

function shouldSkipCloudTask(task, { cloudTaskIds, localJobIds }) {
  const cloudId = String(task?.id || "");
  if (cloudTaskIds.has(cloudId)) return true;
  const linkedLocalId = cloudTaskLocalJobId(task);
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

export function detectRecoveryState(localJobs, cloudOnlyCount, { error = "", cloudDesktopTotal = 0 } = {}) {
  const localCount = Array.isArray(localJobs) ? localJobs.length : 0;
  const hasToken = Boolean(String(getAccessToken() || "").trim());
  return {
    showBanner: localCount === 0 && cloudOnlyCount > 0,
    showEmptyHint: localCount === 0 && cloudOnlyCount === 0 && !error && hasToken,
    cloudOnlyCount,
    cloudDesktopTotal,
    error: String(error || "").trim(),
    needsLogin: !hasToken && localCount === 0,
  };
}

function formatRecoveryError(err) {
  const raw = String(
    err?.response?.data?.message
      || err?.response?.data?.detail
      || err?.message
      || "拉取云端任务失败",
  ).trim();
  if (isTokenExpiredError(err) || raw.toLowerCase().includes("token_expired")) {
    return "登录已过期，请重新登录盈小蚁账号后刷新本页";
  }
  return raw;
}

async function ensureCloudAccessToken() {
  let token = String(getAccessToken() || "").trim();
  if (token) return token;
  if (!isPortalAuthenticated()) return "";
  return refreshAccessTokenFromPortalSession();
}

async function fetchCloudRecoveryWithRetry(localJobs, { cloudTaskFilter } = {}) {
  try {
    const cloudTasks = await fetchAllCloudDesktopTasks();
    const { merged, cloudOnlyCount } = mergeLocalAndCloudJobs(localJobs, cloudTasks, { cloudTaskFilter });
    return { merged, cloudOnlyCount, cloudDesktopTotal: cloudTasks.length };
  } catch (err) {
    if (!isTokenExpiredError(err)) throw err;
    clearAccessToken();
    const refreshed = await refreshAccessTokenFromPortalSession();
    if (!refreshed) throw err;
    const cloudTasks = await fetchAllCloudDesktopTasks();
    const { merged, cloudOnlyCount } = mergeLocalAndCloudJobs(localJobs, cloudTasks, { cloudTaskFilter });
    return { merged, cloudOnlyCount, cloudDesktopTotal: cloudTasks.length };
  }
}

export async function loadCloudRecoveryJobs(localJobs, { cloudTaskFilter } = {}) {
  const localCount = Array.isArray(localJobs) ? localJobs.length : 0;

  // 本机有任务时只展示本地列表；云端镜像仅作数据备份，不在列表重复出现。
  // 仅在本机无任务（重装/清库）时才从云端恢复只读历史。
  if (localCount > 0) {
    return {
      merged: localJobs || [],
      recovery: detectRecoveryState(localJobs, 0),
    };
  }

  let token = await ensureCloudAccessToken();
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
    const { merged, cloudOnlyCount, cloudDesktopTotal } = await fetchCloudRecoveryWithRetry(localJobs, {
      cloudTaskFilter,
    });
    return {
      merged,
      recovery: detectRecoveryState(localJobs, cloudOnlyCount, { cloudDesktopTotal }),
    };
  } catch (err) {
    return {
      merged: localJobs || [],
      recovery: detectRecoveryState(localJobs, 0, { error: formatRecoveryError(err) }),
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
