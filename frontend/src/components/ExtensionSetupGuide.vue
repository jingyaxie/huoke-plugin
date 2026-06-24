<template>
  <el-collapse v-model="activeNames" class="extension-setup-guide">
    <el-collapse-item name="guide">
      <template #title>
        <span class="guide-title">Chrome 插件配置</span>
      </template>

      <p class="guide-lead">
        盈小蚁安装包已自带 Chrome 插件。推荐一键启动；若使用日常 Chrome，请按下方路径手动加载。
      </p>

      <div v-if="canLaunch" class="guide-actions">
        <el-button type="primary" size="small" :loading="launching" @click="$emit('launch')">
          启动浏览器插件
        </el-button>
        <ExtensionReloadButton
          v-if="bridgeConnected"
          size="small"
          :connected="true"
          @reloaded="$emit('reloaded')"
        />
        <el-button size="small" @click="$emit('open-folder')">打开插件目录</el-button>
        <el-button size="small" :loading="checking" @click="$emit('refresh')">检测连接</el-button>
      </div>
      <div v-else-if="bridgeConnected" class="guide-actions">
        <ExtensionReloadButton size="small" :connected="true" @reloaded="$emit('reloaded')" />
        <el-button size="small" :loading="checking" @click="$emit('refresh')">检测连接</el-button>
      </div>

      <ol class="guide-steps">
        <li>
          <strong>推荐：</strong>点击「启动浏览器插件」，自动打开 Chrome 并完成加载（无需进入扩展管理页）
        </li>
        <li>
          <strong>手动加载：</strong>Chrome 地址栏输入 <code>chrome://extensions</code> → 开启「开发者模式」→
          「加载已解压的扩展程序」→ 选择下方<strong>插件目录</strong>
        </li>
        <li>看到插件角标 <strong>OK</strong> 后，在本页打开平台并完成登录</li>
      </ol>

      <dl class="guide-paths">
        <div class="path-row">
          <dt>插件目录（手动加载选此）</dt>
          <dd>
            <code>{{ runtimePath }}</code>
            <el-button link type="primary" size="small" @click="copyPath(runtimePath)">复制</el-button>
          </dd>
        </div>
        <div v-if="bundlePath" class="path-row">
          <dt>安装目录内插件（安装包自带，排查时可对照）</dt>
          <dd>
            <code>{{ bundlePath }}</code>
            <el-button link type="primary" size="small" @click="copyPath(bundlePath)">复制</el-button>
          </dd>
        </div>
      </dl>
    </el-collapse-item>
  </el-collapse>
</template>

<script setup>
import { ref } from "vue";
import { ElMessage } from "element-plus";
import ExtensionReloadButton from "./ExtensionReloadButton.vue";

defineProps({
  canLaunch: { type: Boolean, default: false },
  bridgeConnected: { type: Boolean, default: false },
  runtimePath: { type: String, default: "" },
  bundlePath: { type: String, default: "" },
  launching: { type: Boolean, default: false },
  checking: { type: Boolean, default: false },
});

defineEmits(["launch", "open-folder", "refresh", "reloaded"]);

const activeNames = ref(["guide"]);

async function copyPath(text) {
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    ElMessage.success("路径已复制");
  } catch {
    ElMessage.warning("复制失败，请手动选中路径复制");
  }
}
</script>

<style scoped>
.extension-setup-guide {
  margin-top: 12px;
}

.extension-setup-guide :deep(.el-collapse-item__header) {
  height: 36px;
  line-height: 36px;
  font-size: 13px;
}

.extension-setup-guide :deep(.el-collapse-item__content) {
  padding-bottom: 10px;
}

.guide-title {
  font-weight: 600;
}

.guide-lead {
  margin: 0 0 8px;
  font-size: 12px;
  line-height: 1.5;
  color: var(--el-text-color-secondary);
}

.guide-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 8px;
}

.guide-paths {
  margin: 8px 0 0;
}

.path-row {
  margin-bottom: 6px;
}

.path-row dt {
  margin: 0 0 2px;
  font-size: 11px;
  color: var(--el-text-color-secondary);
}

.path-row dd {
  margin: 0;
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.path-row code {
  font-size: 11px;
  word-break: break-all;
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--el-fill-color-light);
}

.guide-steps {
  margin: 0;
  padding-left: 18px;
  font-size: 12px;
  line-height: 1.55;
  color: var(--el-text-color-secondary);
}

.guide-steps code {
  font-size: 11px;
}
</style>
