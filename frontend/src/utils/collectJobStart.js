export function collectJobStartMessage(status) {
  if (status === "running") {
    return "正在停止当前采集并从完整搜索重新开始，请稍候…";
  }
  if (status === "failed") {
    return "正在接续上次进度继续采集，请稍候…";
  }
  if (status === "paused" || status === "completed") {
    return "正在接续上次进度继续采集，请稍候…";
  }
  return "正在启动采集，请稍候…";
}

export function collectJobStartSuccessMessage(status) {
  if (status === "running") {
    return "已重新启动采集（完整搜索），请保持抖音标签页激活";
  }
  if (status === "failed" || status === "paused" || status === "completed") {
    return "已接续采集，请保持抖音标签页激活";
  }
  return "采集已开始，请保持抖音标签页激活";
}
