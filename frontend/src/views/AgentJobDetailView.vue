<template>
  <div class="agent-job-detail">
    <header class="panel detail-hero">
      <div class="hero-top">
        <div class="hero-title-block">
          <h1 class="hero-title">{{ heroTitle }}</h1>
          <div v-if="job" class="hero-tags">
            <el-tag :type="statusTagType(job.status)" size="small">{{ statusLabel(job.status) }}</el-tag>
            <span class="stage-text">阶段 · {{ job.stage || "—" }}</span>
            <el-tag v-if="orchestration?.template_name" type="info" size="small" effect="plain">
              {{ orchestration.template_name }}
            </el-tag>
            <el-tag v-if="compileMethodLabel" type="success" size="small" effect="plain">
              {{ compileMethodLabel }}
            </el-tag>
          </div>
        </div>
        <div v-if="job" class="hero-actions">
          <el-button
            v-if="canStartJob"
            type="primary"
            :loading="executing"
            @click="executeJob"
          >
            {{ startJobLabel }}
          </el-button>
          <el-button v-if="job.run_id" type="primary" plain @click="openRun">查看 Run</el-button>
          <el-button :loading="loading" @click="reload">刷新</el-button>
          <el-button
            v-if="job.status === 'queued' || job.status === 'running'"
            type="danger"
            plain
            @click="cancelJob"
          >
            取消任务
          </el-button>
          <el-button
            v-if="canDeleteJob"
            type="danger"
            plain
            @click="deleteJob"
          >
            删除任务
          </el-button>
        </div>
      </div>
      <div v-if="job" class="hero-meta">
        <span class="meta-item"><em>Job ID</em><code>{{ job.job_id }}</code></span>
        <span class="meta-item"><em>模型</em>{{ job.provider || "—" }} · {{ job.mode || "—" }}</span>
        <span class="meta-item"><em>平台</em>{{ job.platform || "—" }} · {{ job.account_id || "—" }}</span>
        <span class="meta-item"><em>更新</em>{{ formatTime(job.updated_at) }}</span>
      </div>
    </header>

    <div v-loading="loading" class="detail-body">
      <template v-if="job">
        <el-alert
          v-if="orchestration?.llm_fallback"
          title="大模型未可用，当前编排为规则回退结果。登录盈小蚁后重新创建任务可获得 LLM 理解编排。"
          type="warning"
          show-icon
          :closable="false"
          class="detail-alert top-note"
        />
        <el-alert
          v-if="suspendBrief"
          type="warning"
          show-icon
          :closable="false"
          class="detail-alert top-note suspend-alert"
        >
          <template #title>任务已暂停</template>
          <div class="suspend-brief">
            <p v-if="suspendBrief.user_summary" class="suspend-summary">{{ suspendBrief.user_summary }}</p>
            <p><strong>原因：</strong>{{ suspendBrief.reason }}</p>
            <ul v-if="suspendEvidence.length" class="suspend-evidence">
              <li v-for="(line, idx) in suspendEvidence" :key="idx">{{ line }}</li>
            </ul>
            <div v-if="diagnosisScreenshotUrl" class="suspend-screenshot-wrap">
              <img :src="diagnosisScreenshotUrl" alt="诊断截图" class="suspend-screenshot" />
            </div>
            <p v-if="suspendBrief.resume_at_display">
              <strong>自动恢复时间：</strong>{{ suspendBrief.resume_at_display }}
            </p>
            <p v-else>
              <strong>自动恢复时间：</strong>未设定（仅支持手动继续）
            </p>
            <p><strong>恢复后将做：</strong>{{ suspendBrief.next_action }}</p>
            <p class="suspend-hint">{{ suspendBrief.manual_resume }}</p>
          </div>
        </el-alert>
        <el-alert
          v-else-if="executionNote"
          :title="executionNote"
          :type="executionNoteType"
          show-icon
          :closable="false"
          class="detail-alert top-note"
        />

        <div v-if="executionStats" class="execution-stats panel-lite">
          <div class="block-head">
            <h4 class="block-title">执行统计</h4>
            <span class="block-hint">匹配 · 触达 · 目标进度</span>
          </div>
          <div class="stats-grid">
            <div class="stat-card">
              <div class="stat-value">{{ executionStats.comments_captured }}</div>
              <div class="stat-label">匹配评论</div>
              <div class="stat-sub">
                入库 {{ executionStats.comments_persisted }}
                <template v-if="executionStats.raw_comments_scanned">
                  · 扫描 {{ executionStats.raw_comments_scanned }} 条
                </template>
                · {{ executionStats.crawl_done ? "浏览完成" : "浏览中" }}
                <template v-if="executionStats.crawl_success_count || executionStats.crawl_fail_count">
                  · 成功 {{ executionStats.crawl_success_count }} / 失败 {{ executionStats.crawl_fail_count }}
                </template>
              </div>
            </div>
            <div class="stat-card">
              <div class="stat-value stat-value--split">
                <span class="stat-ok">{{ executionStats.reply.ok }}</span>
                <span class="stat-sep">/</span>
                <span class="stat-fail">{{ executionStats.reply.failed }}</span>
              </div>
              <div class="stat-label">评论回复</div>
              <div class="stat-sub">
                成功 / 失败
                <template v-if="executionStats.reply.daily?.limit != null">
                  · 今日 {{ executionStats.reply.daily.used }}/{{ executionStats.reply.daily.limit }}
                </template>
              </div>
            </div>
            <div class="stat-card">
              <div class="stat-value stat-value--split">
                <span class="stat-ok">{{ executionStats.dm.ok }}</span>
                <span class="stat-sep">/</span>
                <span class="stat-fail">{{ executionStats.dm.failed }}</span>
              </div>
              <div class="stat-label">私信</div>
              <div class="stat-sub">
                成功 / 失败
                <template v-if="executionStats.dm.daily?.limit != null">
                  · 今日 {{ executionStats.dm.daily.used }}/{{ executionStats.dm.daily.limit }}
                </template>
              </div>
            </div>
            <div class="stat-card">
              <div class="stat-value stat-value--split">
                <span class="stat-ok">{{ executionStats.follow.ok }}</span>
                <span class="stat-sep">/</span>
                <span class="stat-fail">{{ executionStats.follow.failed }}</span>
              </div>
              <div class="stat-label">关注</div>
              <div class="stat-sub">
                成功 / 失败
                <template v-if="executionStats.follow.daily?.limit != null">
                  · 今日 {{ executionStats.follow.daily.used }}/{{ executionStats.follow.daily.limit }}
                </template>
              </div>
            </div>
            <div class="stat-card stat-card--wide">
              <div class="stat-value">
                {{ executionStats.leads_collected }}
                <span class="stat-target">/ {{ executionStats.target_leads || "—" }}</span>
              </div>
              <div class="stat-label">线索触达</div>
              <el-progress
                v-if="executionStats.target_leads"
                :percentage="Math.min(100, executionStats.progress_pct || 0)"
                :stroke-width="8"
                class="stat-progress"
              />
              <div class="stat-sub">
                本任务触达合计 {{ executionStats.total_outreach_ok }} 条
                <template v-if="executionStats.comments_replied">
                  · 已回复评论 {{ executionStats.comments_replied }} 条
                </template>
              </div>
            </div>
          </div>
        </div>

        <div class="detail-grid">
          <section class="detail-main">
            <div v-if="progressEvents.length" class="progress-block panel-lite">
              <div class="block-head">
                <h4 class="block-title">处理过程</h4>
                <span class="block-hint">{{ progressEvents.length }} 条事件</span>
              </div>
              <ul class="progress-list">
                <li v-for="(evt, idx) in progressEventsDisplayed" :key="idx">
                  <span class="evt-time">{{ formatEventTime(evt.at) }}</span>
                  <span class="evt-label">{{ evt.label || evt.type }}</span>
                </li>
              </ul>
              <p v-if="progressEvents.length > progressEventsDisplayed.length" class="progress-more">
                仅展示最近 {{ progressEventsDisplayed.length }} 条，完整记录请查看 Run
              </p>
            </div>
            <el-empty
              v-else-if="job.status === 'running' || job.status === 'retrying'"
              :description="runningEmptyHint"
              :image-size="64"
              class="panel-lite"
            />
            <el-empty
              v-else-if="orchestration?.is_preview && !orchestration?.llm_compiled"
              description="尚未启动执行，编排步骤为静态预览"
              :image-size="64"
              class="panel-lite"
            />
            <el-empty
              v-else-if="orchestration?.llm_compiled && job.status === 'pending'"
              description="大模型已生成任务简报，可点击「启动执行」开始 Supervisor 循环"
              :image-size="64"
              class="panel-lite"
            />

            <div v-if="canEditConfig" class="config-edit-block panel-lite">
              <div class="block-head">
                <h4 class="block-title">修改配置</h4>
                <span class="block-hint">自然语言或 JSON</span>
              </div>
              <el-radio-group v-model="configEditMode" size="small" class="config-mode">
                <el-radio-button value="nl">自然语言</el-radio-button>
                <el-radio-button value="json">JSON</el-radio-button>
              </el-radio-group>
              <el-input
                v-model="configInput"
                type="textarea"
                :rows="configEditMode === 'json' ? 10 : 4"
                :placeholder="configPlaceholder"
                class="config-textarea"
              />
              <div class="config-actions">
                <el-button
                  v-if="configEditMode === 'json'"
                  size="small"
                  @click="resetConfigJson"
                >
                  载入当前配置
                </el-button>
                <el-button
                  type="primary"
                  size="small"
                  :loading="configSaving"
                  :disabled="!configInput.trim()"
                  @click="applyConfigUpdate"
                >
                  应用修改
                </el-button>
              </div>
              <p class="config-hint">
                示例：「把目标改成100条，私信优先」或
                <code>{"goals":{"target_leads":100},"constraints":{"outreach_priority":["dm","reply","follow"]}}</code>
              </p>
              <ul v-if="configUpdates.length" class="config-history">
                <li v-for="(item, idx) in configUpdates.slice(0, 5)" :key="idx">
                  <span class="evt-time">{{ formatTime(item.at) }}</span>
                  {{ item.instruction_preview || (item.had_structured_config ? "JSON 配置更新" : "配置更新") }}
                </li>
              </ul>
            </div>

            <div v-if="inputSummary" class="summary-block panel-lite">
              <h4 class="block-title">任务摘要</h4>
              <dl class="summary-grid">
                <template v-for="(val, key) in inputSummary" :key="key">
                  <dt>{{ summaryLabel(key) }}</dt>
                  <dd>{{ val ?? "—" }}</dd>
                </template>
              </dl>
            </div>

            <div v-if="taskBriefMd" class="brief-block panel-lite">
              <h4 class="block-title">任务简报 (task_brief.md)</h4>
              <pre class="brief-pre">{{ taskBriefMd }}</pre>
            </div>

            <div v-if="supervisorCycles.length" class="cycles-block panel-lite">
              <div class="block-head">
                <h4 class="block-title">Supervisor 决策日志</h4>
                <span class="block-hint">{{ supervisorCycles.length }} 轮</span>
              </div>
              <ul class="cycle-list">
                <li v-for="cycle in supervisorCyclesDisplayed" :key="cycle.cycle" class="cycle-item">
                  <div class="cycle-head">
                    <span class="cycle-num">第 {{ cycle.cycle }} 轮</span>
                    <el-tag size="small" :type="cycle.ok ? 'success' : 'danger'" effect="light">
                      {{ cycle.action }}
                    </el-tag>
                  </div>
                  <p v-if="cycle.reasoning" class="cycle-reason">{{ cycle.reasoning }}</p>
                  <p v-if="cycle.result_summary" class="cycle-result">{{ cycle.result_summary }}</p>
                </li>
              </ul>
            </div>

            <div v-if="taskLedger" class="ledger-block panel-lite">
              <h4 class="block-title">任务台账</h4>
              <dl class="summary-grid">
                <dt>评论回复</dt>
                <dd>成功 {{ taskLedger.stats?.reply?.ok ?? 0 }} · 失败 {{ taskLedger.stats?.reply?.failed ?? 0 }}</dd>
                <dt>私信</dt>
                <dd>成功 {{ taskLedger.stats?.dm?.ok ?? 0 }} · 失败 {{ taskLedger.stats?.dm?.failed ?? 0 }}</dd>
                <dt>关注</dt>
                <dd>成功 {{ taskLedger.stats?.follow?.ok ?? 0 }} · 失败 {{ taskLedger.stats?.follow?.failed ?? 0 }}</dd>
                <dt>本任务触达合计</dt>
                <dd>{{ taskLedger.total_outreach_ok ?? 0 }} 条</dd>
              </dl>
              <ul v-if="taskLedger.comment_status?.length" class="ledger-sublist">
                <li v-for="(row, idx) in taskLedger.comment_status.slice(-10).reverse()" :key="`c-${idx}`">
                  评论 {{ row.comment_id }} · {{ row.status }}
                  <span v-if="row.reply_text" class="muted">「{{ row.reply_text }}」</span>
                </li>
              </ul>
            </div>

            <div v-if="sandboxInfo" class="sandbox-block panel-lite">
              <h4 class="block-title">任务沙盒</h4>
              <dl class="summary-grid">
                <dt>根目录</dt>
                <dd><code class="mono small-path">{{ sandboxInfo.root }}</code></dd>
                <dt>本地库</dt>
                <dd><code class="mono small-path">{{ sandboxInfo.db_path }}</code></dd>
                <dt>数据表</dt>
                <dd>{{ (sandboxInfo.tables || []).join(" · ") }}</dd>
                <dt>代码区</dt>
                <dd><code>code/helpers.py</code>（可写辅助逻辑）</dd>
                <template v-if="sandboxStats?.available">
                  <dt>沙盒统计</dt>
                  <dd>
                    线索 {{ sandboxStats.leads_total ?? 0 }}（新 {{ sandboxStats.leads_new ?? 0 }}）
                    · 触达成功 {{ sandboxStats.outreach_ok ?? 0 }}
                    · 抓取批次 {{ sandboxStats.crawl_batches ?? 0 }}
                  </dd>
                </template>
              </dl>
              <p class="sandbox-hint">每任务独立目录 + SQLite；删除任务沙盒可一键清理，不影响全局库。</p>
            </div>

            <div v-if="orchestrationSteps.length" class="orch-block panel-lite">
              <div class="block-head">
                <h4 class="block-title">编排步骤</h4>
                <span class="block-hint">{{ orchestrationHint }}</span>
              </div>
              <div class="workflow-steps">
                <div
                  v-for="(step, idx) in orchestrationSteps"
                  :key="step.id || idx"
                  class="workflow-step"
                  :class="stepStatusClass(step.status)"
                >
                  <div class="step-index">{{ step.order || idx + 1 }}</div>
                  <div class="step-body">
                    <div class="step-id">{{ step.id || step.stage }}</div>
                    <div class="step-action">{{ step.action }}</div>
                    <div v-if="step.capability" class="step-cap">{{ step.capability }}</div>
                    <ul v-if="step.sub_steps?.length" class="sub-steps">
                      <li v-for="sub in step.sub_steps" :key="sub.action || sub.label">
                        <strong>{{ sub.order }}. {{ sub.label || sub.action }}</strong>
                        <span v-if="sub.repeat_until" class="sub-desc"> · 循环至 {{ sub.repeat_until }}</span>
                      </li>
                    </ul>
                  </div>
                  <el-tag size="small" :type="stepTagType(step.status)" effect="light">
                    {{ stepStatusLabel(step.status) }}
                  </el-tag>
                </div>
              </div>
              <p v-if="orchestration?.reasoning" class="orch-reason">{{ orchestration.reasoning }}</p>
              <p v-if="orchestration?.unmapped_fields?.length" class="orch-unmapped">
                未映射字段：{{ orchestration.unmapped_fields.join("、") }}
              </p>
            </div>

            <div v-if="executionSummary" class="result-block panel-lite">
              <h4 class="block-title">执行摘要</h4>
              <p class="exec-summary">{{ executionSummary }}</p>
            </div>
          </section>

          <aside class="detail-side">
            <div class="meta-block panel-lite">
              <h4 class="block-title">运行信息</h4>
              <dl class="meta-grid">
                <dt v-if="!inputSummary">任务内容</dt>
                <dd v-if="!inputSummary" class="message-cell">{{ job.message || "—" }}</dd>
                <dt>运行模式</dt>
                <dd>{{ runModeLabel(job.run_mode) }}</dd>
                <dt>调度</dt>
                <dd>
                  优先级 {{ job.priority ?? "—" }} · 重试 {{ job.retry_count ?? 0 }}/{{ job.max_retries ?? "—" }} ·
                  超时 {{ job.timeout_seconds ?? "—" }}s
                </dd>
                <dt>执行策略</dt>
                <dd>
                  {{ job.auto_execute ? "自动执行" : "手动启动" }} ·
                  {{ job.auto_restart ? "失败自动重启" : "失败即停" }}
                </dd>
                <template v-if="dedicatedAgent">
                  <dt>专用智能体</dt>
                  <dd>
                    <code class="mono">{{ dedicatedAgent.profile_id }}</code>
                    <span v-if="dedicatedAgent.strategy_label" class="muted">
                      · {{ dedicatedAgent.strategy_label }}
                    </span>
                    <span v-if="dedicatedAgent.skill_ids?.length" class="muted">
                      · {{ dedicatedAgent.skill_ids.length }} 个 Skill
                    </span>
                  </dd>
                </template>
                <dt>Run ID</dt>
                <dd>
                  <code v-if="job.run_id" class="mono link-code" @click="openRun">{{ job.run_id }}</code>
                  <span v-else class="muted">—</span>
                </dd>
                <dt>Session ID</dt>
                <dd><code v-if="job.session_id" class="mono">{{ job.session_id }}</code><span v-else class="muted">—</span></dd>
                <dt>创建时间</dt>
                <dd>{{ formatTime(job.created_at) }}</dd>
                <dt>更新时间</dt>
                <dd>{{ formatTime(job.updated_at) }}</dd>
              </dl>
            </div>

            <el-alert v-if="job.error" :title="job.error" type="error" show-icon :closable="false" class="detail-alert" />
            <el-alert
              v-if="job.dead_letter_reason"
              :title="`死信原因：${job.dead_letter_reason}`"
              type="warning"
              show-icon
              :closable="false"
              class="detail-alert"
            />

            <details v-if="parsedMessage || sourceMessageText" class="raw-block panel-lite">
              <summary>{{ parsedMessage ? "原始 JSON" : "原始输入" }}</summary>
              <pre v-if="parsedMessage" class="result-pre">{{ JSON.stringify(parsedMessage, null, 2) }}</pre>
              <pre v-else class="result-pre">{{ sourceMessageText }}</pre>
            </details>
          </aside>
        </div>
      </template>
      <el-empty v-else-if="!loading" description="未找到任务" />
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  cancelAgentJobTask,
  deleteAgentJob,
  executeAgentJob,
  fetchAgentJob,
  updateAgentJobConfig,
} from "../api/agent";
import http from "../api/http";
import { getJobDiagnosisScreenshotPath } from "../utils/acquisitionJobs";

