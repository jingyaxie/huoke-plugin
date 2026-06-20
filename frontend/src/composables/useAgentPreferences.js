import { ref, watch } from "vue";

const HEADLESS_KEY = "huoke_agent_headless";
const WS_KEY = "huoke_agent_use_ws";
const PROVIDER_KEY = "huoke_agent_provider";

function readHeadless() {
  const raw = localStorage.getItem(HEADLESS_KEY);
  return raw !== "false";
}

function readUseWebSocket() {
  return localStorage.getItem(WS_KEY) === "true";
}

export function useAgentPreferences() {
  const headless = ref(readHeadless());
  const useWebSocket = ref(readUseWebSocket());
  const provider = ref(localStorage.getItem(PROVIDER_KEY) || "deepseek");

  watch(headless, (value) => {
    localStorage.setItem(HEADLESS_KEY, value ? "true" : "false");
    window.dispatchEvent(new CustomEvent("huoke-agent-prefs-changed"));
  });

  watch(useWebSocket, (value) => {
    localStorage.setItem(WS_KEY, value ? "true" : "false");
    window.dispatchEvent(new CustomEvent("huoke-agent-prefs-changed"));
  });

  watch(provider, (value) => {
    if (value) localStorage.setItem(PROVIDER_KEY, value);
    window.dispatchEvent(new CustomEvent("huoke-agent-prefs-changed"));
  });

  function syncFromStorage() {
    headless.value = readHeadless();
    useWebSocket.value = readUseWebSocket();
    const savedProvider = localStorage.getItem(PROVIDER_KEY);
    if (savedProvider) provider.value = savedProvider;
  }

  return { headless, useWebSocket, provider, syncFromStorage };
}
