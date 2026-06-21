<template>
  <el-dropdown trigger="click" @command="(cmd) => emit('action', cmd)">
    <el-button link class="row-actions-trigger" aria-label="更多操作">
      <el-icon :size="18"><MoreFilled /></el-icon>
    </el-button>
    <template #dropdown>
      <el-dropdown-menu>
        <el-dropdown-item command="start" :disabled="row.status === 'running'">开始</el-dropdown-item>
        <el-dropdown-item command="pause" :disabled="row.status !== 'running'">暂停</el-dropdown-item>
      </el-dropdown-menu>
    </template>
  </el-dropdown>
</template>

<script setup>
import { MoreFilled } from "@element-plus/icons-vue";

defineProps({
  row: { type: Object, required: true },
});

const emit = defineEmits(["action"]);
</script>

<style scoped>
.row-actions-trigger {
  padding: 4px 8px;
  color: var(--el-text-color-secondary);
}

.row-actions-trigger:hover {
  color: var(--el-color-primary);
}
</style>