const route = useRoute();
const router = useRouter();

const loading = ref(false);
const executing = ref(false);
const configSaving = ref(false);
const configEditMode = ref("nl");
const configInput = ref("");
const job = ref(null);
let pollTimer = null;

const SUMMARY_LABELS = {
  task_name: "任务名称",
  keyword: "关键词",
  platform: "平台",
  region: "地区",
  target_leads: "目标线索",
  comment_days: "评论天数",
  video_publish_days: "视频发布天数",
  comment_ratio: "评论权重",
  dm_ratio: "私信权重",
  follow_ratio: "关注权重",
  interval_sec: "触达间隔",
  daily_follow_limit: "日关注上限",
  daily_dm_limit: "日私信上限",
};

const STATUS_MAP = {
  pending: "待执行",
  retrying: "重试中",
  queued: "排队中",
  running: "运行中",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
  dead_letter: "死信",
};

const STEP_STATUS_MAP = {
  pending: "待执行",
  running: "进行中",
  completed: "已完成",
  skipped: "跳过",
  failed: "失败",
  cancelled: "已取消",
  dead_letter: "死信",
};

const jobId = computed(() => String(route.params.jobId || ""));

const orchestration = computed(() => {
  const r = job.value?.result;
  if (r?.orchestration && typeof r.orchestration === "object") return r.orchestration;
  return null;
});

