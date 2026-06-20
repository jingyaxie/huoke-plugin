<template>
  <div class="acquisition-page">
    <header class="page-header">
      <div>
        <h1 class="page-title">大模型配置</h1>
        <p class="page-subtitle">配置 DeepSeek，用于任务编排、评论评估与线索筛选。</p>
      </div>
    </header>

    <section class="table-card panel page-body">
      <SettingsModelSection />
    </section>
  </div>
</template>

<script setup>
import SettingsModelSection from "../settings/SettingsModelSection.vue";
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

.page-body {
  padding: 20px 24px;
}

.page-body :deep(.settings-section) {
  border: none;
  box-shadow: none;
  padding: 0;
}
</style>
