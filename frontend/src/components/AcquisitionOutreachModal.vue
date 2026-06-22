<template>
  <el-dialog
    v-model="visible"
    :title="dialogTitle"
    width="1180px"
    destroy-on-close
    align-center
    modal-class="outreach-dialog-overlay"
    class="outreach-dialog"
    @closed="resetState"
  >
    <div v-if="job" class="outreach-body">
      <div class="outreach-header">
        <div class="view-tabs">
          <el-radio-group v-model="activeView" size="small" @change="page = 1">
            <el-radio-button
              v-for="item in viewOptions"
              :key="item.value"
              :value="item.value"
            >
              {{ item.label }} ({{ item.count }})
            </el-radio-button>
          </el-radio-group>
        </div>

        <div class="outreach-toolbar">
          <span class="toolbar-label">评论筛选</span>
          <el-input
            v-model="keyword"
            placeholder="输入原评论、评论内容、私信内容关键词"
            clearable
            @keyup.enter="page = 1"
          />
          <el-select v-model="actionType" style="width: 140px" @change="page = 1">
            <el-option label="全部类型" value="all" />
            <el-option label="评论" value="comment" />
            <el-option label="私信" value="dm" />
          </el-select>
          <el-button type="primary" @click="page = 1">查询</el-button>
        </div>

        <div class="summary-grid">
          <div><span class="summary-label">任务名称</span><div>{{ rowModel?.name || "—" }}</div></div>
          <div><span class="summary-label">渠道</span><div>{{ platformLabel(rowModel?.platform) }}</div></div>
          <div><span class="summary-label">采集几天内评论</span><div>{{ commentDaysLabel }}</div></div>
        </div>

        <el-alert
          v-if="emptyHint"
          type="warning"
          :closable="false"
          :title="emptyHint"
          show-icon
          class="empty-hint"
        />
      </div>

      <div class="outreach-table-wrap">
        <el-table v-loading="loading || tableLoading" :data="pageRows" stripe empty-text="暂无触达数据">
          <el-table-column prop="nickname" label="用户昵称" width="120" show-overflow-tooltip />
          <el-table-column label="头像" width="72">
            <template #default="{ row }">
              <UserAvatar :src="row.avatar" :fallback="avatarInitial(row.nickname)" :size="28" />
            </template>
          </el-table-column>
          <el-table-column prop="comment_at" label="评论时间" width="140">
            <template #default="{ row }">{{ formatJobTime(row.comment_at) }}</template>
          </el-table-column>
          <el-table-column prop="video_title" label="视频名称" min-width="140" show-overflow-tooltip />
          <el-table-column prop="comment_content" label="原评论" min-width="160" show-overflow-tooltip />
          <el-table-column label="精准评论" width="88">
            <template #default="{ row }">
              <el-tag :type="row.is_precise ? 'success' : 'info'" size="small">
                {{ row.is_precise ? "是" : "否" }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="evaluation_reason" label="评估说明" min-width="180" show-overflow-tooltip />
          <el-table-column prop="reply_content" label="评论内容" min-width="140" show-overflow-tooltip />
          <el-table-column prop="dm_content" label="私信内容" min-width="140" show-overflow-tooltip />
          <el-table-column v-if="showOutreachStatus" label="触达状态" width="100">
            <template #default="{ row }">
              <el-tag
                :type="String(row.outreach_status).toLowerCase() === 'ok' ? 'success' : 'danger'"
                size="small"
              >
                {{ String(row.outreach_status).toLowerCase() === "ok" ? "成功" : "失败" }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column
            v-if="showOutreachStatus"
            prop="outreach_error"
            label="失败原因"
            min-width="160"
            show-overflow-tooltip
          />
          <el-table-column prop="location_text" label="位置" width="100" show-overflow-tooltip />
          <el-table-column prop="executed_at" label="触达时间" width="140">
            <template #default="{ row }">{{ formatJobTime(row.executed_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="140" fixed="right">
            <template #default="{ row }">
              <el-button v-if="row.video_url" link type="primary" size="small" @click="openLink(row.video_url)">
                查看视频
              </el-button>
              <el-button v-if="row.profile_url" link type="primary" size="small" @click="openLink(row.profile_url)">
                查看主页
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <div class="pager-row">
        <span class="pager-text">
          共 {{ filteredRows.length }} 条，当前显示 {{ pageStart }}-{{ pageEnd }}
        </span>
        <el-pagination
          v-model:current-page="page"
          :page-size="pageSize"
          layout="prev, pager, next"
          :total="filteredRows.length"
          background
          small
        />
      </div>
    </div>
  </el-dialog>
</template>

<script setup>
import { computed, ref, watch } from "vue";
import UserAvatar from "./UserAvatar.vue";
import {
  avatarInitial,
  filterOutreachRows,
  formatJobTime,
  getJobRowModel,
  getMetricViewCounts,
  getRowsForMetricView,
  OUTREACH_METRIC_VIEWS,
  OUTREACH_METRIC_VIEW_LABELS,
  platformLabel,
} from "../utils/acquisitionJobs";

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  job: { type: Object, default: null },
  initialView: { type: String, default: OUTREACH_METRIC_VIEWS.ALL },
  loading: { type: Boolean, default: false },
});

const emit = defineEmits(["update:modelValue"]);

const visible = ref(false);
const keyword = ref("");
const actionType = ref("all");
const page = ref(1);
const pageSize = 10;
const tableLoading = ref(false);
const activeView = ref(OUTREACH_METRIC_VIEWS.ALL);