const executionNote = computed(() => orchestration.value?.execution_note || "");

const suspendBrief = computed(() => {
  const brief = orchestration.value?.suspend_brief;
  if (brief && typeof brief === "object") return brief;
  const state = job.value?.result?.supervisor_state;
  const diag = state?.page_diagnosis;
  if (job.value?.status === "pending" && state?.suspended) {
    const reason = state.wake_reason || job.value?.result?.summary || "任务已挂起";
    const fromDiag = diag && typeof diag === "object" ? diag : null;
    return {
      reason: fromDiag?.user_title || reason,
      user_summary: fromDiag?.user_summary || "",
      resume_at: state.resume_at || null,
      resume_at_display: formatResumeAt(state.resume_at),
      next_action: state.next_action || "点击「继续执行」从当前进度继续",
      evidence: fromDiag?.evidence || [],
      issue_type: fromDiag?.issue_type || null,
      screenshot_ref: fromDiag?.screenshot_ref || null,
      manual_resume: "您也可随时点击「继续执行」跳过等待，立即恢复运行",
    };
  }
  return null;
});

const suspendEvidence = computed(() => {
  const rows = suspendBrief.value?.evidence;
  return Array.isArray(rows) ? rows.filter(Boolean) : [];
});

const diagnosisScreenshotUrl = ref("");

