<template>
  <div class="acquisition-page">
    <LegacyPlaywrightBanner />
    <header class="page-header">
      <div>
        <h1 class="page-title">手动获客任务列表</h1>
        <p class="page-subtitle">管理通过账号主页或单条视频发起的手动获客任务。</p>
      </div>
      <el-button type="primary" class="create-btn" @click="createOpen = true">+ 创建任务</el-button>
    </header>

    <AcquisitionJobsPanel ref="panelRef" mode="manual" :active="true" />

    <CreateManualTaskDialog v-model="createOpen" @created="onCreated" />
  </div>
</template>

<script setup>
import { ref } from "vue";
import AcquisitionJobsPanel from "../../components/AcquisitionJobsPanel.vue";
import CreateManualTaskDialog from "../../components/CreateManualTaskDialog.vue";
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
