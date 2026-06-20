import { getAccountId, getApiKey, getAccessToken, getPlatformId, getTenantId, getApiBaseUrl, getWsApiBaseUrl } from "./http";
import http from "./http";

const baseURL = getApiBaseUrl();

function agentHeaders() {
  const headers = {
    "Content-Type": "application/json",
    "X-Tenant-Id": getTenantId(),
    "X-Platform-Id": getPlatformId(),
    "X-Account-Id": getAccountId(),
  };
  const apiKey = getApiKey();
  if (apiKey) {
    headers["X-API-Key"] = apiKey;
  }
  const token = getAccessToken();
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  return headers;
}

export async function fetchAgentConfig() {
  const resp = await fetch(`${baseURL}/agent/config`, { headers: agentHeaders() });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || "获取 Agent 配置失败");
  }
  return resp.json();
}

/** 预检当前租户/账号/平台是否已绑定登录态 */
export async function fetchAgentBindingStatus() {
  const resp = await fetch(`${baseURL}/agent/bindings/status`, { headers: agentHeaders() });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || "获取绑定状态失败");
  }
  return resp.json();
}

export async function createAgentSession(headless = null) {
  const body = {};
  if (headless !== null) body.headless = headless;
  const resp = await fetch(`${baseURL}/agent/sessions`, {
    method: "POST",
    headers: agentHeaders(),
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || `创建会话失败 (${resp.status})`);
  }
  return resp.json();
}

export async function closeAgentSession(sessionId) {
  const resp = await fetch(`${baseURL}/agent/sessions/${sessionId}`, {
    method: "DELETE",
    headers: agentHeaders(),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || `关闭会话失败 (${resp.status})`);
  }
  return resp.json();
}

export async function fetchSkills() {
  const resp = await fetch(`${baseURL}/agent/skills`, { headers: agentHeaders() });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || `获取技能失败 (${resp.status})`);
  }
  return resp.json();
}

export async function fetchSkillEffects() {
  const resp = await fetch(`${baseURL}/agent/skills/effects`, { headers: agentHeaders() });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || "获取技能评分失败");
  }
  return resp.json();
}

export async function fetchSkillEffectDetail(skillId, limit = 30) {
  const resp = await fetch(`${baseURL}/agent/skills/${skillId}/effect?limit=${limit}`, {
    headers: agentHeaders(),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || "获取技能效果详情失败");
  }
  return resp.json();
}

export async function fetchBuiltinHandlers() {
  const resp = await fetch(`${baseURL}/agent/skills/builtin-handlers`, { headers: agentHeaders() });
  if (!resp.ok) throw new Error("获取内置处理器失败");
  return resp.json();
}

export async function createSkill(payload) {
  const resp = await fetch(`${baseURL}/agent/skills`, {
    method: "POST",
    headers: agentHeaders(),
    body: JSON.stringify(payload),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || `创建技能失败 (${resp.status})`);
  }
  return resp.json();
}

export async function updateSkill(skillId, payload) {
  const resp = await fetch(`${baseURL}/agent/skills/${skillId}`, {
    method: "PUT",
    headers: agentHeaders(),
    body: JSON.stringify(payload),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || `更新技能失败 (${resp.status})`);
  }
  return resp.json();
}

export async function deleteSkill(skillId) {
  const resp = await fetch(`${baseURL}/agent/skills/${skillId}`, {
    method: "DELETE",
    headers: agentHeaders(),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || `删除技能失败 (${resp.status})`);
  }
  return resp.json();
}

export async function exportSkillsJson(ids = null) {
  const query = ids?.length ? `?ids=${ids.join(",")}` : "";
  const resp = await fetch(`${baseURL}/agent/skills/export${query}`, { headers: agentHeaders() });
  if (!resp.ok) throw new Error("导出失败");
  return resp.json();
}

export function skillMarkdownDownloadUrl(skillId) {
  return `${baseURL}/agent/skills/${skillId}/export.md`;
}