function revokeDiagnosisScreenshot() {
  if (diagnosisScreenshotUrl.value) {
    URL.revokeObjectURL(diagnosisScreenshotUrl.value);
    diagnosisScreenshotUrl.value = "";
  }
}

async function loadDiagnosisScreenshot() {
  revokeDiagnosisScreenshot();
  const id = jobId.value;
  const ref = suspendBrief.value?.screenshot_ref;
  if (!id || !ref) return;
  try {
    const resp = await http.get(getJobDiagnosisScreenshotPath(id), { responseType: "blob" });
    diagnosisScreenshotUrl.value = URL.createObjectURL(resp.data);
  } catch {
    diagnosisScreenshotUrl.value = "";
  }
}

watch([jobId, () => suspendBrief.value?.screenshot_ref], loadDiagnosisScreenshot);
onUnmounted(revokeDiagnosisScreenshot);

function formatResumeAt(iso) {
  if (!iso) return null;
  try {
    const dt = new Date(iso);
    if (Number.isNaN(dt.getTime())) return String(iso).slice(0, 16);
    return dt.toLocaleString("zh-CN", {
      timeZone: "Asia/Shanghai",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }) + "（北京时间）";
  } catch {
    return String(iso).slice(0, 16);
  }
}

const dedicatedAgent = computed(() => {
  const d = orchestration.value?.dedicated_agent;
  return d && typeof d === "object" ? d : null;
});

