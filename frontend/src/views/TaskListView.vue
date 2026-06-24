<template>
  <div class="task-hub">
    <header class="hub-header panel">
      <div class="hub-brand">
        <h1 class="hub-title">任务编排</h1>
        <p class="hub-desc">
          用自然语言或 JSON 描述需求，选择执行策略（类人分步），由<strong>平台专用智能体</strong>按 Skill 白名单执行；
          通用对话请使用「智能体助手」。
        </p>
      </div>
      <div class="hub-actions">
        <el-button :loading="refreshing" @click="refreshCurrent">刷新</el-button>
        <el-button type="primary" @click="agentCreateVisible = true">创建任务</el-button>
      </div>
    </header>

    <el-alert v-if="errorMessage" :title="errorMessage" type="error" show-icon :closable="false" />

    <section class="hub-body panel">
      <div class="stats-row">
        <button
          v-for="stat in statCards"
          :key="stat.key"
          type="button"
          class="stat-card"
          :class="{ active: statusFilter === stat.filterValue }"
          @click="statusFilter = stat.filterValue"
        >
          <span class="stat-num">{{ stat.count }}</span>
          <span class="stat-label">{{ stat.label }}</span>
        </button>
      </div>

      <TaskAgentJobsPanel
        ref="agentPanelRef"
        :status-filter="statusFilter"
        :active="true"
        @jobs-updated="onJobsUpdated"
        @create="agentCreateVisible = true"
      />
    </section>

    <AgentJobCreateDialog
      v-model:visible="agentCreateVisible"
      :submitting="jobSubmitting"
      @submit="onCreateAgentJob"
    />
  </div>
</template>

<script setup>
import { computed, ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import TaskAgentJobsPanel from "../components/TaskAgentJobsPanel.vue";
import AgentJobCreateDialog from "../components/AgentJobCreateDialog.vue";
import { submitAgentJob } from "../api/agent";

const router = useRouter();

const refreshing = ref(false);
const errorMessage = ref("");
const agentJobs = ref([]);
const statusFilter = ref("");
const agentCreateVisible = ref(false);
const jobSubmitting = ref(false);
const agentPanelRef = ref(null);

const statCards = computed(() => {
  const list = agentJobs.value;
  return [
    { key: "all", label: "全部", filterValue: "", count: list.length },
    { key: "running", label: "运行中", filterValue: "running", count: list.filter((j) => j.status === "running").length },
    { key: "queued", label: "排队", filterValue: "queued", count: list.filter((j) => j.status === "queued").length },
    { key: "pending", label: "待执行", filterValue: "pending", count: list.filter((j) => j.status === "pending").length },
    { key: "completed", label: "已完成", filterValue: "completed", count: list.filter((j) => j.status === "completed").length },
    {
      key: "failed",
      label: "失败",
      filterValue: "failed",
      count: list.filter((j) => j.status === "failed" || j.status === "dead_letter").length,
    },
  ];
});

function onJobsUpdated(list) {
  agentJobs.value = Array.isArray(list) ? list : [];
  errorMessage.value = "";
}

async function refreshCurrent() {
  refreshing.value = true;
  try {
    await agentPanelRef.value?.loadJobs?.();
  } catch (err) {
    errorMessage.value = err.message || "加载任务失败";
  } finally {
    refreshing.value = false;
  }
}

async function onCreateAgentJob(payload) {
  jobSubmitting.value = true;
  try {
    const job = await submitAgentJob(payload);
    const method = job?.result?.orchestration?.compile_method;
    const tpl = job?.result?.orchestration?.template_name;
    if (job?.result?.orchestration?.llm_fallback) {
      ElMessage.warning("大模型未配置，已回退规则编译；请登录盈小蚁后重试");
    } else if (method === "hybrid" || method === "llm") {
      ElMessage.success(tpl ? `大模型已理解任务，编排方案：${tpl}` : "大模型已理解任务并生成编排");
    } else if (payload.auto_execute) {
      ElMessage.success("任务已创建并入队执行");
    } else {
      ElMessage.success("任务已创建，可在详情页启动执行");
    }
    agentCreateVisible.value = false;
    await agentPanelRef.value?.loadJobs?.();
    if (job?.job_id) {
      router.push(`/tasks/jobs/${job.job_id}`);
    }
  } catch (err) {
    ElMessage.error(err.message || "提交失败");
  } finally {
    jobSubmitting.value = false;
  }
}
</script>

<style scoped>
.task-hub {
  display: flex;
  flex-direction: column;
  gap: 12px;
  width: 100%;
  padding-bottom: 8px;
}

.hub-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  padding: 18px 20px;
}

.hub-title {
  margin: 0 0 6px;
  font-size: 22px;
  font-weight: 700;
  color: var(--primary);
}

.hub-desc {
  margin: 0;
  color: var(--muted);
  font-size: 14px;
  line-height: 1.5;
  max-width: 640px;
}

.hub-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

.hub-body {
  padding: 12px 16px 16px;
}

.stats-row {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(100px, 1fr));
  gap: 8px;
  margin-bottom: 12px;
}

.stat-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 12px 8px;
  border: 1px solid var(--border, #e2e8f0);
  border-radius: 10px;
  cursor: pointer;
  background: #fff;
  transition: border-color 0.15s, background 0.15s;
}

.stat-card:hover,
.stat-card.active {
  border-color: var(--el-color-primary-light-5);
  background: var(--el-color-primary-light-9);
}

.stat-num {
  font-size: 20px;
  font-weight: 700;
}

.stat-label {
  font-size: 12px;
  color: var(--muted);
}

@media (max-width: 760px) {
  .hub-header {
    flex-direction: column;
  }
}
</style>
