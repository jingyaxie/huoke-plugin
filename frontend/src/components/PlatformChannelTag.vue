<template>
  <span class="channel-tag" :class="`channel-tag--${platform || 'default'}`">{{ text }}</span>
</template>

<script setup>
import { computed } from "vue";
import { platformLabel } from "../utils/acquisitionJobs";

const props = defineProps({
  platform: { type: String, default: "" },
});

const text = computed(() => platformLabel(props.platform));
</script>

<style scoped>
.channel-tag {
  display: inline-flex;
  align-items: center;
  border-radius: 6px;
  border: 1px solid transparent;
  padding: 2px 8px;
  font-size: 12px;
  font-weight: 500;
}

.channel-tag--douyin {
  background: #f0f9ff;
  border-color: #e0f2fe;
  color: #0284c7;
}

.channel-tag--xiaohongshu {
  background: #fff1f2;
  border-color: #ffe4e6;
  color: #e11d48;
}

.channel-tag--kuaishou {
  background: #fffbeb;
  border-color: #fef3c7;
  color: #d97706;
}

.channel-tag--default {
  background: #f8fafc;
  border-color: #e2e8f0;
  color: #64748b;
}
</style>
