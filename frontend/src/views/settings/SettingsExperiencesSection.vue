<template>
  <section class="settings-section panel">
    <header class="section-head">
      <h2 class="section-title">经验库</h2>
      <p class="section-desc">从成功/失败对话中提炼经验，在相似任务时注入系统提示（做梦）。</p>
    </header>

    <div class="toolbar-row">
      <el-button type="primary" :loading="dreamConsolidating" @click="runDreamConsolidate">整理历史对话</el-button>
      <el-button :loading="dreamRunLoading" @click="dreamCurrentRun">提炼当前对话</el-button>
      <el-button @click="loadExperiences">刷新</el-button>
    </div>

    <el-table
      :data="experiences"
      stripe
      highlight-current-row
      @current-change="(row) => (selectedExperience = row)"
    >
      <el-table-column prop="title" label="任务" min-width="180" show-overflow-tooltip />
      <el-table-column prop="outcome" label="结果" width="88">
        <template #default="{ row }">
          <el-tag
            size="small"
            :type="row.outcome === 'success' ? 'success' : row.outcome === 'failure' ? 'danger' : 'warning'"
          >
            {{ { success: "成功", failure: "失败", partial: "部分" }[row.outcome] || row.outcome }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="enabled" label="启用" width="80">
        <template #default="{ row }">
          <el-switch v-model="row.enabled" size="small" @change="toggleExperience(row)" />
        </template>
      </el-table-column>
      <el-table-column label="操作" width="88">
        <template #default="{ row }">
          <el-button link type="danger" size="small" @click="removeExperience(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div v-if="selectedExperience" class="experience-detail">
      <h4>{{ selectedExperience.title }}</h4>
      <p>{{ selectedExperience.lesson }}</p>
      <div v-if="selectedExperience.do_tips?.length">
        <strong>建议做法</strong>
        <ul>
          <li v-for="(tip, i) in selectedExperience.do_tips" :key="'do-' + i">{{ tip }}</li>
        </ul>
      </div>
      <div v-if="selectedExperience.avoid_tips?.length">
        <strong>应避免</strong>
        <ul>
          <li v-for="(tip, i) in selectedExperience.avoid_tips" :key="'av-' + i">{{ tip }}</li>
        </ul>
      </div>
    </div>
  </section>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  consolidateDreams,
  deleteExperience,
  dreamFromRun,
  fetchExperiences,
  toggleExperienceEnabled,
} from "../../api/agent";

const RUN_STORAGE_KEY = "huoke_agent_run_id";

const experiences = ref([]);
const selectedExperience = ref(null);
const dreamConsolidating = ref(false);
const dreamRunLoading = ref(false);
const dreamAutoLoading = ref(false);

async function loadExperiences() {
  try {
    if (!dreamAutoLoading.value) {
      dreamAutoLoading.value = true;
      try {
        await consolidateDreams(40, false);
      } catch {
        /* ignore */
      } finally {
        dreamAutoLoading.value = false;
      }
    }
    const data = await fetchExperiences();
    experiences.value = data.items || [];
    if (!selectedExperience.value && experiences.value.length) {
      selectedExperience.value = experiences.value[0];
    }
  } catch (err) {
    ElMessage.error(err.message || "加载经验库失败");
  }
}

async function runDreamConsolidate() {
  dreamConsolidating.value = true;
  try {
    const result = await consolidateDreams(40, false);
    ElMessage.success(`已提炼 ${result.created?.length || 0} 条经验，跳过 ${result.skipped?.length || 0} 条`);
    await loadExperiences();
  } catch (err) {
    ElMessage.error(err.message || "整理失败");
  } finally {
    dreamConsolidating.value = false;
  }
}

async function dreamCurrentRun() {
  const runId = localStorage.getItem(RUN_STORAGE_KEY);
  if (!runId) {
    ElMessage.warning("请先在智能体助手中开始一段对话");
    return;
  }
  dreamRunLoading.value = true;
  try {
    await dreamFromRun(runId, false);
    ElMessage.success("已从当前对话提炼经验");
    await loadExperiences();
  } catch (err) {
    ElMessage.error(err.message || "提炼失败");
  } finally {
    dreamRunLoading.value = false;
  }
}

async function toggleExperience(row) {
  try {
    await toggleExperienceEnabled(row.id, row.enabled);
  } catch (err) {
    row.enabled = !row.enabled;
    ElMessage.error(err.message || "更新失败");
  }
}

async function removeExperience(row) {
  try {
    await ElMessageBox.confirm("确定删除这条经验？", "删除经验", { type: "warning" });
    await deleteExperience(row.id);
    if (selectedExperience.value?.id === row.id) selectedExperience.value = null;
    await loadExperiences();
  } catch (err) {
    if (err !== "cancel") ElMessage.error(err.message || "删除失败");
  }
}

onMounted(loadExperiences);
</script>

<style scoped>
.experience-detail {
  margin-top: 16px;
  padding: 14px;
  background: #f8fafc;
  border-radius: 10px;
  font-size: 13px;
  line-height: 1.6;
}

.experience-detail h4 {
  margin: 0 0 8px;
}

.experience-detail p {
  margin: 0 0 10px;
}
</style>
