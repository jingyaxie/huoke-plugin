#!/usr/bin/env node
/**
 * 插件实验室串联测试
 * 用法: node scripts/run-plugin-lab-auto-flow.mjs [xiaohongshu|kuaishou|xhs|ks|all]
 * 默认: 小红书 + 快手（不含抖音）
 */
const BASE = process.env.VITE_LOCAL_SERVICE_URL || "http://127.0.0.1:18766";

const DEFAULTS = {
  douyin: {
    searchText: "创业",
    filterOption: "一天内",
    videoIndex: 1,
    scrollRounds: 4,
    maxComments: 15,
    scrollDistance: 800,
  },
  xiaohongshu: {
    searchText: "护肤",
    videoIndex: 1,
    scrollRounds: 4,
    maxComments: 15,
    scrollDistance: 800,
  },
  kuaishou: {
    searchText: "美食",
    videoIndex: 1,
    scrollRounds: 4,
    maxComments: 15,
    scrollDistance: 800,
  },
};

const FLOW = [
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

const SKIP = {
  xiaohongshu: new Set(["click_filter_btn", "click_filter_overlay"]),
  kuaishou: new Set(["click_filter_btn", "click_filter_overlay"]),
  douyin: new Set(),
};

function buildPayload(actionId, platform) {
  const d = DEFAULTS[platform];
  const payload = {};
  switch (actionId) {
    case "open_browser":
      payload.platform = platform;
      payload.reuse_existing = false;
      break;
    case "swipe_page":
      payload.direction = "down";
      payload.distance = d.scrollDistance;
      break;
    case "find_search_box":
    case "input_search_text":
      payload.platform = platform;
      if (actionId === "input_search_text") payload.search_text = d.searchText;
      break;
    case "click_search_btn":
      break;
    case "fetch_search_results":
      payload.limit = 20;
      payload.api_timeout_ms = 15000;
      break;
    case "click_search_video":
      payload.video_index = d.videoIndex;
      break;
    case "scroll_and_collect_comments":
      payload.scroll_rounds = d.scrollRounds;
      payload.max_comments = d.maxComments;
      break;
    default:
      break;
  }
  return payload;
}

async function runAction(actionId, platform) {
  const url = `${BASE}/api/plugin-lab/actions/${actionId}`;
  const payload = buildPayload(actionId, platform);
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal: AbortSignal.timeout(180_000),
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.error || data.message || `HTTP ${res.status}`);
  }
  const body = data.data ?? data;
  const ok = data.ok !== false && body?.ok !== false;
  return {
    ok,
    message: body?.message || data.message || data.error || (ok ? "ok" : "failed"),
    count: body?.count ?? body?.items?.length,
  };
}

async function runPlatform(platform) {
  console.log(`\n========== ${platform} ==========`);
  const results = [];
  for (const actionId of FLOW) {
    if (SKIP[platform]?.has(actionId)) {
      console.log(`  SKIP  ${actionId}`);
      results.push({ actionId, status: "skipped" });
      continue;
    }
    process.stdout.write(`  RUN   ${actionId} ... `);
    const start = Date.now();
    try {
      const r = await runAction(actionId, platform);
      const sec = ((Date.now() - start) / 1000).toFixed(1);
      const extra = r.count != null ? ` (count=${r.count})` : "";
      if (r.ok) {
        console.log(`PASS ${sec}s${extra} — ${r.message}`);
        results.push({ actionId, status: "pass", message: r.message });
      } else {
        console.log(`FAIL ${sec}s — ${r.message}`);
        results.push({ actionId, status: "fail", message: r.message });
        break;
      }
    } catch (err) {
      const sec = ((Date.now() - start) / 1000).toFixed(1);
      const msg = err?.message || String(err);
      console.log(`ERR  ${sec}s — ${msg}`);
      results.push({ actionId, status: "error", message: msg });
      break;
    }
  }
  return results;
}

async function main() {
  const arg = process.argv[2] || "xhs_ks";
  const statusRes = await fetch(`${BASE}/api/plugin-lab/status`);
  const status = await statusRes.json();
  if (!status.connected_clients) {
    console.error("插件未连接，请加载 extension/dist 并确保角标 OK");
    process.exit(1);
  }
  console.log(`local-service OK, extension clients=${status.connected_clients}`);

  const platformMap = {
    xhs: "xiaohongshu",
    ks: "kuaishou",
    xiaohongshu: "xiaohongshu",
    kuaishou: "kuaishou",
    douyin: "douyin",
  };
  let platforms;
  if (arg === "all") {
    platforms = ["xiaohongshu", "kuaishou"];
  } else if (arg === "xhs_ks" || arg === "both") {
    platforms = ["xiaohongshu", "kuaishou"];
  } else {
    platforms = [platformMap[arg] || arg];
  }

  const summary = {};
  for (const p of platforms) {
    summary[p] = await runPlatform(p);
  }

  console.log("\n========== SUMMARY ==========");
  for (const [p, rows] of Object.entries(summary)) {
    const pass = rows.filter((r) => r.status === "pass").length;
    const fail = rows.find((r) => r.status === "fail" || r.status === "error");
    console.log(
      `${p}: ${pass}/${FLOW.length} passed` + (fail ? ` — stopped at ${fail.actionId}: ${fail.message}` : ""),
    );
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
