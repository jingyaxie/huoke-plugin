import { getLocalServiceBaseUrl } from "./localService";

function llmSettingsUrl() {
  return `${getLocalServiceBaseUrl()}/api/settings/llm`;
}

async function readLlmError(resp, fallback) {
  const text = await resp.text().catch(() => "");
  if (text) {
    try {
      const parsed = JSON.parse(text);
      if (parsed.detail) return String(parsed.detail);
      if (parsed.error) return String(parsed.error);
      if (parsed.message) return String(parsed.message);
    } catch {
      return text.trim() || fallback;
    }
  }
  if (resp.status === 404) {
    return "local-service 未提供模型配置接口，请重启 local-service（npm run dev 或重新编译 cargo run）";
  }
  if (resp.status === 0 || resp.type === "error") {
    return `无法连接 local-service（${getLocalServiceBaseUrl()}），请确认服务已启动`;
  }
  return `${fallback}（HTTP ${resp.status}）`;
}

export async function fetchLlmSettings() {
  let resp;
  try {
    resp = await fetch(llmSettingsUrl());
  } catch {
    throw new Error(`无法连接 local-service（${getLocalServiceBaseUrl()}），请确认服务已启动`);
  }
  if (!resp.ok) {
    throw new Error(await readLlmError(resp, "读取模型设置失败"));
  }
  return resp.json();
}

export async function saveLlmSettings(payload) {
  let resp;
  try {
    resp = await fetch(llmSettingsUrl(), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch {
    throw new Error(`无法连接 local-service（${getLocalServiceBaseUrl()}），请确认服务已启动`);
  }
  if (!resp.ok) {
    throw new Error(await readLlmError(resp, "保存模型设置失败"));
  }
  return resp.json();
}
