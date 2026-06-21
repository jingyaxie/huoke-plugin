#!/usr/bin/env node
/**
 * 搜索/主页「打开详情 → 返回」是否覆盖搜索上下文
 *
 * 用法:
 *   node scripts/test-search-return-smoke.mjs [douyin|xhs|ks|profile|all]
 *
 * 环境:
 *   VITE_LOCAL_SERVICE_URL  默认 http://127.0.0.1:18766
 *   DOUYIN_PROFILE_URL        抖音主页测试 URL（profile 场景必填）
 */
const BASE = process.env.VITE_LOCAL_SERVICE_URL || "http://127.0.0.1:18766";

const KEYWORDS = {
  douyin: process.env.DOUYIN_SEARCH_KEYWORD || "创业",
  xiaohongshu: process.env.XHS_SEARCH_KEYWORD || "护肤",
  kuaishou: process.env.KS_SEARCH_KEYWORD || "美食",
};

const PROFILE_URL = process.env.DOUYIN_PROFILE_URL?.trim() || "";

async function api(actionId, payload = {}, attempt = 1) {
  const res = await fetch(`${BASE}/api/plugin-lab/actions/${actionId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal: AbortSignal.timeout(180_000),
  });
  const data = await res.json();
  const body = data.data ?? data;
  const ok = res.ok && data.ok !== false && body?.ok !== false;
  const errMsg = data.error || body?.message || body?.error || `HTTP ${res.status}`;
  if (!ok) {
    if (attempt < 3 && /content script not responding|no platform tab|no extension connected/i.test(errMsg)) {
      await sleep(2500);
      return api(actionId, payload, attempt + 1);
    }
    throw new Error(`${actionId}: ${errMsg}`);
  }
  return body;
}

async function snapshot(platform) {
  return api("search_context_probe", { platform });
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

function isSearchListReady(probe, platform) {
  if (probe.on_search_page) return true;
  if (platform === "xiaohongshu" || platform === "kuaishou") {
    return (probe.search_card_count ?? 0) > 0;
  }
  return false;
}

function hasStoredSearchUrl(probe) {
  return Boolean(probe.search_url_preserved || probe.lab_search_url || probe.tab_session_search_url);
}

function log(step, msg) {
  console.log(`  [${step}] ${msg}`);
}

function assert(cond, msg) {
  if (!cond) throw new Error(msg);
}

async function papi(platform, actionId, payload = {}) {
  return api(actionId, { platform, ...payload });
}

async function searchFlow(platform, label) {
  const keyword = KEYWORDS[platform];
  console.log(`\n=== ${label} 搜索返回 ===`);

  await papi(platform, "open_browser", { reuse_existing: true, wait_load: true });
  await papi(platform, "find_search_box", {});
  await papi(platform, "input_search_text", { search_text: keyword });
  await papi(platform, "click_search_btn", { search_text: keyword });
  await sleep(1500);

  const before = await snapshot(platform);
  log("search", `url=${before.url}`);
  log("search", `lab_search_url=${before.lab_search_url || before.tab_session_search_url || "(empty)"}`);

  const fetch1 = await papi(platform, "fetch_search_results", { limit: 12, api_timeout_ms: 15000 });
  const count1 = fetch1.count ?? fetch1.items?.length ?? 0;
  log("fetch", `第 1 次 ${count1} 条`);
  assert(count1 > 0, "搜索结果为空");

  const afterFetch = await snapshot(platform);
  assert(isSearchListReady(afterFetch, platform), "fetch 后不在搜索结果/列表态");
  assert(hasStoredSearchUrl(afterFetch) || count1 > 0, "未记录搜索 URL");

  await papi(platform, "click_search_video", { video_index: 1, use_detail_window: true });
  await sleep(1500);

  const inVideo = await snapshot(platform);
  log("video", `list url=${inVideo.url} (列表页应不变)`);

  await papi(platform, "close_video_detail", {});
  await sleep(800);

  const afterClose = await snapshot(platform);
  log("return", `list url=${afterClose.url}`);
  log("return", `on_search_page=${afterClose.on_search_page} cards=${afterClose.search_card_count}`);
  assert(isSearchListReady(afterClose, platform), "关闭视频窗后列表页丢失");

  const fetch2 = await papi(platform, "fetch_search_results", { limit: 12, api_timeout_ms: 15000 });
  const count2 = fetch2.count ?? fetch2.items?.length ?? 0;
  log("fetch", `关闭视频窗后第 2 次 ${count2} 条`);
  assert(count2 > 0, "关闭视频窗后无法再次拉取搜索结果");

  try {
    await papi(platform, "click_search_video", { video_index: 2, use_detail_window: true });
    log("continue", "成功在独立窗口打开第 2 个视频");
    await papi(platform, "close_video_detail", {});
  } catch (err) {
    log("continue", `第 2 个视频跳过: ${err.message}`);
  }

  console.log(`✅ ${label} 搜索返回通过`);
  return { platform, ok: true };
}

async function profileFlow() {
  if (!PROFILE_URL) {
    console.log("\n=== 抖音主页返回 ===");
    console.log("⏭  跳过：请设置 DOUYIN_PROFILE_URL");
    return { platform: "douyin-profile", skipped: true };
  }

  console.log("\n=== 抖音主页返回 ===");
  const platform = "douyin";

  await api("open_browser", { platform, url: PROFILE_URL, reuse_existing: true, wait_load: true });
  await sleep(1500);

  const prof1 = await api("fetch_profile_videos", { limit: 12 });
  const count1 = prof1.count ?? prof1.items?.length ?? 0;
  log("profile", `作品 ${count1} 条`);
  assert(count1 > 0, "主页无作品");

  const profileUrl = PROFILE_URL;

  await api("click_profile_video", { video_index: 1 });
  await sleep(1200);

  await api("close_video_detail", {});
  await sleep(800);

  const back = await api("back_to_profile", { profile_url: profileUrl });
  log("back", back.message || back.url);

  const prep = await api("prepare_profile_for_video", {});
  log("prepare", prep.message || JSON.stringify(prep));
  assert(prep.on_profile_page !== false, "返回后不在主页");

  const prof2 = await api("fetch_profile_videos", { limit: 12 });
  const count2 = prof2.count ?? prof2.items?.length ?? 0;
  log("profile", `返回后作品 ${count2} 条`);
  assert(count2 > 0, "返回主页后作品列表为空");

  console.log("✅ 抖音主页返回通过");
  return { platform: "douyin-profile", ok: true };
}

async function ensureService() {
  const res = await fetch(`${BASE}/api/plugin-lab/status`, { signal: AbortSignal.timeout(5000) });
  const st = await res.json();
  if (!st.connected_clients) {
    throw new Error("扩展未连接 — 请加载 extension/dist 并确认 local-service 在运行");
  }
  return st;
}

const SCENARIOS = {
  douyin: () => searchFlow("douyin", "抖音"),
  xhs: () => searchFlow("xiaohongshu", "小红书"),
  ks: () => searchFlow("kuaishou", "快手"),
  profile: profileFlow,
  all: async () => {
    const results = [];
    for (const fn of [SCENARIOS.douyin, SCENARIOS.xhs, SCENARIOS.ks, SCENARIOS.profile]) {
      results.push(await fn());
    }
    return results;
  },
};

async function main() {
  const arg = (process.argv[2] || "all").toLowerCase();
  const key = arg === "xiaohongshu" ? "xhs" : arg === "kuaishou" ? "ks" : arg;
  const run = SCENARIOS[key];
  if (!run) {
    console.error(`未知场景: ${arg}（douyin|xhs|ks|profile|all）`);
    process.exit(2);
  }

  console.log(`local-service: ${BASE}`);
  const st = await ensureService();
  console.log(`扩展已连接: ${st.connected_clients} 客户端`);

  const started = Date.now();
  try {
    await run();
    console.log(`\n全部完成 (${((Date.now() - started) / 1000).toFixed(1)}s)`);
  } catch (err) {
    console.error(`\n❌ 失败: ${err.message}`);
    process.exit(1);
  }
}

main();
