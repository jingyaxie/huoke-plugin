<template>
  <el-form-item label="浏览器模式">
    <div class="browser-mode-grid">
      <button
        v-for="option in options"
        :key="option.value"
        type="button"
        class="browser-mode-card"
        :class="{ active: modelValue === option.value }"
        @click="$emit('update:modelValue', option.value)"
      >
        <span class="browser-mode-check">{{ modelValue === option.value ? "✓" : "" }}</span>
        <div>
          <div class="browser-mode-label">{{ option.label }}</div>
          <div class="browser-mode-hint">{{ option.hint }}</div>
        </div>
      </button>
    </div>
  </el-form-item>
</template>

<script setup>
defineProps({
  modelValue: { type: String, default: "headless" },
});

defineEmits(["update:modelValue"]);

const options = [
  { value: "headless", label: "无头模式", hint: "后台运行，资源占用低（推荐）" },
  { value: "headed", label: "有头模式", hint: "可见浏览器，便于调试或过验证码" },
];
</script>

<style scoped>
.browser-mode-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  width: 100%;
}

.browser-mode-card {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 14px;
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
  background: #fff;
  text-align: left;
  cursor: pointer;
}

.browser-mode-card.active {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
}

.browser-mode-check {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  border: 1px solid var(--el-border-color);
  display: grid;
  place-items: center;
  font-size: 12px;
  flex-shrink: 0;
}

.browser-mode-card.active .browser-mode-check {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary);
  color: #fff;
}

.browser-mode-label {
  font-size: 14px;
  font-weight: 500;
}

.browser-mode-hint {
  margin-top: 2px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
</style>
