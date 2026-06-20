<template>
  <div class="task-layout">
    <div class="task-layout-inner">
      <header v-if="isSecondary" class="task-layout-header panel">
        <el-button class="back-btn" text @click="goBack">← 返回列表</el-button>
        <span class="crumb-current">{{ secondaryTitle }}</span>
      </header>

      <main class="task-layout-main">
        <router-view />
      </main>
    </div>
  </div>
</template>

<script setup>
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";

const route = useRoute();
const router = useRouter();

const isSecondary = computed(() => route.name !== "tasks");

const secondaryTitle = computed(() => {
  if (route.name === "agent-job-detail") return "编排任务详情";
  return "";
});

function goBack() {
  if (window.history.length > 1) {
    router.back();
    return;
  }
  router.push("/tasks");
}
</script>

<style scoped>
.task-layout {
  min-height: 100%;
  box-sizing: border-box;
}

.task-layout-inner {
  width: 100%;
  max-width: 1280px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.task-layout-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 20px;
  flex-shrink: 0;
}

.back-btn {
  padding: 0;
  font-weight: 600;
}

.crumb-current {
  font-size: 15px;
  font-weight: 600;
  color: var(--text);
}

.task-layout-main {
  flex: 1;
  min-width: 0;
  min-height: 0;
}
</style>