const executionNoteType = computed(() => {
  const outcome = job.value?.result?.completion_outcome;
  const status = job.value?.status;
  if (status === "completed" && outcome === "goal_reached") return "success";
  if (status === "completed") return "info";
  if (outcome === "plan_incomplete" || outcome === "quota_exhausted") return "warning";
  if (status === "pending" && job.value?.result?.supervisor_state?.suspended) return "warning";
  if (status === "failed" || status === "dead_letter") return "error";
  if (orchestration.value?.llm_compiled) return "success";
  if (orchestration.value?.is_preview) return "info";
  return "success";
});

const taskBriefMd = computed(() => {
  const brief = orchestration.value?.task_brief;
  if (brief?.brief_md) return String(brief.brief_md);
  return "";
});

const supervisorCycles = computed(() => {
  const cycles = job.value?.result?.supervisor_cycles;
  return Array.isArray(cycles) ? cycles : [];
});

const supervisorCyclesDisplayed = computed(() => supervisorCycles.value.slice().reverse().slice(0, 20));

const taskLedger = computed(() => {
  const ledger = job.value?.result?.task_ledger;
  if (ledger && typeof ledger === "object") return ledger;
  const snapLedger = job.value?.result?.data_snapshot?.task_ledger;
  return snapLedger && typeof snapLedger === "object" ? snapLedger : null;
});

function outreachBucket(stats, key) {
  const bucket = stats?.[key];
  return {
    ok: Number(bucket?.ok || 0),
    failed: Number(bucket?.failed || 0),
  };
}

function dailyQuota(interactionStats, key) {
  const row = interactionStats?.[key];
  return {
    used: Number(row?.count || 0),
    limit: row?.limit ?? null,
    remaining: row?.remaining ?? null,
  };
}

function countCrawlCycles(cycles) {
  let ok = 0;
  let failed = 0;
  for (const cycle of cycles || []) {
    if (cycle?.action !== "crawl_keyword") continue;
    if (cycle?.ok) ok += 1;
    else failed += 1;
  }
  return { ok, failed };
}

const executionStats = computed(() => {
  const result = job.value?.result;
  if (!result || typeof result !== "object") return null;

  const prebuilt = result.execution_stats || result.data_snapshot?.execution_stats;
  const supervisor = result.supervisor_state && typeof result.supervisor_state === "object"
    ? result.supervisor_state
    : {};
  const progress = result.data_snapshot?.progress && typeof result.data_snapshot.progress === "object"
    ? result.data_snapshot.progress
    : {};
  const ledger = taskLedger.value || {};
  const stats = ledger.stats || {};
  const interaction = result.data_snapshot?.interaction_stats || {};
  const crawlCounts = countCrawlCycles(result.supervisor_cycles);

  const reply = outreachBucket(stats, "reply");
  const dm = outreachBucket(stats, "dm");
  const follow = outreachBucket(stats, "follow");
  const targetLeads = Number(
    progress.target_leads
    || orchestration.value?.task_brief?.goals?.target_leads
    || inputSummary.value?.target_leads
    || 0,
  );
  const leadsCollected = Number(progress.leads_collected || supervisor.leads_collected || 0);
  const commentsCaptured = Number(progress.comments_captured || supervisor.comments_captured || 0);
  const commentsPersisted = Number(supervisor.comments_persisted || 0);
  const rawCommentsScanned = Number(supervisor.raw_comments_scanned || 0);
  const progressPct = progress.pct != null
    ? Number(progress.pct)
    : targetLeads
      ? Math.round((100 * leadsCollected) / targetLeads * 10) / 10
      : 0;

  const commentStatus = Array.isArray(ledger.comment_status) ? ledger.comment_status : [];
  const commentsReplied = commentStatus.filter((row) => row?.status === "ok").length;

  const merged = {
    comments_captured: commentsCaptured,
    comments_persisted: commentsPersisted,
    raw_comments_scanned: rawCommentsScanned,
    comments_replied: commentsReplied,
    crawl_done: Boolean(progress.crawl_done || supervisor.crawl_done),
    crawl_success_count: crawlCounts.ok,
    crawl_fail_count: crawlCounts.failed,
    target_leads: targetLeads,
    leads_collected: leadsCollected,
    progress_pct: progressPct,
    reply: { ...reply, daily: dailyQuota(interaction, "reply") },
    dm: { ...dm, daily: dailyQuota(interaction, "dm") },
    follow: { ...follow, daily: dailyQuota(interaction, "follow") },
    total_outreach_ok: Number(
      ledger.total_outreach_ok || reply.ok + dm.ok + follow.ok,
    ),
    sandbox_outreach_ok: Number(result.sandbox_stats?.outreach_ok || 0),
  };

  if (prebuilt && typeof prebuilt === "object") {
    return {
      ...prebuilt,
      ...merged,
      reply: { ...prebuilt.reply, ...merged.reply, daily: merged.reply.daily },
      dm: { ...prebuilt.dm, ...merged.dm, daily: merged.dm.daily },
      follow: { ...prebuilt.follow, ...merged.follow, daily: merged.follow.daily },
    };
  }

  const hasData = (
    merged.comments_captured
    || merged.comments_persisted
    || merged.total_outreach_ok
    || merged.crawl_success_count
    || merged.crawl_fail_count
    || result.execution_mode === "supervisor"
    || result.supervisor_cycles?.length
  );
  return hasData ? merged : null;
});

const sandboxInfo = computed(() => {
  const sb = job.value?.result?.sandbox;
  return sb && typeof sb === "object" ? sb : null;
});

const sandboxStats = computed(() => {
  const stats = job.value?.result?.sandbox_stats;
  return stats && typeof stats === "object" ? stats : null;
});

const canEditConfig = computed(() => {
  const status = job.value?.status;
  return status && status !== "running";
});