export function skillJsonDownloadUrl(skillId) {
  return `${baseURL}/agent/skills/${skillId}/export.json`;
}

export async function importSkillsJson(skills, overwrite = false) {
  const resp = await fetch(`${baseURL}/agent/skills/import/json`, {
    method: "POST",
    headers: agentHeaders(),
    body: JSON.stringify({ skills, overwrite }),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || "导入失败");
  }
  return resp.json();
}

export async function importSkillMarkdown(content, overwrite = false) {
  const resp = await fetch(`${baseURL}/agent/skills/import/markdown`, {
    method: "POST",
    headers: agentHeaders(),
    body: JSON.stringify({ content, overwrite }),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || "导入 SKILL.md 失败");
  }
  return resp.json();
}

export async function parseSkillMarkdown(content) {
  const resp = await fetch(`${baseURL}/agent/skills/parse-markdown`, {
    method: "POST",
    headers: agentHeaders(),
    body: JSON.stringify({ content }),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || "解析 SKILL.md 失败");
  }
  return resp.json();
}

export async function recordSkillFromSteps(payload) {
  const resp = await fetch(`${baseURL}/agent/skills/record-from-steps`, {
    method: "POST",
    headers: agentHeaders(),
    body: JSON.stringify(payload),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || "录制技能失败");
  }
  return resp.json();
}

export async function fetchSkillHubConfig() {
  const resp = await fetch(`${baseURL}/agent/skills/hub/config`, { headers: agentHeaders() });
  if (!resp.ok) throw new Error("加载 SkillHub 配置失败");
  return resp.json();
}

export async function updateSkillHubConfig(payload) {
  const resp = await fetch(`${baseURL}/agent/skills/hub/config`, {
    method: "PUT",
    headers: agentHeaders(),
    body: JSON.stringify(payload),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || "保存 SkillHub 配置失败");
  }
  return resp.json();
}

export async function searchSkillHub(query, limit = 20) {
  const params = new URLSearchParams({ q: query, limit: String(limit) });
  const resp = await fetch(`${baseURL}/agent/skills/hub/search?${params}`, {
    headers: agentHeaders(),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || "搜索 SkillHub 失败");
  }
  return resp.json();
}

export async function installSkillHub(payload) {
  const resp = await fetch(`${baseURL}/agent/skills/hub/install`, {
    method: "POST",
    headers: agentHeaders(),
    body: JSON.stringify(payload),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || "安装技能失败");
  }
  return resp.json();
}

export async function installSkillHubZip(file, overwrite = false) {
  const form = new FormData();
  form.append("file", file);
  const headers = agentHeaders();
  delete headers["Content-Type"];
  const resp = await fetch(
    `${baseURL}/agent/skills/hub/install-zip?overwrite=${overwrite ? "true" : "false"}`,
    { method: "POST", headers, body: form }
  );
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || "上传安装失败");
  }
  return resp.json();
}

export async function fetchSkillHubInstalled() {
  const resp = await fetch(`${baseURL}/agent/skills/hub/installed`, { headers: agentHeaders() });
  if (!resp.ok) throw new Error("加载已安装 SkillHub 技能失败");
  return resp.json();
}

export async function uninstallSkillHub(slug) {
  const resp = await fetch(`${baseURL}/agent/skills/hub/installed/${slug}`, {
    method: "DELETE",
    headers: agentHeaders(),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || "卸载失败");
  }
  return resp.json();
}

export async function downloadWithAuth(url, filename) {
  const resp = await fetch(url, { headers: agentHeaders() });
  if (!resp.ok) throw new Error("下载失败");
  const blob = await resp.blob();
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  link.click();
  URL.revokeObjectURL(link.href);
}

export async function fetchAgentRuns(limit = 50) {
  const resp = await fetch(`${baseURL}/agent/runs?limit=${limit}`, { headers: agentHeaders() });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || "获取对话历史失败");
  }
  return resp.json();
}

