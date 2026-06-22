import localService from "./localService";

const BASE = "/api/plugin-lab";

/**
 * 插件实验室 API — 与 Chrome 插件通信，逐步调试浏览器自动化能力。
 * 后端路由尚未实现时，界面会显示连接/404 错误，便于联调。
 */
export async function fetchPluginLabStatus() {
  const { data } = await localService.get(`${BASE}/status`);
  return data;
}

export async function checkPluginLabReadiness(actionId) {
  const { data } = await localService.get(`${BASE}/actions/${actionId}/readiness`, {
    timeout: 10000,
  });
  return data;
}

export async function fetchPluginLabSnapshot() {
  const { data } = await localService.get(`${BASE}/snapshot`, { timeout: 10000 });
  return data;
}

export async function runPluginLabAction(actionId, payload = {}) {
  const timeoutMs = actionId === "open_browser" ? 25000 : 120000;
  const { data } = await localService.post(`${BASE}/actions/${actionId}`, payload, {
    timeout: timeoutMs,
  });
  return data;
}

/** 各平台实验室默认参数（打开页面后可直接单步/串联测试） */
export const PLATFORM_LAB_DEFAULTS = {
  douyin: {
    searchText: "创业",
    filterOption: "一天内",
    replyText: "感谢分享，很有启发",
    dmText: "你好，想进一步了解一下",
    videoIndex: 1,
    commentIndex: 1,
    scrollRounds: 4,
    maxComments: 20,
    scrollDistance: 800,
  },
  xiaohongshu: {
    searchText: "护肤",
    filterOption: "",
    replyText: "写得很好，收藏了",
    dmText: "",
    videoIndex: 1,
    commentIndex: 1,
    scrollRounds: 4,
    maxComments: 20,
    scrollDistance: 800,
  },
  kuaishou: {
    searchText: "美食",
    filterOption: "",
    replyText: "视频拍得不错",
    dmText: "",
    videoIndex: 1,
    commentIndex: 1,
    scrollRounds: 4,
    maxComments: 20,
    scrollDistance: 800,
  },
};

export const DM_UNSUPPORTED_PLATFORMS = new Set(["xiaohongshu", "kuaishou"]);
export const FILTER_UNSUPPORTED_PLATFORMS = new Set(["xiaohongshu", "kuaishou"]);

const DM_ACTION_IDS = new Set(["click_dm_btn", "input_dm_text", "send_dm"]);
const FILTER_ACTION_IDS = new Set(["click_filter_btn", "click_filter_overlay"]);

export function applyPlatformLabDefaults(platform, target = {}) {
  const defaults = PLATFORM_LAB_DEFAULTS[platform] || PLATFORM_LAB_DEFAULTS.douyin;
  return {
    platform,
    reuseExisting: target.reuseExisting ?? true,
    waitPageLoad: target.waitPageLoad ?? false,
    scrollDirection: target.scrollDirection ?? "down",
    searchText: target.searchText ?? defaults.searchText,
    filterOption: target.filterOption ?? defaults.filterOption,
    replyText: target.replyText ?? defaults.replyText,
    dmText: target.dmText ?? defaults.dmText,
    videoIndex: target.videoIndex ?? defaults.videoIndex,
    commentIndex: target.commentIndex ?? defaults.commentIndex,
    scrollRounds: target.scrollRounds ?? defaults.scrollRounds,
    maxComments: target.maxComments ?? defaults.maxComments,
    scrollDistance: target.scrollDistance ?? defaults.scrollDistance,
  };
}

export function getActionSkipReason(actionId, platform) {
  if (DM_UNSUPPORTED_PLATFORMS.has(platform) && DM_ACTION_IDS.has(actionId)) {
    return platform === "xiaohongshu" ? "小红书不支持私信" : "快手不支持私信";
  }
  if (FILTER_UNSUPPORTED_PLATFORMS.has(platform) && FILTER_ACTION_IDS.has(actionId)) {
    return platform === "xiaohongshu" ? "小红书暂无筛选" : "快手暂无筛选";
  }
  return null;
}

export function isActionRunnableOnPlatform(action, platform) {
  return !getActionSkipReason(action.id, platform);
}

/** 就绪检测：逐步调用 preflight，不执行实际操作 */
export async function runLabReadinessBatch(platform, actions = PLUGIN_LAB_ACTIONS, onProgress) {
  const results = [];
  for (const action of actions) {
    const skipReason = getActionSkipReason(action.id, platform);
    if (skipReason) {
      const row = {
        actionId: action.id,
        label: action.label,
        status: "skipped",
        message: skipReason,
      };
      results.push(row);
      onProgress?.(row, results);
      continue;
    }
    try {
      const resp = await checkPluginLabReadiness(action.id);
      const body = resp?.data ?? resp;
      const ok = Boolean(resp?.ok ?? body?.can_execute);
      const row = {
        actionId: action.id,
        label: action.label,
        status: ok ? "ready" : "not_ready",
        message: resp?.error || resp?.message || body?.message || (ok ? "可执行" : "当前界面不可执行"),
      };
      results.push(row);
      onProgress?.(row, results);
    } catch (err) {
      const row = {
        actionId: action.id,
        label: action.label,
        status: "error",
        message: err?.response?.data?.error || err?.message || "检测失败",
      };
      results.push(row);
      onProgress?.(row, results);
    }
  }
  return results;
}