const RESTARTABLE_STATUSES = new Set(["pending", "cancelled", "failed", "dead_letter", "completed"]);

const canStartJob = computed(() => RESTARTABLE_STATUSES.has(job.value?.status));

const canDeleteJob = computed(() => RESTARTABLE_STATUSES.has(job.value?.status));

const startJobLabel = computed(() => {
  const status = job.value?.status;
  if (status === "pending" && job.value?.result?.supervisor_state?.suspended) return "继续执行";
  if (status === "pending") return "启动执行";
  if (status === "cancelled") return "重新启动";
  if (status === "failed" || status === "dead_letter") return "重试执行";
  if (status === "completed") return "再次执行";
  return "启动执行";
});

const currentConfigJson = computed(() => {
  const brief = orchestration.value?.task_brief;
  if (!brief || typeof brief !== "object") return "{}";
  return JSON.stringify(
    {
      keyword: brief.keyword,
      platform: brief.platform,
      region: brief.region,
      goals: brief.goals || {},
      constraints: brief.constraints || {},
      success_criteria: brief.success_criteria,
    },
    null,
    2,
  );
});

const configPlaceholder = computed(() => {
  if (configEditMode.value === "json") {
    return '{\n  "goals": { "target_leads": 100 },\n  "constraints": { "outreach_priority": ["dm", "reply", "follow"] }\n}';
  }
  return "例如：把目标改成100条，私信优先；或：关键词改成「企业团餐」，评论抓取近7天";
});

const configUpdates = computed(() => {
  const items = job.value?.result?.config_updates;
  return Array.isArray(items) ? items : [];
});

const runningEmptyHint = computed(() => {
  if (job.value?.result?.execution_mode === "supervisor") {
    return "Supervisor 循环执行中，决策日志将实时更新…";
  }
  return "执行已开始，等待 Supervisor 事件…";
});

const progressEvents = computed(() => {
  const events = job.value?.result?.progress_events;
  return Array.isArray(events) ? events : [];
});

const progressEventsDisplayed = computed(() => progressEvents.value.slice(-50).reverse());

const parsedMessage = computed(() => {
  const fromOrch = orchestration.value?.source_payload;
  if (fromOrch && typeof fromOrch === "object" && Object.keys(fromOrch).length) {
    return fromOrch;
  }
  const text = job.value?.message?.trim();
  if (!text?.startsWith("{")) return null;
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
});

const sourceMessageText = computed(() => {
  const fromOrch = orchestration.value?.source_message;
  if (fromOrch && String(fromOrch).trim()) return String(fromOrch).trim();
  if (parsedMessage.value) return "";
  return job.value?.message?.trim() || "";
});

const orchestrationSteps = computed(() => orchestration.value?.steps || []);

const COMPILE_METHOD_MAP = {
  rule: "规则简报",
  llm: "大模型简报",
  hybrid: "混合简报",
};

const compileMethodLabel = computed(() => {
  const method = orchestration.value?.compile_method;
  if (!method) return "";
  const confidence = orchestration.value?.confidence;
  const label = COMPILE_METHOD_MAP[method] || method;
  if (typeof confidence === "number" && confidence > 0) {
    return `${label} · ${Math.round(confidence * 100)}%`;
  }
  return label;
});

const orchestrationHint = computed(() => {
  const mode = orchestration.value?.execution_mode;
  if (mode === "skill_flow") return "计划驱动 · Skill 分步（无 LLM 决策）";
  const dedicatedMode = dedicatedAgent.value?.execution_mode;
  if (dedicatedMode === "skill_flow") return "计划驱动 · Skill 分步（无 LLM 决策）";
  if (mode === "supervisor") return "Supervisor 混合架构";
  return "编排方案";
});

const inputSummary = computed(() => {
  const fromOrch = orchestration.value?.input_summary;
  if (fromOrch && Object.keys(fromOrch).length) {
    return Object.fromEntries(Object.entries(fromOrch).filter(([, v]) => v != null && v !== ""));
  }
  if (!parsedMessage.value) return null;
  const raw = parsedMessage.value;
  return Object.fromEntries(
    Object.entries({
      task_name: raw.task_name,
      keyword: raw.keyword || raw.product_keyword,
      platform: raw.platform || raw.channel,
      region: raw.region,
      target_leads: raw.target_count || raw.target_leads,
      comment_days: raw.comment_days,
      video_publish_days: raw.video_publish_days,
      comment_ratio: raw.comment_ratio,
      dm_ratio: raw.dm_ratio,
    }).filter(([, v]) => v != null && v !== ""),
  );
});

const jobPlatform = computed(() => {
  const plat = job.value?.platform || inputSummary.value?.platform;
  return plat ? String(plat).trim() : "";
});

const jobKeyword = computed(() => {
  const kw = inputSummary.value?.keyword;
  return kw ? String(kw).trim() : "";
});

const executionSummary = computed(() => job.value?.result?.summary || "");

const heroTitle = computed(() => {
  const name = inputSummary.value?.task_name;
  if (name) return String(name);
  const keyword = inputSummary.value?.keyword;
  if (keyword) return `编排任务 · ${keyword}`;
  return job.value?.job_id ? `编排任务 · ${job.value.job_id.slice(0, 8)}` : "编排任务详情";
});

function summaryLabel(key) {
  return SUMMARY_LABELS[key] || key;
}

function statusLabel(status) {
  return STATUS_MAP[status] || status;
}

function stepStatusLabel(status) {
  return STEP_STATUS_MAP[status] || status || "待执行";
}

function statusTagType(status) {
  if (status === "completed") return "success";
  if (status === "running") return "primary";
  if (status === "retrying") return "warning";
  if (status === "failed" || status === "dead_letter") return "danger";
  if (status === "cancelled") return "info";
  if (status === "pending") return "info";
  return "warning";
}

function stepTagType(status) {
  if (status === "completed") return "success";
  if (status === "running") return "primary";
  if (status === "skipped") return "info";
  if (status === "failed" || status === "dead_letter") return "danger";
  if (status === "cancelled") return "info";
  return "info";
}

