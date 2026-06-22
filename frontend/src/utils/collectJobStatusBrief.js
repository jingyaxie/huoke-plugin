import { extensionJobTargetCount } from "./extensionCollectJobs";

export function collectJobProgress(row) {
  return Number(row?.precise_count ?? row?.comment_count ?? 0);
}

export function collectJobStatusLabel(status) {
  const map = {
    pending: "待执行",
    running: "运行中",
    completed: "已完成",
    failed: "失败",
    paused: "已暂停",
  };
  return map[status] || status || "—";
}

export function collectJobStatusTagType(status) {
  const map = {
    pending: "info",
    running: "primary",
    completed: "success",
    failed: "danger",
    paused: "warning",
  };
  return map[status] || "info";
}

/** 状态文案可点击查看详情（失败原因 / 后续步骤） */
export function isCollectJobStatusClickable(row) {
  const status = row?.status;
  if (status === "failed") return true;
  if (status === "paused") return true;
  if (status === "running") return true;
  if (String(row?.error_message || "").trim()) return true;
  if (status === "completed") {
    const target = extensionJobTargetCount(row);
    const progress = collectJobProgress(row);
    return target > 0 && progress < target;
  }
  return false;
}

export function getCollectJobStatusBrief(row) {
  const status = row?.status || "";
  const error = String(row?.error_message || "").trim();
  const target = extensionJobTargetCount(row);
  const progress = collectJobProgress(row);
  const precise = Number(row?.precise_count ?? 0);
  const comments = Number(row?.comment_count ?? 0);

  if (status === "failed") {
    return buildFailedBrief(error, { target, progress, precise, comments });
  }
  if (status === "paused") {
    return {
      title: "任务已暂停",
      tone: "warning",
      summary:
        progress > 0
          ? `已采集 ${precise > 0 ? `${precise} 条精准线索` : `${comments} 条评论`}，任务已暂停。`
          : "任务已暂停，尚未产生采集进度。",
      reason: error || "您手动暂停了任务，或运行过程中被中断。",
      next_actions: [
        "点击「继续采集」从当前进度继续",
        "请保持抖音标签页激活，并停留在搜索结果页",
      ],
      can_continue: true,
    };
  }
  if (status === "running") {
    const progressText =
      precise > 0
        ? `精准线索 ${precise}${target > 0 ? ` / 目标 ${target}` : ""}`
        : `评论 ${comments}${target > 0 ? ` / 目标约 ${target}` : ""}`;
    return {
      title: "任务运行中",
      tone: "primary",
      summary: `正在采集，当前 ${progressText}。`,
      reason: "请保持 Chrome 中抖音标签页处于激活状态，勿最小化或关闭浏览器窗口。",
      next_actions: [
        "如需停止，请使用操作菜单中的「暂停」",
        "若长时间无进展，请在 chrome://extensions 重新加载 Huoke 扩展，再点「重新启动采集」",
      ],
      can_continue: false,
    };
  }
  if (status === "completed" && target > 0 && progress < target) {
    return {
      title: "已完成但未达目标",
      tone: "warning",
      summary: `当前 ${progress}/${target} 条精准线索，尚未凑够预设目标。`,
      reason:
        error ||
        "当前批次的视频已全部处理完毕，仍缺线索。可继续采集以加载更多搜索结果。",
      next_actions: [
        "点击「继续采集」滚动搜索页并采集更多视频",
        "或在创建任务时提高「采集视频数」扩大覆盖面",
      ],
      can_continue: true,
    };
  }
  if (error) {
    return buildFailedBrief(error, { target, progress, precise, comments });
  }
  return null;
}

function buildFailedBrief(error, ctx) {
  const { target, progress, precise, comments } = ctx;
  let summary = error;
  let detail = "";
  const dashIdx = error.indexOf(" — ");
  if (dashIdx > 0) {
    summary = error.slice(0, dashIdx).trim();
    detail = error.slice(dashIdx + 3).trim();
  }

  return {
    title: "采集失败",
    tone: "error",
    summary: summary || "任务执行失败",
    reason: detail || summary,
    next_actions: inferNextActions(error, detail),
    can_continue: !/already completed|已全部完成/i.test(error),
    stats: { target, progress, precise, comments },
  };
}

function inferNextActions(error, detail) {
  const text = `${error} ${detail}`.toLowerCase();
  const actions = [];

  if (text.includes("当前视频列表已全部采集") || text.includes("视频列表已全部")) {
    actions.push("点击「继续采集」，系统将滚动搜索页加载更多视频");
    actions.push("创建任务时可提高「采集视频数」，扩大单次搜索覆盖面");
    actions.push("若精准率偏低，可适当降低「精准线索目标」或放宽评估标准");
  } else if (text.includes("未能打开") || text.includes("failed to open")) {
    actions.push("确认 Chrome 中抖音页面停留在搜索结果列表（建议多列布局）");
    actions.push("在 chrome://extensions 重新加载 Huoke 扩展，并刷新抖音页");
    actions.push("点击「继续采集」重试");
  } else if (
    text.includes("message channel closed") ||
    text.includes("content script not responding")
  ) {
    actions.push("在 chrome://extensions 重新加载 Huoke 扩展");
    actions.push("刷新抖音标签页，必要时重新登录");
    actions.push("点击「继续采集」重试");
  } else if (text.includes("command timeout") || text.includes("open_browser")) {
    actions.push("确认页面顶部显示「插件已连接」");
    actions.push("点击「启动浏览器插件」或刷新页面后，再点「继续采集」");
  } else if (text.includes("部分视频采集失败")) {
    actions.push("点击「继续采集」重试未成功的视频");
    actions.push("保持抖音标签页激活，避免切换到其他窗口");
  } else if (text.includes("no comments captured") || text.includes("暂无评论")) {
    actions.push("确认抖音账号已登录，且目标视频下有评论");
    actions.push("检查任务的「评论时间范围」是否过窄");
    actions.push("点击「继续采集」重试");
  } else if (text.includes("search produced no videos")) {
    actions.push("确认抖音已登录且搜索结果页可见");
    actions.push("尝试更换关键词或重新创建任务");
  } else {
    actions.push("点击「继续采集」从当前进度重试");
    actions.push("若反复失败，请在 chrome://extensions 重新加载 Huoke 扩展");
  }

  return actions;
}
