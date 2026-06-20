<template>
  <span class="user-avatar" :style="sizeStyle">
    <img
      v-if="src && !failed"
      :src="src"
      referrerpolicy="no-referrer"
      class="user-avatar__img"
      alt=""
      @error="failed = true"
    />
    <span v-else class="user-avatar__fallback">{{ fallback }}</span>
  </span>
</template>

<script setup>
import { computed, ref, watch } from "vue";

const props = defineProps({
  src: { type: String, default: "" },
  fallback: { type: String, default: "?" },
  size: { type: Number, default: 28 },
});

const failed = ref(false);

watch(
  () => props.src,
  () => {
    failed.value = false;
  },
);

const sizeStyle = computed(() => ({
  width: `${props.size}px`,
  height: `${props.size}px`,
}));
</script>

<style scoped>
.user-avatar {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  overflow: hidden;
  background: #e2e8f0;
  flex-shrink: 0;
}

.user-avatar__img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.user-avatar__fallback {
  color: #fff;
  font-size: 12px;
  font-weight: 500;
  line-height: 1;
}
</style>
