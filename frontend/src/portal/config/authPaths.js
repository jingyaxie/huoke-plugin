/** 启用 portal 时需登录才能访问的本地 AI 获客路由（与 LOCAL_NAV_SECTION 保持一致） */
export const LOCAL_ACQUISITION_PATHS = [
  "/extension-bridge",
  "/manual-tasks",
  "/presets",
  "/platform-login",
  "/auto-tasks",
];

export function isLocalAcquisitionPath(path) {
  const normalized = String(path || "").trim();
  return LOCAL_ACQUISITION_PATHS.some(
    (prefix) => normalized === prefix || normalized.startsWith(`${prefix}/`),
  );
}
