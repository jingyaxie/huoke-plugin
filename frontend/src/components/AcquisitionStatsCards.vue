<template>
  <div class="stats-grid">
    <div v-for="item in items" :key="item.key" class="stats-card" :class="`stats-card--${item.key}`">
      <span class="stats-label">{{ item.label }}</span>
      <div class="stats-value">{{ loading ? "—" : formatValue(data?.[item.key]) }}</div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  data: { type: Object, default: null },
  loading: { type: Boolean, default: false },
});

const items = [
  { key: "running_tasks", label: "运行中任务" },
  { key: "queued_tasks", label: "排队中" },
  { key: "precise_customers", label: "精准客户" },
  { key: "total_leads", label: "总线索" },
  { key: "dm_count", label: "私信数" },
  { key: "follow_count", label: "关注数" },
];

function formatValue(value) {
  const num = Number(value || 0);
  return Number.isFinite(num) ? num.toLocaleString("zh-CN") : "0";
}
</script>

<style scoped>
.stats-grid {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 16px;
}

.stats-card {
  border-radius: 12px;
  padding: 16px 18px;
  border: 1px solid transparent;
}

.stats-label {
  display: block;
  font-size: 13px;
  font-weight: 500;
}

.stats-value {
  margin-top: 12px;
  font-size: 30px;
  font-weight: 600;
  line-height: 1.1;
}

.stats-card--running_tasks {
  background: #eff6ff;
  border-color: #dbeafe;
}
.stats-card--running_tasks .stats-label,
.stats-card--running_tasks .stats-value {
  color: #2563eb;
}

.stats-card--queued_tasks {
  background: #fff7ed;
  border-color: #ffedd5;
}
.stats-card--queued_tasks .stats-label,
.stats-card--queued_tasks .stats-value {
  color: #ea580c;
}

.stats-card--precise_customers {
  background: #ecfdf5;
  border-color: #d1fae5;
}
.stats-card--precise_customers .stats-label,
.stats-card--precise_customers .stats-value {
  color: #059669;
}

.stats-card--total_leads {
  background: #f5f3ff;
  border-color: #ede9fe;
}
.stats-card--total_leads .stats-label,
.stats-card--total_leads .stats-value {
  color: #7c3aed;
}

.stats-card--dm_count {
  background: #fefce8;
  border-color: #fef08a;
}
.stats-card--dm_count .stats-label,
.stats-card--dm_count .stats-value {
  color: #ca8a04;
}

.stats-card--follow_count {
  background: #f0f9ff;
  border-color: #e0f2fe;
}
.stats-card--follow_count .stats-label,
.stats-card--follow_count .stats-value {
  color: #0284c7;
}

@media (max-width: 1200px) {
  .stats-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}
</style>
