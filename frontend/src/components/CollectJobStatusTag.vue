<template>
  <span class="collect-status-tag">
    <el-button
      v-if="clickable"
      link
      class="status-btn"
      :type="tagType === 'danger' ? 'danger' : tagType === 'warning' ? 'warning' : 'primary'"
      @click.stop="openDialog"
    >
      <el-tag size="small" :type="tagType" class="status-tag-inner">
        {{ label }}
        <el-icon class="status-hint-icon"><InfoFilled /></el-icon>
      </el-tag>
    </el-button>
    <el-tag v-else size="small" :type="tagType">{{ label }}</el-tag>

    <Teleport to="body">
      <CollectJobStatusDialog
        v-model="dialogOpen"
        :brief="brief"
        @continue="$emit('continue', row)"
      />
    </Teleport>
  </span>
</template>

<script setup>
import { computed, ref } from "vue";
import { InfoFilled } from "@element-plus/icons-vue";
import CollectJobStatusDialog from "./CollectJobStatusDialog.vue";
import {
  collectJobStatusLabel,
  collectJobStatusTagType,
  effectiveCollectJobStatus,
  getCollectJobStatusBrief,
  isCollectJobStatusClickable,
} from "../utils/collectJobStatusBrief";

const props = defineProps({
  row: { type: Object, required: true },
});

defineEmits(["continue"]);

const dialogOpen = ref(false);

const effectiveStatus = computed(() => effectiveCollectJobStatus(props.row));
const label = computed(() => collectJobStatusLabel(effectiveStatus.value));
const tagType = computed(() => collectJobStatusTagType(effectiveStatus.value));
const clickable = computed(() => isCollectJobStatusClickable(props.row));
const brief = computed(() => getCollectJobStatusBrief(props.row));

function openDialog() {
  if (!brief.value) return;
  dialogOpen.value = true;
}
</script>

<style scoped>
.collect-status-tag {
  display: inline-flex;
  align-items: center;
}

.status-btn {
  padding: 0;
  height: auto;
  vertical-align: middle;
}

.status-tag-inner {
  cursor: pointer;
}

.status-hint-icon {
  margin-left: 2px;
  font-size: 12px;
  vertical-align: -1px;
  opacity: 0.75;
}
</style>
