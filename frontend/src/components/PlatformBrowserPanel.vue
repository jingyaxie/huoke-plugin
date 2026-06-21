<template>
  <el-card shadow="never" class="platform-browser-panel">
    <template #header>
      <div class="panel-head">
        <span>平台登录</span>
        <span class="panel-hint">登录态由 Chrome 自行管理，App 不绑定、不检测账号状态</span>
      </div>
    </template>

    <p class="intro">
      在 Chrome 中打开对应平台并完成登录即可。插件会复用当前浏览器 Cookie，无需在 App 内授权或注入浏览器。
    </p>

    <div class="platform-grid">
      <article v-for="item in platforms" :key="item.id" class="platform-card">
        <div class="platform-name">{{ item.label }}</div>
        <p class="platform-desc">{{ item.desc }}</p>
        <el-button type="primary" plain @click="openPlatform(item)">在 Chrome 中打开</el-button>
      </article>
    </div>

    <el-collapse class="setup-collapse">
      <el-collapse-item title="首次使用：安装 Chrome 插件" name="ext">
        <ol class="setup-steps">
          <li>打开 <code>chrome://extensions</code>，开启「开发者模式」</li>
          <li>「加载已解压的扩展程序」→ 选择项目内 <code>extension/dist</code>（不是 <code>extension/</code> 源码目录）</li>
          <li>修改插件后执行 <code>cd extension && npm run build</code>，再在扩展页点「重新加载」</li>
          <li>若显示 <strong>Service Worker（无效）</strong>：点击该蓝色链接唤醒后台；或点击插件图标查看连接状态</li>
          <li>确认本地服务已启动（<code>npm run dev</code>，端口 18766），再打开上方平台页面登录</li>
        </ol>
      </el-collapse-item>
    </el-collapse>
  </el-card>
</template>

<script setup>
import { ElMessage } from "element-plus";
import { EXTENSION_PLATFORM_LOGIN_CARDS } from "../config/extensionPlatformCapabilities";

const platforms = EXTENSION_PLATFORM_LOGIN_CARDS;

function openPlatform(item) {
  const opened = window.open(item.url, "_blank", "noopener,noreferrer");
  if (!opened) {
    ElMessage.warning("请允许弹出窗口，或手动在 Chrome 地址栏打开：" + item.url);
    return;
  }
  ElMessage.success(`已在浏览器打开${item.label}，请在该页面完成登录`);
}
</script>

<style scoped>
.platform-browser-panel {
  width: 100%;
}

.panel-head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 10px;
}

.panel-hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  font-weight: 400;
}

.intro {
  margin: 0 0 16px;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
}

.platform-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.platform-card {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.platform-name {
  font-size: 16px;
  font-weight: 600;
}

.platform-desc {
  margin: 0;
  flex: 1;
  font-size: 13px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
}

.setup-collapse {
  margin-top: 16px;
}

.setup-steps {
  margin: 0;
  padding-left: 20px;
  color: var(--el-text-color-secondary);
  line-height: 1.7;
}

@media (max-width: 900px) {
  .platform-grid {
    grid-template-columns: 1fr;
  }
}
</style>
