<template>
  <section class="settings-section panel">
    <header class="section-head">
      <h2 class="section-title">通用</h2>
      <p class="section-desc">租户、数据源与 API 鉴权，智能体与任务接口共用同一上下文。</p>
    </header>

    <div class="field-block">
      <label class="field-label">数据源</label>
      <el-input v-model="platformId" placeholder="douyin / xiaohongshu / kuaishou" @change="onPlatformChange" />
    </div>
    <div class="field-block">
      <label class="field-label">租户 ID</label>
      <el-input v-model="tenantId" placeholder="default" @change="onTenantChange" />
    </div>
    <div class="field-block">
      <label class="field-label">API Key</label>
      <el-input
        v-model="apiKey"
        type="password"
        show-password
        placeholder="启用鉴权时填写"
        @change="onApiKeyChange"
      />
    </div>
    <p class="hint-text">修改后立即生效，无需重启前端。</p>
  </section>
</template>

<script setup>
import { ref } from "vue";
import { getTenantId, setTenantId, getPlatformId, setPlatformId, getApiKey, setApiKey } from "../../api/http";

const tenantId = ref(getTenantId());
const platformId = ref(getPlatformId());
const apiKey = ref(getApiKey());

function onTenantChange() {
  setTenantId(tenantId.value);
  window.dispatchEvent(new CustomEvent("huoke-tenant-changed", { detail: tenantId.value }));
}

function onPlatformChange() {
  setPlatformId(platformId.value);
  window.dispatchEvent(new CustomEvent("huoke-platform-changed", { detail: platformId.value }));
}

function onApiKeyChange() {
  setApiKey(apiKey.value);
}
</script>