/** 串联执行：按步骤顺序实际调用（需已连接插件且步骤 1 已打开对应平台页） */
export const AUTO_FLOW_ACTION_IDS = [
  "open_browser",
  "swipe_page",
  "find_search_box",
  "input_search_text",
  "click_search_btn",
  "fetch_search_results",
  "click_search_video",
  "click_comment_btn",
  "scroll_and_collect_comments",
  "close_video_detail",
];

export async function runLabAutoFlow(platform, buildPayload, actions = PLUGIN_LAB_ACTIONS, onProgress) {
  const actionMap = new Map(actions.map((item) => [item.id, item]));
  const results = [];

  for (const actionId of AUTO_FLOW_ACTION_IDS) {
    const action = actionMap.get(actionId);
    if (!action) continue;

    const skipReason = getActionSkipReason(actionId, platform);
    if (skipReason) {
      const row = { actionId, label: action.label, status: "skipped", message: skipReason };
      results.push(row);
      onProgress?.(row, results);
      continue;
    }

    try {
      const payload = buildPayload(action);
      const data = await runPluginLabAction(actionId, payload);
      const body = data?.data ?? data;
      const ok = body?.ok !== false && data?.ok !== false;
      const row = {
        actionId,
        label: action.label,
        status: ok ? "pass" : "fail",
        message: body?.message || data?.message || data?.error || (ok ? "成功" : "失败"),
        data: body,
      };
      results.push(row);
      onProgress?.(row, results);
      if (!ok) break;
    } catch (err) {
      const row = {
        actionId,
        label: action.label,
        status: "error",
        message: err?.response?.data?.error || err?.message || "执行失败",
      };
      results.push(row);
      onProgress?.(row, results);
      break;
    }
  }

  return results;
}

export const KNOWN_FILTER_OPTIONS = [
  "综合排序",
  "最新发布",
  "最多点赞",
  "一天内",
  "一周内",
  "半年内",
  "1分钟以下",
  "1-5分钟",
  "5分钟以上",
  "关注的人",
  "最近看过",
  "还未看过",
];

export const PLUGIN_LAB_ACTIONS = [
  { id: "open_browser", label: "1. 打开浏览器", description: "在屏幕左侧半屏新建独立 Chrome 窗口（非日常浏览器标签）" },
  { id: "swipe_page", label: "2. 界面滑动", description: "模拟触摸板/滚轮分段滚动页面" },
  { id: "find_search_box", label: "3. 找到搜索框", description: "定位并聚焦顶部搜索输入框" },
  { id: "click_filter_btn", label: "4. 点击筛选按钮", description: "点击「筛选」打开浮层（不抓取浮层内容）" },
  { id: "click_filter_overlay", label: "5. 点击筛选浮层按钮", description: "在 dialog 内按文案精确点击选项", needsFilterOption: true },
  { id: "input_search_text", label: "6. 输入搜索文本", description: "逐字模拟键盘输入搜索关键词", needsSearchText: true },
  { id: "click_search_btn", label: "7. 点击搜索", description: "触发搜索并进入搜索结果页（不截获数据，无 CDP）", returnsData: true },
  { id: "fetch_search_results", label: "8. 获取搜索结果", description: "hook 截获 search 接口，失败再从 DOM 抓取（无 CDP）", returnsData: true },
  { id: "click_search_video", label: "9. 点击搜索结果视频", description: "优先打开搜索 Feed 浮层（modal_id/CDP/DOM），失败再开独立窗", needsVideoIndex: true },
  { id: "click_comment_btn", label: "10. 点击评论按钮", description: "打开视频评论区" },
  {
    id: "scroll_and_collect_comments",
    label: "11. 滑动浏览并抓取评论",
    description: "模拟人类滑动评论列表并采集可见评论",
    returnsData: true,
  },
  {
    id: "reply_comment",
    label: "12. 回复评论",
    description: "点击回复按钮并在输入框输入回复",
    needsReplyText: true,
  },
  { id: "send_comment", label: "13. 发送评论", description: "点击评论发送按钮" },
  { id: "click_comment_avatar", label: "14. 点击评论用户头像", description: "进入评论用户主页" },
  { id: "click_follow_btn", label: "15. 点击关注", description: "在个人主页点击关注按钮" },
  { id: "click_dm_btn", label: "16. 点击私信", description: "打开私信对话框" },
  { id: "input_dm_text", label: "17. 输入私信文本", description: "在私信输入框输入内容", needsDmText: true },
  { id: "send_dm", label: "18. 发送私信", description: "点击私信发送按钮" },
  { id: "close_video_detail", label: "19. 关闭视频详情", description: "关闭视频详情界面" },
];
