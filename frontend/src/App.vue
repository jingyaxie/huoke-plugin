<template>
  <router-view />
</template>

<script setup>
import { onMounted, onUnmounted } from "vue";
import { useRouter } from "vue-router";
import { handlePortalMessage } from "./portal";
import { mapH5PathToCloudRoute } from "./config/cloudNav";

const router = useRouter();

function resolveNavigatePath(path) {
  if (path.startsWith("/customer/")) {
    return mapH5PathToCloudRoute(path);
  }
  return path;
}

function onPortalMessage(event) {
  const result = handlePortalMessage(event);
  if (result?.navigate) {
    router.push(resolveNavigatePath(result.navigate)).catch(() => {});
  }
}

onMounted(() => {
  window.addEventListener("message", onPortalMessage);
});

onUnmounted(() => {
  window.removeEventListener("message", onPortalMessage);
});
</script>
