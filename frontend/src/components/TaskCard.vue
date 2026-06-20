<template>
  <article
    class="task-card panel"
    :class="[`status-${task.status}`, { 'is-active': isRunning }]"
    tabindex="0"
    @click="$emit('open', task.task_id)"
    @keydown.enter="$emit('open', task.task_id)"
  >
    <header class="card-head">
      <div class="card-title-wrap">
        <h3 class="card-title">{{ task.name || task.spec?.keyword || "未命名任务" }}</h3>
        <p class="card-id">{{ task.task_id }}</p>
      </div>
      <el-tag :type="statusTagType" size="small" effect="light">{{ statusLabel }}</el-tag>
    </header>

    <div class="card-keywords">
      <span class="keyword">{{ task.spec?.keyword || "-" }}</span>
      <span class="dot">·</span>
      <span>{{ platformLabel }}</span>
    </div>

    <div class="card-tags">
      <el-tag size="small" type="info" effect="plain">{{ task.template_id }}</el-tag>
      <el-tag v-if="compileLabel" size="small" effect="plain">{{ compileLabel }}</el-tag>
      <el-tag size="small" :type="task.source === 'external' ? 'warning' : ''" effect="plain">
        {{ task.source === "external" ? "外部" : "本地" }}
      </el-tag>
      <el-tag v-if="task.auto_restart !== false" size="small" type="success" effect="plain">
        自动重启 {{ task.retry_count ?? 0 }}/{{ task.max_retries ?? 0 }}
      </el-tag>
      <el-tag v-else size="small" effect="plain">失败即停</el-tag>
    </div>

    <div class="card-progress">
      <div class="progress-label">
        <span>{{ phaseText }}</span>
        <span>{{ progressText }}</span>
      </div>
      <el-progress :percentage="task.progress?.overall_percent || 0" :stroke-width="8" :show-text="false" />
    </div>

    <footer class="card-foot" @click.stop>
      <span class="time">{{ createdText }}</span>
      <div class="foot-actions">
        <el-button v-if="canStart" size="small" type="success" plain @click="$emit('submit', task)">
          开始执行
        </el-button>
        <el-button v-if="canContinue" size="small" type="success" plain @click="$emit('continue', task)">
          继续执行
        </el-button>
        <el-button v-if="canDelete" size="small" type="danger" plain @click="$emit('delete', task)">
          删除
        </el-button>
        <el-button size="small" type="primary" link @click="$emit('open', task.task_id)">查看详情</el-button>
      </div>
    </footer>
  </article>
</template>

<script setup>
import { computed } from "vue";

const props = defineProps({
  task: { type: Object, required: true },
});

defineEmits(["open", "submit", "continue", "delete"]);

const TERMINAL_STATUSES = ["failed", "dead_letter", "completed", "cancelled"];

const STATUS_MAP = {
  scheduled: "已预约",
  queued: "排队中",
  running: "运行中",
  retrying: "重试中",
  paused: "已暂停",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
  dead_letter: "死信",
};

const PLATFORM_MAP = {
  douyin: "抖音",
  xiaohongshu: "小红书",
  kuaishou: "快手",
};

const statusLabel = computed(() => STATUS_MAP[props.task.status] || props.task.status);

const statusTagType = computed(() => {
  const s = props.task.status;
  if (s === "completed") return "success";
  if (s === "running") return "primary";
  if (s === "retrying") return "warning";
  if (s === "failed" || s === "dead_letter") return "danger";
  if (s === "paused") return "warning";
  if (s === "scheduled") return "warning";
  return "info";
});

const isRunning = computed(() => ["running", "retrying"].includes(props.task.status));

const platformLabel = computed(
  () => PLATFORM_MAP[props.task.platform] || props.task.platform || "-",
);

const compileLabel = computed(() => {
  const method = props.task.compile_plan?.method;
  if (method === "rule") return "规则编排";
  if (method === "llm") return "LLM 编排";
  if (method === "hybrid") return "混合编排";
  return "";
});

const phaseText = computed(() => {
  if (props.task.current_phase) return props.task.current_phase;
  if (props.task.status === "queued") return "排队中";
  if (props.task.status === "retrying") return "重试中";
  if (props.task.status === "scheduled") return "等待定时";
  if (props.task.status === "completed") return "已完成";
  return "—";
});

const progressText = computed(() => {
  const crawl = props.task.progress?.crawl || {};
  const done = crawl.done ?? 0;
  const total = crawl.total ?? 0;
  if (total > 0) return `${done}/${total}`;
  const pct = props.task.progress?.overall_percent;
  return pct != null ? `${pct}%` : "0%";
});

const canStart = computed(() => {
  const s = props.task.status;
  return s === "queued" || s === "paused" || s === "scheduled";
});

const canContinue = computed(() => TERMINAL_STATUSES.includes(props.task.status));

const canDelete = computed(() => props.task.status && props.task.status !== "running");

const createdText = computed(() => {
  if (props.task.status === "scheduled" && props.task.scheduled_at) {
    try {
      return `计划 ${new Date(props.task.scheduled_at).toLocaleString("zh-CN", {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      })}`;
    } catch {
      return "";
    }
  }
  if (!props.task.created_at) return "";
  try {
    return new Date(props.task.created_at).toLocaleString("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return "";
  }
});
</script>

<style scoped>
.task-card {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
  cursor: pointer;
  transition: box-shadow 0.2s, transform 0.15s, border-color 0.2s;
  border: 1px solid var(--border, #e8e8e8);
  min-height: 196px;
}

.task-card:hover,
.task-card:focus-visible {
  border-color: var(--el-color-primary-light-5);
  box-shadow: 0 6px 20px rgba(64, 158, 255, 0.12);
  transform: translateY(-2px);
  outline: none;
}

.task-card.status-running {
  border-color: var(--el-color-primary-light-7);
}

.task-card.is-active {
  background: linear-gradient(180deg, #f5f9ff 0%, #fff 40%);
}

.card-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 10px;
}

.card-title-wrap {
  min-width: 0;
  flex: 1;
}

.card-title {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  line-height: 1.35;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.card-id {
  margin: 4px 0 0;
  font-size: 11px;
  color: #aaa;
  font-family: ui-monospace, monospace;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.card-keywords {
  font-size: 13px;
  color: #555;
}

.keyword {
  font-weight: 500;
  color: #333;
}

.dot {
  margin: 0 4px;
  color: #ccc;
}

.card-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.card-progress {
  margin-top: auto;
}

.progress-label {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: #888;
  margin-bottom: 6px;
}

.card-foot {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  padding-top: 4px;
  border-top: 1px dashed #eee;
}

.time {
  font-size: 11px;
  color: #aaa;
}

.foot-actions {
  display: flex;
  gap: 4px;
  align-items: center;
}
</style>
