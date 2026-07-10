import { OUTREACH_UI_ENABLED } from "../../config/features";

/** 启用 portal 时需登录才能访问的本地 AI 获客路由（与 LOCAL_NAV_SECTION 保持一致） */
export const LOCAL_ACQUISITION_PATHS = [
  "/extension-bridge",
  "/manual-tasks",
  ...(OUTREACH_UI_ENABLED ? ["/presets", "/outreach-tasks"] : []),
  "/platform-login",
  "/auto-tasks",
];

export function isLocalAcquisitionPath(path) {
  const normalized = String(path || "").trim();
  return LOCAL_ACQUISITION_PATHS.some(
    (prefix) => normalized === prefix || normalized.startsWith(`${prefix}/`),
  );
}
