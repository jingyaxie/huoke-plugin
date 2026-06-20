<template>
  <el-alert
    type="warning"
    :closable="false"
    show-icon
    class="legacy-banner"
    title="此页面使用旧版 Playwright 执行层，已停止维护。"
  >
    <template #default>
      请改用
      <router-link to="/extension-bridge">插件获客</router-link>
      （Chrome 插件 + Rust local-service）。旧版需 Python 后端与 Playwright，仅保留配置/实验用途。
    </template>
  </el-alert>
</template>

<style scoped>
.legacy-banner {
  margin-bottom: 4px;
}
.legacy-banner a {
  color: var(--el-color-primary);
  font-weight: 600;
}
</style>
