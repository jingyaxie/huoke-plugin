<template>
  <button
    v-if="clickable || Number(value) > 0"
    type="button"
    class="metric-link"
    @click="$emit('click', $event)"
  >
    {{ value }}
  </button>
  <span v-else class="metric-zero">0</span>
</template>

<script setup>
defineProps({
  value: { type: [Number, String], default: 0 },
  clickable: { type: Boolean, default: false },
});

defineEmits(["click"]);
</script>

<style scoped>
.metric-link {
  border: none;
  background: none;
  padding: 0;
  color: var(--el-color-primary);
  font: inherit;
  cursor: pointer;
  text-decoration: underline;
  text-underline-offset: 2px;
}

.metric-link:hover {
  color: var(--el-color-primary-light-3);
}

.metric-zero {
  color: var(--el-text-color-regular);
}
</style>
