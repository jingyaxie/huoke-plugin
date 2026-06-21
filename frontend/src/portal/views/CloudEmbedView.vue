<template>
  <div class="cloud-embed">
    <iframe
      ref="frameRef"
      class="cloud-frame"
      :src="embedUrl"
      :title="pageTitle"
      referrerpolicy="no-referrer-when-downgrade"
      allow="clipboard-read; clipboard-write"
      @load="onFrameLoad"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { findCloudNavByRoute, getPortalBaseUrl } from "../config/cloudNav";
import {
  buildPortalEmbedUrl,
  clearPortalAuth,
  isPortalMessageOrigin,
  PORTAL_PING_MESSAGE,
  PORTAL_PONG_MESSAGE,
} from "../utils/portalShell";

const route = useRoute();
const router = useRouter();
const frameRef = ref(null);

const pageTitle = computed(() => route.meta?.title || "盈小蚁客户后台");

const embedUrl = computed(() => {
  const navItem = findCloudNavByRoute(route.path);
  const h5Path = navItem?.h5Path || route.meta?.h5Path || "/customer/dashboard";
  const base = h5Path.startsWith("http") ? h5Path : `${getPortalBaseUrl()}${h5Path}`;
  const suffix = route.fullPath.includes("?") ? route.fullPath.slice(route.fullPath.indexOf("?")) : "";
  return buildPortalEmbedUrl(`${base}${suffix}`);
});

function pingFrame() {
  const win = frameRef.value?.contentWindow;
  if (!win) return;
  try {
    win.postMessage({ type: PORTAL_PING_MESSAGE }, "*");
  } catch {
    /* cross-origin until loaded */
  }
}

function onFrameLoad() {
  pingFrame();
  window.setTimeout(pingFrame, 500);
}

function onPortalMessage(event) {
  if (!isPortalMessageOrigin(event.origin)) return;
  const data = event.data;
  if (!data || data.type !== PORTAL_PONG_MESSAGE) return;
  if (data.authenticated !== false) return;
  clearPortalAuth();
  router.replace({
    name: "portal-login",
    query: { redirect: route.fullPath },
  }).catch(() => {});
}

onMounted(() => {
  window.addEventListener("message", onPortalMessage);
});

onUnmounted(() => {
  window.removeEventListener("message", onPortalMessage);
});
</script>

<style scoped>
.cloud-embed {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  height: 100%;
  background: transparent;
  border: none;
  border-radius: 0;
  box-shadow: none;
  overflow: hidden;
}

.cloud-frame {
  flex: 1;
  display: block;
  width: 100%;
  min-height: 0;
  border: 0;
  background: transparent;
}
</style>
