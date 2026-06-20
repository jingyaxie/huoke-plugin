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

export async function runPluginLabAction(actionId, payload = {}) {
  const { data } = await localService.post(`${BASE}/actions/${actionId}`, payload, {
    timeout: 120000,
  });
  return data;
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
  { id: "open_browser", label: "1. 打开浏览器", description: "在屏幕左侧半屏打开目标平台窗口" },
  { id: "swipe_page", label: "2. 界面滑动", description: "模拟触摸板/滚轮分段滚动页面" },
  { id: "find_search_box", label: "3. 找到搜索框", description: "定位并聚焦顶部搜索输入框" },
  { id: "click_filter_btn", label: "4. 点击筛选按钮", description: "点击「筛选」打开浮层（不抓取浮层内容）" },
  { id: "click_filter_overlay", label: "5. 点击筛选浮层按钮", description: "在 dialog 内按文案精确点击选项", needsFilterOption: true },
  { id: "input_search_text", label: "6. 输入搜索文本", description: "逐字模拟键盘输入搜索关键词", needsSearchText: true },
  { id: "click_search_btn", label: "7. 点击搜索", description: "触发搜索请求" },
  { id: "fetch_search_results", label: "8. 获取搜索结果", description: "抓取搜索页数据并返回", returnsData: true },
  {
    id: "click_search_video",
    label: "9. 点击搜索结果视频",
    description: "按序号点击搜索结果中的视频",
    needsVideoIndex: true,
  },
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