watch(
  () => props.modelValue,
  (value) => {
    visible.value = value;
    if (value) activeView.value = props.initialView || OUTREACH_METRIC_VIEWS.ALL;
  },
  { immediate: true },
);

watch(
  () => props.initialView,
  (value) => {
    if (visible.value && value) activeView.value = value;
  },
);

watch(visible, (value) => {
  emit("update:modelValue", value);
});

const rowModel = computed(() => (props.job ? getJobRowModel(props.job) : null));

const dialogTitle = computed(() => {
  const label = OUTREACH_METRIC_VIEW_LABELS[activeView.value] || "全部采集";
  return `查看数据 · ${label}`;
});

const viewOptions = computed(() => {
  if (!props.job) return [];
  const counts = getMetricViewCounts(props.job);
  return [
    { value: OUTREACH_METRIC_VIEWS.ALL, label: "全部采集", count: counts[OUTREACH_METRIC_VIEWS.ALL] || 0 },
    { value: OUTREACH_METRIC_VIEWS.PRECISE, label: "精准线索", count: counts[OUTREACH_METRIC_VIEWS.PRECISE] || 0 },
    { value: OUTREACH_METRIC_VIEWS.REPLY, label: "已回复", count: counts[OUTREACH_METRIC_VIEWS.REPLY] || 0 },
    { value: OUTREACH_METRIC_VIEWS.DM, label: "已私信", count: counts[OUTREACH_METRIC_VIEWS.DM] || 0 },
    { value: OUTREACH_METRIC_VIEWS.FOLLOW, label: "关注记录", count: counts[OUTREACH_METRIC_VIEWS.FOLLOW] || 0 },
  ];
});

const showOutreachStatus = computed(() =>
  [OUTREACH_METRIC_VIEWS.REPLY, OUTREACH_METRIC_VIEWS.DM, OUTREACH_METRIC_VIEWS.FOLLOW].includes(activeView.value),
);

const commentDaysLabel = computed(() => {
  const days = String(rowModel.value?.config?.comment_days ?? "3");
  const map = { 0: "不限", 3: "3天", 5: "5天", 7: "7天" };
  return map[days] || `${days}天`;
});

const allRows = computed(() => (props.job ? getRowsForMetricView(props.job, activeView.value) : []));

const filteredRows = computed(() =>
  filterOutreachRows(allRows.value, { keyword: keyword.value, actionType: actionType.value }),
);

const pageRows = computed(() => {
  const start = (page.value - 1) * pageSize;
  return filteredRows.value.slice(start, start + pageSize);
});

const pageStart = computed(() => (filteredRows.value.length ? (page.value - 1) * pageSize + 1 : 0));
const pageEnd = computed(() => Math.min(page.value * pageSize, filteredRows.value.length));

const emptyHint = computed(() => {
  if (!props.job || props.loading) return "";
  const commentsCaptured = Number(
    props.job?.sync?.progress?.comments_captured
    || rowModel.value?.metrics?.produced_total
    || 0,
  );
  if (filteredRows.value.length > 0) return "";
  if (commentsCaptured > 0) {
    return `任务已采集 ${commentsCaptured} 条评论，暂无触达记录。请刷新列表后重试，或前往「抓取数据」页查看完整评论库。`;
  }
  return "暂无采集或触达数据，任务执行后将在此展示。";
});

function openLink(url) {
  if (!url) return;
  window.open(url, "_blank", "noopener,noreferrer");
}

function resetState() {
  keyword.value = "";
  actionType.value = "all";
  page.value = 1;
  activeView.value = props.initialView || OUTREACH_METRIC_VIEWS.ALL;
}
</script>

<style scoped>
.outreach-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
  height: 100%;
  min-height: 0;
}

.outreach-header {
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.outreach-table-wrap {
  flex: 1;
  min-height: 180px;
  overflow: auto;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
}

.view-tabs {
  overflow-x: auto;
}

.view-tabs :deep(.el-radio-group) {
  flex-wrap: nowrap;
}

.outreach-toolbar {
  display: flex;
  gap: 10px;
  align-items: center;
}

.toolbar-label {
  font-size: 14px;
  font-weight: 500;
  white-space: nowrap;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  border: 1px solid var(--el-border-color-light);
  border-radius: 10px;
  padding: 14px 16px;
  background: var(--el-fill-color-light);
}

.summary-label {
  display: block;
  margin-bottom: 4px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.pager-row {
  flex-shrink: 0;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.pager-text {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}
</style>

<style>
/* 弹层挂载在 body，需全局样式；水平居中于侧栏右侧主内容区 */
.outreach-dialog-overlay.el-overlay .el-overlay-dialog {
  padding-left: var(--sidebar-width, 240px);
  box-sizing: border-box;
}

.outreach-dialog.el-dialog {
  display: flex;
  flex-direction: column;
  max-height: min(88vh, 920px);
  margin: 6vh auto;
}

.outreach-dialog .el-dialog__header {
  flex-shrink: 0;
  margin-right: 0;
}

.outreach-dialog .el-dialog__body {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  padding-top: 8px;
}

@media (max-width: 900px) {
  .outreach-dialog-overlay.el-overlay .el-overlay-dialog {
    padding-left: 0;
  }

  .outreach-dialog.el-dialog {
    max-height: 92vh;
    margin: 4vh auto;
  }
}
</style>
