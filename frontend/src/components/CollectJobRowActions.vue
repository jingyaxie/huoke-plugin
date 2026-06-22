<template>
  <el-dropdown trigger="click" @command="(cmd) => emit('action', cmd)">
    <el-button link class="row-actions-trigger" aria-label="更多操作">
      <el-icon :size="18"><MoreFilled /></el-icon>
    </el-button>
    <template #dropdown>
      <el-dropdown-menu>
        <el-dropdown-item command="view">查看数据</el-dropdown-item>
        <el-dropdown-item command="evaluate" :disabled="!canEvaluate">
          评估评论
        </el-dropdown-item>
        <el-dropdown-item command="start" :disabled="!canStart">
          {{ row.status === "paused" ? "继续采集" : "开始采集" }}
        </el-dropdown-item>
        <el-dropdown-item command="pause" :disabled="!canPause">暂停</el-dropdown-item>
        <el-dropdown-item v-if="canDelete" command="delete" divided>
          <span class="danger-text">删除</span>
        </el-dropdown-item>
      </el-dropdown-menu>
    </template>
  </el-dropdown>
</template>

<script setup>
import { computed } from "vue";
import { MoreFilled } from "@element-plus/icons-vue";

const props = defineProps({
  row: { type: Object, required: true },
});

const emit = defineEmits(["action"]);

const canStart = computed(
  () => props.row.status !== "running" && props.row.status !== "completed",
);

const canPause = computed(() => props.row.status === "running");

const canEvaluate = computed(
  () => Number(props.row.comment_count || 0) > 0 && props.row.status !== "running",
);

const canDelete = computed(() =>
  ["pending", "paused", "failed", "completed"].includes(props.row.status),
);
</script>

<style scoped>
.row-actions-trigger {
  padding: 4px 8px;
  color: var(--el-text-color-secondary);
}

.row-actions-trigger:hover {
  color: var(--el-color-primary);
}

.danger-text {
  color: var(--el-color-danger);
}
</style>
