<template>
  <div class="container">
      <div class="panel page-header">
        <div>
          <h2 class="page-title">API 文档</h2>
          <p class="page-subtitle">
            对外集成与抓取相关接口说明；仅收录当前在用的 API，废弃路径不再列出。下方可在线验证 Pipeline。
          </p>
        </div>
        <div class="header-actions">
          <el-button :loading="healthLoading" @click="checkHealthStatus">健康检查</el-button>
          <el-button type="primary" @click="openSwagger">OpenAPI 文档</el-button>
        </div>
      </div>

      <el-alert
        v-if="healthStatus"
        :title="healthStatus"
        :type="healthOk ? 'success' : 'error'"
        show-icon
        :closable="false"
        class="status-alert"
      />

      <el-alert
        v-if="errorMessage"
        :title="errorMessage"
        type="error"
        show-icon
        :closable="false"
        class="status-alert"
      />

      <div class="panel section-panel">
        <h3 class="section-title">缓存策略</h3>
        <p class="section-desc">
          所有抓取类接口默认缓存 <strong>24 小时</strong>。缓存命中时直接返回已存储数据，不触发 Playwright 抓取。
          评论数据按 <code>comment_id</code> 增量合并写入数据库，并维护 canonical JSON 文件。
        </p>
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="默认 TTL">24 小时（可通过 cache_ttl_hours 调整）</el-descriptions-item>
          <el-descriptions-item label="强制拉取">force_refresh=true 时跳过缓存并即时拉取；拉取失败则自动回退返回已有缓存</el-descriptions-item>
          <el-descriptions-item label="评论存储">
            DB 表 content_comments + 文件 comments_{platform}_{tenant}_{content_id}.json
          </el-descriptions-item>
          <el-descriptions-item label="搜索存储">
            缓存索引 crawl_cache_entries + 文件 search_{platform}_{tenant}_{hash}.json
          </el-descriptions-item>
          <el-descriptions-item label="响应字段">cache.from_cache / cache.cache_hit / cache.expires_at</el-descriptions-item>
        </el-descriptions>
      </div>

      <div class="panel section-panel">
        <h3 class="section-title">鉴权与请求头</h3>
        <p class="section-desc">
          在左侧边栏配置租户 ID 与 API Key；请求会自动携带以下 Header（通过
          <code>http.js</code> 拦截器注入）。
        </p>
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="X-Tenant-Id">
            <code>{{ tenantId }}</code>
          </el-descriptions-item>
          <el-descriptions-item label="X-Platform-Id">
            <code>{{ platformId }}</code>
          </el-descriptions-item>
          <el-descriptions-item label="X-Account-Id">
            <code>{{ accountId }}</code>
          </el-descriptions-item>
          <el-descriptions-item label="X-API-Key">
            <code>{{ apiKeyMasked }}</code>
            <span class="muted-inline">（启用租户鉴权时必填）</span>
          </el-descriptions-item>
          <el-descriptions-item label="Authorization">
            <code>{{ tokenMasked }}</code>
            <span class="muted-inline">（用户登录后自动携带）</span>
          </el-descriptions-item>
          <el-descriptions-item label="API Base URL">
            <code>{{ apiBaseUrl }}</code>
          </el-descriptions-item>
        </el-descriptions>
        <p class="section-desc note">
          管理员创建 API Key：<code>POST /api/admin/tenant-keys</code>，需携带
          <code>X-Admin-Secret</code>。
        </p>
      </div>

      <div class="panel section-panel">
        <h3 class="section-title">外部集成 API（推荐）</h3>
        <p class="section-desc">
          AISales / PC 客户端创建获客任务请走 <code>external/*</code>。先拉取
          <code>capabilities</code> 获取 intent 与字段定义，再
          <code>POST external/jobs</code> 创建任务；状态通过
          <code>GET jobs/{job_id}</code> 的 <code>sync</code> 字段或 webhook 同步。
          详细契约见仓库 <code>docs/technical/agent-job-sync-contract.md</code>。
        </p>
        <ApiEndpointTable :endpoints="externalEndpoints" :curl-builder="buildCurl" />
      </div>

      <div class="panel section-panel">
        <h3 class="section-title">关键词视频 + 评论 Pipeline</h3>
        <p class="section-desc">
          线索来源抓取入口：按关键词搜索热门视频/笔记并抓取评论（Skill
          <code>pipeline-keyword-video-comments</code>）。PC 客户端【线索来源】与内容库配合使用；
          异步模式返回 <code>job_id</code> 后轮询任务接口。
        </p>

        <div class="grid">
          <div class="form-area">
            <el-form label-width="110px">
              <el-form-item label="关键词" required>
                <el-input v-model="pipelineForm.keyword" placeholder="例如：淋浴房" />
              </el-form-item>
              <el-form-item label="平台">
                <el-checkbox-group v-model="pipelineForm.platforms">
                  <el-checkbox value="douyin">抖音</el-checkbox>
                  <el-checkbox value="xiaohongshu">小红书</el-checkbox>
                </el-checkbox-group>
              </el-form-item>
              <el-form-item label="视频数量">
                <el-input-number v-model="pipelineForm.video_limit" :min="1" :max="20" />
              </el-form-item>
              <el-form-item label="地区">
                <el-input
                  v-model="pipelineForm.region"
                  placeholder="可选，如：辽宁、沈阳、辽宁省淋浴房"
                  clearable
                />
                <span class="field-hint">会拼入搜索词并作为筛选上下文，留空则不限制</span>
              </el-form-item>
              <el-form-item label="最近天数">
                <el-input-number v-model="pipelineForm.days" :min="1" :max="30" />
              </el-form-item>
              <el-form-item label="超时 (秒)">
                <el-input-number v-model="pipelineForm.timeout_seconds" :min="60" :max="3600" :step="60" />
              </el-form-item>
              <el-form-item label="异步任务">
                <el-switch v-model="pipelineForm.async_job" />
                <span class="field-hint">开启后返回 job_id，通过任务接口轮询结果</span>
              </el-form-item>
              <el-form-item label="强制拉取">
                <el-switch v-model="pipelineForm.force_refresh" />
                <span class="field-hint">忽略 24h 缓存，立即触发抓取</span>
              </el-form-item>
              <el-form-item label="缓存 (小时)">
                <el-input-number v-model="pipelineForm.cache_ttl_hours" :min="0.25" :max="168" :step="1" />
              </el-form-item>
              <el-form-item>
                <el-button type="primary" :loading="pipelineLoading" @click="runPipeline">
                  调用接口
                </el-button>
                <el-button @click="copyPipelineCurl">复制 curl</el-button>
              </el-form-item>
            </el-form>
          </div>

          <div class="curl-area">
            <div class="curl-head">
              <span class="curl-label">请求示例</span>
              <el-button text size="small" @click="copyPipelineCurl">复制</el-button>
            </div>
            <pre class="code-block">{{ pipelineCurl }}</pre>
          </div>
        </div>

        <div v-if="pipelineResult" class="result-area">
          <div class="result-head">
            <h4>响应结果</h4>
            <el-tag :type="pipelineResult.status === 'completed' ? 'success' : 'warning'" size="small">
              {{ pipelineResult.status }}
            </el-tag>
            <el-tag v-if="pipelineResult.job_id" type="info" size="small" class="tag-gap">
              job_id: {{ pipelineResult.job_id }}
            </el-tag>
            <el-tag
              v-if="pipelineResult.cache?.from_cache"
              type="success"
              size="small"
              class="tag-gap"
            >
              缓存命中
            </el-tag>
          </div>
          <pre class="code-block result-json">{{ formatJson(pipelineResult) }}</pre>
        </div>
      </div>

      <div class="panel section-panel">
        <h3 class="section-title">内容库</h3>
        <p class="section-desc">
          Pipeline 或 Agent 任务抓取后的结构化数据。PC 客户端在 pipeline 完成后通过内容库拉取视频/笔记与评论，再转换为线索。
        </p>
        <ApiEndpointTable :endpoints="contentEndpoints" :curl-builder="buildCurl" />
      </div>

      <div class="panel section-panel">
        <h3 class="section-title">Skill 执行</h3>
        <p class="section-desc">
          同步执行单个 Skill（搜索、抓评、关注、私信等）。REST 平台工具路径已收敛为此入口，与 Pipeline、Agent 共用
          <code>SkillRunnerService</code>。
        </p>
        <ApiEndpointTable :endpoints="skillEndpoints" :curl-builder="buildCurl" />
      </div>

      <div class="panel section-panel">
        <h3 class="section-title">接口目录</h3>
        <el-tabs v-model="activeTab">
          <el-tab-pane label="外部集成" name="external">
            <ApiEndpointTable :endpoints="externalEndpoints" :curl-builder="buildCurl" />
          </el-tab-pane>
          <el-tab-pane label="Pipeline" name="pipeline">
            <ApiEndpointTable :endpoints="pipelineEndpoints" :curl-builder="buildCurl" />
          </el-tab-pane>
          <el-tab-pane label="内容库" name="contents">
            <ApiEndpointTable :endpoints="contentEndpoints" :curl-builder="buildCurl" />
          </el-tab-pane>
          <el-tab-pane label="Skill" name="skills">
            <ApiEndpointTable :endpoints="skillEndpoints" :curl-builder="buildCurl" />
          </el-tab-pane>
          <el-tab-pane label="基础" name="general">
            <ApiEndpointTable :endpoints="generalEndpoints" :curl-builder="buildCurl" />
          </el-tab-pane>
        </el-tabs>
      </div>
    </div>
</template>

<script setup>
import { computed, defineComponent, h, onMounted, onUnmounted, reactive, ref } from "vue";
import { ElButton, ElMessage, ElTag } from "element-plus";
import {
  getAccountId,
  getApiBaseUrl,
  getApiKey,
  getAccessToken,
  getPlatformId,
  getTenantId,
} from "../api/http";
import { checkHealth, getSwaggerDocsUrl, runKeywordVideoComments } from "../api/openPipeline";

const ApiEndpointTable = defineComponent({
  props: {
    endpoints: { type: Array, required: true },
    curlBuilder: { type: Function, required: true },
  },
  setup(props) {
    return () =>
      h(
        "div",
        { class: "endpoint-list" },
        props.endpoints.map((ep) =>
          h("div", { class: "endpoint-item", key: ep.path }, [
            h("div", { class: "endpoint-head" }, [
              h(ElTag, { type: ep.method === "GET" ? "success" : "primary", size: "small" }, () => ep.method),
              h("code", { class: "endpoint-path" }, ep.path),
              h("span", { class: "endpoint-summary" }, ep.summary),
            ]),
            h("p", { class: "endpoint-desc" }, ep.description),
            ep.body
              ? h("div", { class: "endpoint-body" }, [
                  h("span", { class: "body-label" }, "请求体："),
                  h("pre", { class: "code-block small" }, JSON.stringify(ep.body, null, 2)),
                ])
              : null,
            h(
              ElButton,
              {
                text: true,
                type: "primary",
                size: "small",
                onClick: () => copyText(props.curlBuilder(ep)),
              },
              () => "复制 curl"
            ),
          ])
        )
      );
  },
});

const tenantId = ref(getTenantId());
const platformId = ref(getPlatformId());
const accountId = ref(getAccountId());
const apiBaseUrl = getApiBaseUrl();

const healthLoading = ref(false);
const healthOk = ref(false);
const healthStatus = ref("");
const errorMessage = ref("");
const pipelineLoading = ref(false);
const pipelineResult = ref(null);
const activeTab = ref("external");

const pipelineForm = reactive({
  keyword: "",
  platforms: ["douyin", "xiaohongshu"],
  video_limit: 5,
  region: "",
  days: 3,
  timeout_seconds: 1200,
  async_job: false,
  force_refresh: false,
  cache_ttl_hours: 24,
});

const apiKeyMasked = computed(() => {
  const key = getApiKey();
  if (!key) return "（未设置）";
  if (key.length <= 8) return "****";
  return `${key.slice(0, 4)}****${key.slice(-4)}`;
});

const tokenMasked = computed(() => {
  const token = getAccessToken();
  if (!token) return "（未登录）";
  return `Bearer ${token.slice(0, 8)}...`;
});

const externalEndpoints = [
  {
    method: "GET",
    path: "/api/agent/external/capabilities",
    summary: "查询任务能力定义",
    description:
      "返回 schema huoke.external_task.v1：支持的 intent、scope 字段、lead_task_types 映射、同步 schema 版本。创建任务前应先调用。",
  },
  {
    method: "POST",
    path: "/api/agent/external/jobs",
    summary: "创建外部获客任务",
    description:
      "按 intent + scope 创建 Agent 异步任务。intent：keyword_auto（关键词自动）、single_video（单视频）、account_home（账号主页）。",
    body: {
      intent: "keyword_auto",
      name: "深圳团餐循环触达",
      platform: "douyin",
      scope: {
        keyword: "团餐配送",
        region: "深圳",
        target_count: 80,
        comment_days: 3,
      },
      outreach: {
        constraints: {
          comment_dm_interval_seconds_min: 30,
          follow_per_day: 10,
        },
      },
      correlation: {
        external_system: "aisales",
        external_task_id: "lead-task-uuid",
      },
      auto_execute: true,
      webhook_url: "https://example.com/api/huoke-agent-bridge/callbacks/jobs",
    },
  },
  {
    method: "GET",
    path: "/api/agent/jobs/{job_id}",
    summary: "查询任务状态与同步数据",
    description:
      "响应含 status、result 与 sync（schema huoke.agent_job_sync.v1：progress、leads、outreach_events 等）。",
  },
  {
    method: "POST",
    path: "/api/agent/jobs/{job_id}/cancel",
    summary: "取消运行中任务",
    description: "取消排队或执行中的任务。",
  },
];

const pipelineEndpoints = [
  {
    method: "POST",
    path: "/api/agent/pipeline/keyword-video-comments",
    summary: "关键词视频+评论 Pipeline",
    description: "按关键词搜索并抓取评论；async_job=true 时返回 job_id，配合 GET jobs/{job_id} 轮询。",
    body: {
      keyword: "淋浴房",
      platforms: ["douyin", "xiaohongshu"],
      video_limit: 5,
      region: "辽宁",
      days: 3,
      timeout_seconds: 1200,
      async_job: false,
      force_refresh: false,
      cache_ttl_hours: 24,
    },
  },
  {
    method: "GET",
    path: "/api/agent/jobs/{job_id}",
    summary: "查询异步 Pipeline 任务",
    description: "async_job 模式下轮询任务状态与结果。",
  },
];

const contentEndpoints = [
  {
    method: "GET",
    path: "/api/platforms/{platform}/contents",
    summary: "内容列表",
    description: "抓取入库的视频/笔记列表。platform：douyin | xiaohongshu | kuaishou。",
    query: { offset: 0, limit: 50 },
  },
  {
    method: "GET",
    path: "/api/platforms/{platform}/contents/{content_id}",
    summary: "内容详情（含评论）",
    description: "单条内容详情，可选 max_comments 限制返回评论数。",
    query: { max_comments: 200 },
  },
];

const skillEndpoints = [
  {
    method: "POST",
    path: "/api/agent/skills/execute",
    summary: "同步执行 Skill",
    description:
      "统一 Skill 入口。常用 skill_id：douyin-keyword-comments、xhs-keyword-comments、follow-user、send-dm、reply-comment。",
    body: {
      skill_id: "douyin-keyword-comments",
      platform: "douyin",
      params: { keyword: "护肤", limit: 3, days: 3 },
      agent_fallback: false,
      timeout_seconds: 600,
    },
  },
];

const generalEndpoints = [
  { method: "GET", path: "/api/health", summary: "健康检查" },
  {
    method: "POST",
    path: "/api/admin/tenant-keys",
    summary: "创建租户 API Key",
    description: "需 Header X-Admin-Secret。",
    body: { tenant_id: "default", label: "integration" },
  },
];

function refreshContext() {
  tenantId.value = getTenantId();
  platformId.value = getPlatformId();
  accountId.value = getAccountId();
}

function formatApiError(err, fallback) {
  const detail = err?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((d) => d.msg).join("; ");
  return err?.message || fallback;
}

function formatJson(data) {
  return JSON.stringify(data, null, 2);
}

function buildHeaders() {
  const headers = [
    `-H "Content-Type: application/json"`,
    `-H "X-Tenant-Id: ${getTenantId()}"`,
    `-H "X-Platform-Id: ${getPlatformId()}"`,
    `-H "X-Account-Id: ${getAccountId()}"`,
  ];
  const apiKey = getApiKey();
  if (apiKey) headers.push(`-H "X-API-Key: ${apiKey}"`);
  const token = getAccessToken();
  if (token) headers.push(`-H "Authorization: Bearer ${token}"`);
  return headers.join(" \\\n  ");
}

function buildCurl(endpoint) {
  const base = apiBaseUrl.replace(/\/$/, "");
  let url = `${base}${endpoint.path.replace("/api", "")}`;
  if (endpoint.query) {
    const qs = new URLSearchParams(endpoint.query).toString();
    url += `?${qs}`;
  }
  const lines = [`curl -X ${endpoint.method} "${url}" \\`, `  ${buildHeaders()}`];
  if (endpoint.body) {
    lines.push(`  -d '${JSON.stringify(endpoint.body)}'`);
  }
  return lines.join("\n");
}

const pipelineCurl = computed(() =>
  buildCurl({
    method: "POST",
    path: "/api/agent/pipeline/keyword-video-comments",
    body: {
      keyword: pipelineForm.keyword || "淋浴房",
      platforms: pipelineForm.platforms,
      video_limit: pipelineForm.video_limit,
      region: pipelineForm.region || null,
      days: pipelineForm.days,
      timeout_seconds: pipelineForm.timeout_seconds,
      async_job: pipelineForm.async_job,
      force_refresh: pipelineForm.force_refresh,
      cache_ttl_hours: pipelineForm.cache_ttl_hours,
    },
  })
);

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    ElMessage.success("已复制到剪贴板");
  } catch {
    ElMessage.error("复制失败，请手动选择复制");
  }
}

function copyPipelineCurl() {
  copyText(pipelineCurl.value);
}

async function checkHealthStatus() {
  healthLoading.value = true;
  errorMessage.value = "";
  try {
    const data = await checkHealth();
    healthOk.value = true;
    healthStatus.value = `服务正常：${data.status || "ok"}`;
  } catch (err) {
    healthOk.value = false;
    healthStatus.value = formatApiError(err, "健康检查失败");
  } finally {
    healthLoading.value = false;
  }
}

function openSwagger() {
  window.open(getSwaggerDocsUrl(), "_blank", "noopener,noreferrer");
}

async function runPipeline() {
  if (!pipelineForm.keyword.trim()) {
    ElMessage.warning("请先输入关键词");
    return;
  }
  if (!pipelineForm.platforms.length) {
    ElMessage.warning("请至少选择一个平台");
    return;
  }
  pipelineLoading.value = true;
  errorMessage.value = "";
  pipelineResult.value = null;
  try {
    const data = await runKeywordVideoComments({
      keyword: pipelineForm.keyword.trim(),
      platforms: pipelineForm.platforms,
      video_limit: pipelineForm.video_limit,
      region: pipelineForm.region.trim() || null,
      days: pipelineForm.days,
      timeout_seconds: pipelineForm.timeout_seconds,
      async_job: pipelineForm.async_job,
      force_refresh: pipelineForm.force_refresh,
      cache_ttl_hours: pipelineForm.cache_ttl_hours,
    });
    pipelineResult.value = data;
    if (data.cache?.from_cache) {
      ElMessage.success("返回缓存数据（未触发抓取）");
    } else if (data.job_id) {
      ElMessage.success(`异步任务已提交，job_id: ${data.job_id}`);
    } else {
      ElMessage.success("Pipeline 执行完成");
    }
  } catch (err) {
    errorMessage.value = formatApiError(err, "Pipeline 调用失败");
    ElMessage.error(errorMessage.value);
  } finally {
    pipelineLoading.value = false;
  }
}

function onContextChanged() {
  refreshContext();
}

onMounted(() => {
  refreshContext();
  window.addEventListener("huoke-tenant-changed", onContextChanged);
});

onUnmounted(() => {
  window.removeEventListener("huoke-tenant-changed", onContextChanged);
});
</script>

<style scoped>
.page-header {
  padding: 16px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}

.header-actions {
  display: flex;
  gap: 8px;
}

.status-alert {
  margin-top: 12px;
}

.section-panel {
  padding: 16px;
  margin-top: 12px;
}

.section-title {
  margin: 0 0 8px;
  font-size: 16px;
}

.section-desc {
  margin: 0 0 14px;
  color: var(--muted);
  font-size: 13px;
  line-height: 1.5;
}

.section-desc.note {
  margin-top: 12px;
  margin-bottom: 0;
}

.muted-inline {
  margin-left: 8px;
  color: var(--muted);
  font-size: 12px;
}

.grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.form-area {
  min-width: 0;
}

.curl-area {
  min-width: 0;
}

.curl-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.curl-label {
  font-size: 13px;
  color: var(--muted);
}

.code-block {
  margin: 0;
  padding: 12px;
  background: #f8fafc;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.5;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;
}

.code-block.small {
  font-size: 11px;
  padding: 8px;
}

.result-area {
  margin-top: 16px;
}

.result-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.result-head h4 {
  margin: 0;
  font-size: 14px;
}

.tag-gap {
  margin-left: 4px;
}

.field-hint {
  display: block;
  margin-top: 6px;
  font-size: 12px;
  color: var(--muted);
}

:deep(.endpoint-list) {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

:deep(.endpoint-item) {
  padding-bottom: 16px;
  border-bottom: 1px solid #f0f0f0;
}

:deep(.endpoint-item:last-child) {
  border-bottom: none;
  padding-bottom: 0;
}

:deep(.endpoint-head) {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}

:deep(.endpoint-path) {
  font-size: 13px;
  color: #374151;
}

:deep(.endpoint-summary) {
  font-size: 13px;
  color: var(--muted);
}

:deep(.endpoint-desc) {
  margin: 0 0 8px;
  font-size: 13px;
  color: #4b5563;
  line-height: 1.5;
}

:deep(.endpoint-body) {
  margin-bottom: 8px;
}

:deep(.body-label) {
  font-size: 12px;
  color: var(--muted);
}

.result-json {
  max-height: 400px;
  overflow-y: auto;
}

@media (max-width: 900px) {
  .grid {
    grid-template-columns: 1fr;
  }

  .page-header {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