export async function fetchAgentRun(runId) {
  const resp = await fetch(`${baseURL}/agent/runs/${runId}`, { headers: agentHeaders() });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || `获取对话历史失败 (${resp.status})`);
  }
  return resp.json();
}

export async function deleteAgentRun(runId) {
  const resp = await fetch(`${baseURL}/agent/runs/${runId}`, {
    method: "DELETE",
    headers: agentHeaders(),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || `删除对话失败 (${resp.status})`);
  }
  return resp.json();
}

/** 同步 Agent 对话（阻塞至完成或超时，适合 API 测试） */
export async function syncAgentChat(payload) {
  const timeoutMs = Math.min((payload.timeout_seconds || 600) * 1000 + 10000, 3600000);
  const resp = await http.post("/agent/chat/sync", payload, { timeout: timeoutMs });
  return resp.data;
}

/**
 * 发送消息并通过 SSE 接收智能体事件流
 * @param {object} params
 * @param {string} params.message
 * @param {string|null} params.sessionId
 * @param {string} params.provider
 * @param {boolean|null} params.headless
 * @param {(event: object) => void} params.onEvent
 * @param {AbortSignal} [params.signal]
 */
export async function streamAgentChat({
  message,
  sessionId,
  runId,
  provider,
  headless,
  mode,
  runMode,
  agentProfileId,
  onEvent,
  signal,
}) {
  const body = { message, provider, mode: mode || "agent", run_mode: runMode || "auto" };
  if (sessionId) body.session_id = sessionId;
  if (runId) body.run_id = runId;
  if (agentProfileId) body.agent_profile_id = agentProfileId;
  if (headless !== null && headless !== undefined) body.headless = headless;

  return streamAgentEvents(`${baseURL}/agent/chat`, body, onEvent, signal);
}

async function streamAgentEvents(url, body, onEvent, signal) {
  const resp = await fetch(url, {
    method: "POST",
    headers: agentHeaders(),
    body: JSON.stringify(body),
    signal,
  });

  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || `请求失败 (${resp.status})`);
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let gotTerminal = false;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() || "";
    for (const part of parts) {
      const line = part.trim();
      if (!line.startsWith("data: ")) continue;
      try {
        const event = JSON.parse(line.slice(6));
        onEvent(event);
        if (event.type === "done" || event.type === "cancelled") {
          gotTerminal = true;
        }
      } catch {
        // ignore
      }
    }
  }

  if (!gotTerminal) {
    throw new Error("连接中断，任务进度已保存，可继续执行");
  }
}

export function resumeAgentRun(runId, onEvent, signal) {
  return streamAgentEvents(
    `${baseURL}/agent/resume/run`,
    { run_id: runId },
    onEvent,
    signal,
  );
}

export function resumeApproval(runId, approved, onEvent, signal) {
  return streamAgentEvents(
    `${baseURL}/agent/resume/approval`,
    { run_id: runId, approved },
    onEvent,
    signal,
  );
}

export function resumePlan(runId, approved, onEvent, signal) {
  return streamAgentEvents(
    `${baseURL}/agent/resume/plan`,
    { run_id: runId, approved },
    onEvent,
    signal,
  );
}

export async function fetchRules() {
  const resp = await fetch(`${baseURL}/agent/rules`, { headers: agentHeaders() });
  if (!resp.ok) throw new Error("获取规则失败");
  return resp.json();
}

export async function createRule(payload) {
  const resp = await fetch(`${baseURL}/agent/rules`, {
    method: "POST",
    headers: agentHeaders(),
    body: JSON.stringify(payload),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || "创建规则失败");
  }
  return resp.json();
}

export async function updateRule(ruleId, payload) {
  const resp = await fetch(`${baseURL}/agent/rules/${ruleId}`, {
    method: "PUT",
    headers: agentHeaders(),
    body: JSON.stringify(payload),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || "更新规则失败");
  }
  return resp.json();
}

