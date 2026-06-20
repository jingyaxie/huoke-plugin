<template>
  <div v-if="issues.length" class="health-alerts">
    <div class="health-title">{{ title }}</div>
    <ul class="health-list">
      <li v-for="issue in issues" :key="issue.issueKey" class="health-item">
        <div class="health-message">
          <span class="health-nickname">【{{ issue.platformLabel }}】{{ issue.nickname }}</span>
          <span class="health-sep">|</span>
          <span>{{ issue.message }}</span>
        </div>
        <el-button
          link
          type="primary"
          size="small"
          :loading="resolvingKey === issue.issueKey"
          @click="$emit('resolve', issue)"
        >
          {{ resolvingKey === issue.issueKey ? "处理中…" : `${actionLabel(issue)} →` }}
        </el-button>
      </li>
    </ul>
    <p class="health-hint">点击后将打开本机浏览器完成重新登录或风控验证，完成后请返回此页刷新状态。</p>
  </div>
</template>

<script setup>
defineProps({
  issues: { type: Array, default: () => [] },
  resolvingKey: { type: String, default: "" },
  title: { type: String, default: "账号绑定异常提醒" },
});

defineEmits(["resolve"]);

function actionLabel(issue) {
  if (issue.kind === "risk_control") return "前往处理";
  return "重新登录";
}
</script>

<style scoped>
.health-alerts {
  border: 1px solid #fcd34d;
  background: rgba(255, 251, 235, 0.9);
  border-radius: 8px;
  padding: 16px;
}

.health-title {
  font-size: 14px;
  font-weight: 600;
  color: #78350f;
  margin-bottom: 8px;
}

.health-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.health-item {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border: 1px solid #fde68a;
  background: rgba(255, 255, 255, 0.7);
  border-radius: 6px;
  padding: 8px 12px;
  font-size: 13px;
  color: #451a03;
}

.health-nickname {
  font-weight: 600;
}

.health-sep {
  margin: 0 8px;
  color: #fcd34d;
}

.health-hint {
  margin: 8px 0 0;
  font-size: 12px;
  color: rgba(120, 53, 15, 0.8);
}
</style>