function stepStatusClass(status) {
  if (status === "running") return "is-running";
  if (status === "completed") return "is-done";
  if (status === "skipped") return "is-skipped";
  if (status === "failed" || status === "dead_letter" || status === "cancelled") return "is-error";
  return "";
}

function runModeLabel(mode) {
  if (mode === "confirm") return "工具需审批";
  if (mode === "auto") return "工具自动批准";
  return mode || "—";
}

function formatTime(value) {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString("zh-CN");
  } catch {
    return String(value);
  }
}

function formatEventTime(value) {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleTimeString("zh-CN", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return String(value);
  }
}

async function reload() {
  if (!jobId.value) return;
  loading.value = true;
  try {
    job.value = await fetchAgentJob(jobId.value);
  } catch (err) {
    ElMessage.error(err.message || "加载任务详情失败");
  } finally {
    loading.value = false;
  }
}

async function executeJob() {
  if (!jobId.value) return;
  executing.value = true;
  try {
    job.value = await executeAgentJob(jobId.value);
    ElMessage.success("任务已启动");
    schedulePoll();
  } catch (err) {
    ElMessage.error(err.message || "启动任务失败");
  } finally {
    executing.value = false;
  }
}

async function cancelJob() {
  if (!jobId.value) return;
  try {
    await cancelAgentJobTask(jobId.value);
    ElMessage.success("已取消任务");
    await reload();
  } catch (err) {
    ElMessage.error(err.message || "取消任务失败");
  }
}

async function deleteJob() {
  if (!jobId.value) return;
  try {
    await ElMessageBox.confirm(
      "确定删除此任务？沙盒与执行记录将一并清除，不可恢复。",
      "删除任务",
      { type: "warning", confirmButtonText: "删除", cancelButtonText: "取消" },
    );
    await deleteAgentJob(jobId.value);
    ElMessage.success("任务已删除");
    router.push("/tasks");
  } catch (err) {
    if (err === "cancel" || err?.message === "cancel") return;
    ElMessage.error(err.message || "删除任务失败");
  }
}

function resetConfigJson() {
  configInput.value = currentConfigJson.value;
}

async function applyConfigUpdate() {
  if (!jobId.value || !configInput.value.trim()) return;
  configSaving.value = true;
  try {
    const payload =
      configEditMode.value === "json"
        ? { config: JSON.parse(configInput.value) }
        : { message: configInput.value.trim() };
    job.value = await updateAgentJobConfig(jobId.value, payload);
    ElMessage.success("配置已更新");
    configInput.value = "";
  } catch (err) {
    ElMessage.error(err.message || "更新配置失败");
  } finally {
    configSaving.value = false;
  }
}

function openRun() {
  if (!job.value?.run_id) return;
  localStorage.setItem("huoke_agent_run_id", job.value.run_id);
  router.push("/agent");
}

function schedulePoll() {
  if (pollTimer) clearInterval(pollTimer);
  const active = job.value && ["running", "queued", "retrying"].includes(job.value.status);
  if (!active) return;
  pollTimer = setInterval(() => reload(), 2500);
}

watch(
  () => [jobId.value, job.value?.status],
  () => schedulePoll(),
);

watch(jobId, () => {
  reload();
});

onMounted(() => {
  reload();
});

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer);
});
</script>

<style scoped>
.agent-job-detail {
  display: flex;
  flex-direction: column;
  gap: 12px;
  width: 100%;
  padding-bottom: 16px;
}

.detail-hero {
  padding: 18px 20px;
}

.hero-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  flex-wrap: wrap;
}

.hero-title {
  margin: 0 0 8px;
  font-size: 22px;
  font-weight: 700;
  color: var(--primary, #0f172a);
}

.hero-tags {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.stage-text {
  font-size: 13px;
  color: #64748b;
}

.hero-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.hero-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 16px 24px;
  margin-top: 14px;
  font-size: 13px;
  color: #475569;
}

.meta-item em {
  font-style: normal;
  color: #94a3b8;
  margin-right: 6px;
}

.meta-item code {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
}

.detail-body {
  min-height: 200px;
}

.top-note {
  margin-bottom: 12px;
}

.detail-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.6fr) minmax(280px, 1fr);
  gap: 12px;
  align-items: start;
}