export async function deleteRule(ruleId) {
  const resp = await fetch(`${baseURL}/agent/rules/${ruleId}`, {
    method: "DELETE",
    headers: agentHeaders(),
  });
  if (!resp.ok) throw new Error("删除规则失败");
  return resp.json();
}

export async function fetchAgentProfiles() {
  const resp = await fetch(`${baseURL}/agent/profiles`, { headers: agentHeaders() });
  if (!resp.ok) throw new Error("获取 Agent 档案失败");
  return resp.json();
}

export async function createAgentProfile(payload) {
  const resp = await fetch(`${baseURL}/agent/profiles`, {
    method: "POST",
    headers: agentHeaders(),
    body: JSON.stringify(payload),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || "创建 Agent 档案失败");
  }
  return resp.json();
}

export async function updateAgentProfile(profileId, payload) {
  const resp = await fetch(`${baseURL}/agent/profiles/${profileId}`, {
    method: "PUT",
    headers: agentHeaders(),
    body: JSON.stringify(payload),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || "更新 Agent 档案失败");
  }
  return resp.json();
}

export async function deleteAgentProfile(profileId) {
  const resp = await fetch(`${baseURL}/agent/profiles/${profileId}`, {
    method: "DELETE",
    headers: agentHeaders(),
  });
  if (!resp.ok) throw new Error("删除 Agent 档案失败");
  return resp.json();
}

export async function cancelAgentRun(runId) {
  const resp = await fetch(`${baseURL}/agent/runs/${runId}/cancel`, {
    method: "POST",
    headers: agentHeaders(),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || "停止失败");
  }
  return resp.json();
}

export async function fetchCheckpoints(runId) {
  const resp = await fetch(`${baseURL}/agent/runs/${runId}/checkpoints`, {
    headers: agentHeaders(),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || "获取检查点失败");
  }
  return resp.json();
}

export async function restoreCheckpoint(runId, checkpointId) {
  const resp = await fetch(`${baseURL}/agent/runs/${runId}/checkpoints/restore`, {
    method: "POST",
    headers: agentHeaders(),
    body: JSON.stringify({ checkpoint_id: checkpointId }),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || "恢复检查点失败");
  }
  return resp.json();
}

function wsUrl() {
  const tenant = getTenantId();
  const platform = getPlatformId();
  const params = new URLSearchParams({
    tenant_id: tenant,
    platform,
    account_id: getAccountId(),
  });
  const apiKey = getApiKey();
  if (apiKey) {
    params.set("api_key", apiKey);
  }
  const token = getAccessToken();
  if (token) {
    params.set("token", token);
  }
  const root = getWsApiBaseUrl();
  return `${root}/agent/ws?${params.toString()}`;
}

/**
 * 创建 Agent WebSocket 连接（双向：聊天、取消、审批）
 */
export function createAgentWebSocket({ onEvent, onOpen, onClose, onError } = {}) {
  const ws = new WebSocket(wsUrl());
  ws.onopen = () => onOpen?.();
  ws.onclose = () => onClose?.();
  ws.onerror = (err) => onError?.(err);
  ws.onmessage = (evt) => {
    try {
      onEvent?.(JSON.parse(evt.data));
    } catch {
      // ignore
    }
  };
  return ws;
}

export function sendAgentWsMessage(ws, type, payload) {
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    throw new Error("WebSocket 未连接");
  }
  ws.send(JSON.stringify({ type, payload }));
}

export async function fetchExperiences() {
  const resp = await fetch(`${baseURL}/agent/experiences`, { headers: agentHeaders() });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || "获取经验库失败");
  }
  return resp.json();
}

export async function consolidateDreams(limit = 30, useLlm = false) {
  const resp = await fetch(`${baseURL}/agent/dream/consolidate?limit=${limit}`, {
    method: "POST",
    headers: agentHeaders(),
    body: JSON.stringify({ use_llm: useLlm }),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || "做梦整理失败");
  }
  return resp.json();
}

