import http from "./http";

const LONG_TIMEOUT = 120000;

export function executeSkill(payload) {
  const timeoutMs = payload.timeout_seconds
    ? Math.min(payload.timeout_seconds * 1000 + 5000, 3600000)
    : LONG_TIMEOUT;
  return http.post("/agent/skills/execute", payload, { timeout: timeoutMs });
}

export function listSkills() {
  return http.get("/agent/skills");
}

export function listBuiltinHandlers() {
  return http.get("/agent/skills/builtin-handlers");
}
