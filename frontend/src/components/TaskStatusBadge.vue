<template>
  <span class="status-badge" :class="[`status-badge--${tone}`, { 'status-badge--clickable': clickable }]">{{ label }}</span>
</template>

<script setup>
import { computed } from "vue";
import { jobStatusLabel } from "../utils/acquisitionJobs";

const props = defineProps({
  status: { type: String, default: "" },
  clickable: { type: Boolean, default: false },
});

const label = computed(() => jobStatusLabel(props.status));

const tone = computed(() => {
  const status = props.status;
  if (status === "running" || status === "retrying") return "running";
  if (status === "queued") return "queued";
  if (status === "suspended") return "suspended";
  if (status === "pending" || status === "waiting_start") return "waiting";
  if (status === "completed") return "completed";
  if (status === "cancelled") return "stopped";
  if (status === "failed" || status === "dead_letter") return "failed";
  return "default";
});
</script>

<style scoped>
.status-badge {
  display: inline-flex;
  align-items: center;
  border-radius: 6px;
  padding: 2px 10px;
  font-size: 12px;
  font-weight: 500;
  line-height: 1.5;
}

.status-badge--running {
  background: #eff6ff;
  color: #2563eb;
}

.status-badge--queued {
  background: #fff7ed;
  color: #ea580c;
}

.status-badge--suspended {
  background: #fef3c7;
  color: #b45309;
}

.status-badge--waiting {
  background: #f8fafc;
  color: #64748b;
}

.status-badge--completed {
  background: #ecfdf5;
  color: #059669;
}

.status-badge--stopped {
  background: #f1f5f9;
  color: #64748b;
}

.status-badge--failed {
  background: #fef2f2;
  color: #dc2626;
}

.status-badge--default {
  background: #f8fafc;
  color: #64748b;
}

.status-badge--clickable {
  cursor: pointer;
  text-decoration: underline;
  text-underline-offset: 2px;
}
</style>