export async function dreamFromRun(runId, useLlm = false) {
  const resp = await fetch(`${baseURL}/agent/dream/runs/${runId}`, {
    method: "POST",
    headers: agentHeaders(),
    body: JSON.stringify({ use_llm: useLlm }),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || "提炼经验失败");
  }
  return resp.json();
}

export async function deleteExperience(experienceId) {
  const resp = await fetch(`${baseURL}/agent/experiences/${experienceId}`, {
    method: "DELETE",
    headers: agentHeaders(),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || "删除经验失败");
  }
  return resp.json();
}

export async function toggleExperienceEnabled(experienceId, enabled) {
  const resp = await fetch(`${baseURL}/agent/experiences/${experienceId}`, {
    method: "PUT",
    headers: agentHeaders(),
    body: JSON.stringify({ enabled }),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || "更新经验失败");
  }
  return resp.json();
}

export async function fetchAgentStrategies(platform = null) {
  const params = platform ? `?platform=${encodeURIComponent(platform)}` : "";
  const resp = await fetch(`${baseURL}/agent/strategies${params}`, { headers: agentHeaders() });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || "获取执行策略失败");
  }
  return resp.json();
}

export async function submitAgentJob(payload) {
  const resp = await fetch(`${baseURL}/agent/jobs`, {
    method: "POST",
    headers: agentHeaders(),
    body: JSON.stringify(payload),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || "提交异步任务失败");
  }
  return resp.json();
}

export async function fetchAgentJob(jobId) {
  const resp = await fetch(`${baseURL}/agent/jobs/${jobId}`, {
    headers: agentHeaders(),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || "获取异步任务失败");
  }
  return resp.json();
}

export async function fetchAgentJobs(limit = 50) {
  const resp = await fetch(`${baseURL}/agent/jobs?limit=${limit}`, {
    headers: agentHeaders(),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || "获取任务队列失败");
  }
  return resp.json();
}

export async function cancelAgentJobTask(jobId) {
  const resp = await fetch(`${baseURL}/agent/jobs/${jobId}/cancel`, {
    method: "POST",
    headers: agentHeaders(),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || "取消异步任务失败");
  }
  return resp.json();
}

export async function pauseAgentJobTask(jobId) {
  const resp = await fetch(`${baseURL}/agent/jobs/${jobId}/pause`, {
    method: "POST",
    headers: agentHeaders(),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || "暂停任务失败");
  }
  return resp.json();
}

export async function executeAgentJob(jobId) {
  const resp = await fetch(`${baseURL}/agent/jobs/${jobId}/execute`, {
    method: "POST",
    headers: agentHeaders(),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || "启动任务失败");
  }
  return resp.json();
}

export async function updateAgentJobConfig(jobId, payload) {
  const resp = await fetch(`${baseURL}/agent/jobs/${jobId}/config`, {
    method: "PATCH",
    headers: agentHeaders(),
    body: JSON.stringify(payload),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || "更新任务配置失败");
  }
  return resp.json();
}

export async function deleteAgentJob(jobId) {
  const headers = agentHeaders();
  let resp = await fetch(`${baseURL}/agent/jobs/${jobId}/delete`, {
    method: "POST",
    headers,
  });
  if (resp.status === 404 || resp.status === 405) {
    resp = await fetch(`${baseURL}/agent/jobs/${jobId}`, {
      method: "DELETE",
      headers,
    });
  }
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || "删除任务失败");
  }
  return resp.json();
}

export async function runAgentBenchmark(cases) {
  const resp = await fetch(`${baseURL}/agent/eval/benchmark`, {
    method: "POST",
    headers: agentHeaders(),
    body: JSON.stringify({ cases }),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || "运行基准评测失败");
  }
  return resp.json();
}
