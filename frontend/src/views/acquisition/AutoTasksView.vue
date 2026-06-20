<template>
  <div class="acquisition-page">
    <LegacyPlaywrightBanner />
    <header class="page-header">
      <div>
        <h1 class="page-title">AI获客任务列表</h1>
        <p class="page-subtitle">创建和管理自动获客任务，跟踪抓取进度、精准客户数量与线索更新。</p>
      </div>
      <el-button type="primary" class="create-btn" @click="createOpen = true">+ 创建任务</el-button>
    </header>

    <AcquisitionJobsPanel ref="panelRef" mode="auto" :active="true" />

    <CreateAutoTaskDialog v-model="createOpen" @created="onCreated" />
  </div>
</template>

<script setup>
import { ref } from "vue";
import AcquisitionJobsPanel from "../../components/AcquisitionJobsPanel.vue";
import CreateAutoTaskDialog from "../../components/CreateAutoTaskDialog.vue";
import LegacyPlaywrightBanner from "../../components/LegacyPlaywrightBanner.vue";

const panelRef = ref(null);
const createOpen = ref(false);

async function onCreated() {
  await panelRef.value?.loadJobs?.();
}
</script>

<style scoped>
.acquisition-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
}

.create-btn {
  flex-shrink: 0;
  padding: 0 20px;
}
</style>