.detail-main,
.detail-side {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.progress-list {
  margin: 0;
  padding: 0;
  list-style: none;
  max-height: 480px;
  overflow: auto;
}

.progress-list li {
  display: flex;
  gap: 12px;
  padding: 8px 0;
  border-bottom: 1px dashed #e2e8f0;
  font-size: 13px;
}

.evt-time {
  flex-shrink: 0;
  color: #94a3b8;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}

.evt-label {
  color: #334155;
}

.progress-more {
  margin: 8px 0 0;
  font-size: 12px;
  color: #94a3b8;
}

.brief-pre {
  margin: 0;
  padding: 12px;
  background: #f8fafc;
  border-radius: 8px;
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-wrap;
  color: #334155;
  max-height: 360px;
  overflow: auto;
}

.cycle-list {
  margin: 0;
  padding: 0;
  list-style: none;
}

.cycle-item {
  padding: 10px 0;
  border-bottom: 1px dashed #e2e8f0;
}

.cycle-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.cycle-num {
  font-size: 12px;
  font-weight: 600;
  color: #64748b;
}

.cycle-reason,
.cycle-result {
  margin: 4px 0 0;
  font-size: 13px;
  line-height: 1.5;
  color: #475569;
}

.cycle-result {
  color: #94a3b8;
  font-size: 12px;
}

.ledger-sublist {
  margin: 8px 0 0;
  padding-left: 16px;
  font-size: 12px;
  color: #64748b;
}

.ledger-sublist li {
  margin-bottom: 4px;
}

.small-path {
  font-size: 11px;
  word-break: break-all;
}

.sandbox-hint {
  margin: 8px 0 0;
  font-size: 12px;
  color: #94a3b8;
}

.config-mode {
  margin-bottom: 10px;
}

.config-textarea {
  width: 100%;
}

.config-actions {
  display: flex;
  gap: 8px;
  margin-top: 10px;
}

.config-hint {
  margin: 10px 0 0;
  font-size: 12px;
  color: #94a3b8;
  line-height: 1.5;
}

.config-history {
  margin: 12px 0 0;
  padding-left: 18px;
  font-size: 12px;
  color: #64748b;
}

.config-history li {
  margin-bottom: 6px;
}

.sub-steps {
  margin: 8px 0 0;
  padding-left: 16px;
  list-style: disc;
  font-size: 12px;
  color: #64748b;
}

.sub-steps li {
  margin-bottom: 4px;
}

.sub-weight {
  margin-left: 6px;
  color: #94a3b8;
}

.sub-desc {
  display: block;
  margin-top: 2px;
  color: #94a3b8;
}

.execution-stats {
  margin-bottom: 16px;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 12px;
}

.stat-card {
  padding: 12px 14px;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
}

.stat-card--wide {
  grid-column: span 2;
}

.stat-value {
  font-size: 28px;
  font-weight: 700;
  line-height: 1.2;
  color: #0f172a;
}

.stat-value--split {
  display: flex;
  align-items: baseline;
  gap: 4px;
}

.stat-ok {
  color: #16a34a;
}

.stat-fail {
  color: #dc2626;
  font-size: 22px;
}

.stat-sep {
  color: #cbd5e1;
  font-size: 20px;
  font-weight: 500;
}

.stat-target {
  font-size: 16px;
  font-weight: 500;
  color: #94a3b8;
}

.stat-label {
  margin-top: 4px;
  font-size: 13px;
  font-weight: 600;
  color: #475569;
}

.stat-sub {
  margin-top: 6px;
  font-size: 12px;
  line-height: 1.45;
  color: #94a3b8;
}

.stat-progress {
  margin-top: 8px;
}

@media (max-width: 720px) {
  .stat-card--wide {
    grid-column: span 1;
  }
}

.panel-lite {
  padding: 14px 16px;
  background: #f8fafc;
  border-radius: 10px;
}

.block-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 10px;
}

.block-title {
  margin: 0 0 8px;
  font-size: 14px;
  font-weight: 600;
  color: #475569;
}

.block-head .block-title {
  margin: 0;
}

.block-hint {
  font-size: 12px;
  color: #94a3b8;
}

.summary-grid {
  display: grid;
  grid-template-columns: 100px 1fr;
  gap: 8px 16px;
  margin: 0;
  font-size: 13px;
}

.summary-grid dt {
  margin: 0;
  color: #94a3b8;
}

.summary-grid dd {
  margin: 0;
  color: #334155;
}

.workflow-steps {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.workflow-step {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 12px 14px;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
}

.workflow-step.is-running {
  border-color: var(--el-color-primary-light-5);
  background: #eff6ff;
}

.workflow-step.is-done {
  border-color: #bbf7d0;
  background: #f0fdf4;
}

.workflow-step.is-error {
  border-color: #fecaca;
  background: #fef2f2;
}

.step-index {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: #e2e8f0;
  color: #475569;
  font-size: 13px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.step-body {
  flex: 1;
  min-width: 0;
}

.step-id {
  font-size: 12px;
  font-weight: 600;
  color: #64748b;
  text-transform: uppercase;
}

.step-action {
  font-size: 15px;
  color: #1e293b;
  margin-top: 2px;
}

.step-cap {
  font-size: 12px;
  color: #94a3b8;
  margin-top: 4px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}

.orch-reason {
  margin: 10px 0 0;
  font-size: 12px;
  color: #64748b;
}

.orch-unmapped {
  margin: 6px 0 0;
  font-size: 12px;
  color: #b45309;
}

.task-link {
  display: inline-block;
  margin-top: 8px;
  font-size: 13px;
}

.meta-grid {
  display: grid;
  grid-template-columns: 88px 1fr;
  gap: 10px 12px;
  margin: 0;
  font-size: 13px;
}

.meta-grid dt {
  margin: 0;
  color: #94a3b8;
}

.meta-grid dd {
  margin: 0;
  color: #334155;
  word-break: break-word;
}

.message-cell {
  white-space: pre-wrap;
  line-height: 1.5;
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
}

.link-code {
  color: var(--el-color-primary);
  cursor: pointer;
}

.link-code:hover {
  text-decoration: underline;
}

.muted {
  color: #cbd5e1;
}

.detail-alert {
  margin-top: 0;
}

.suspend-brief {
  margin: 4px 0 0;
  font-size: 13px;
  line-height: 1.6;
  color: #334155;
}

.suspend-brief p {
  margin: 6px 0 0;
}

.suspend-summary {
  color: #64748b;
}

.suspend-evidence {
  margin: 6px 0 0;
  padding-left: 18px;
  color: #64748b;
  font-size: 12px;
}

.suspend-screenshot-wrap {
  margin-top: 10px;
}

.suspend-screenshot {
  max-width: 100%;
  max-height: 220px;
  object-fit: contain;
  border-radius: 6px;
  border: 1px solid #e2e8f0;
  background: #fff;
}

.suspend-hint {
  color: #64748b;
  font-size: 12px;
}

.raw-block summary {
  cursor: pointer;
  font-size: 13px;
  color: #64748b;
}

.exec-summary {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
  color: #334155;
}

.result-pre {
  margin: 8px 0 0;
  padding: 12px;
  background: #fff;
  border-radius: 8px;
  font-size: 12px;
  overflow: auto;
  max-height: 400px;
}

@media (max-width: 900px) {
  .detail-grid {
    grid-template-columns: 1fr;
  }
}
</style>
