<template>
  <div class="chat-turn is-assistant streaming">
    <div class="turn-inner assistant-row">
      <div class="turn-avatar">
        <svg viewBox="0 0 24 24" class="avatar-icon" aria-hidden="true">
          <path
            fill="currentColor"
            d="M12 2a7 7 0 0 0-7 7c0 3.2 2.1 5.9 5 6.8V18H7v2h10v-2h-3v-2.2c2.9-.9 5-3.6 5-6.8a7 7 0 0 0-7-7Z"
          />
        </svg>
      </div>
      <div class="turn-content">
        <div v-if="html" class="prose streaming-prose" v-html="html" />
        <div v-else class="thinking-row">
          <span v-if="status" class="status-text">{{ status }}</span>
          <span class="typing-dots"><i /><i /><i /></span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  html: { type: String, default: "" },
  status: { type: String, default: "" },
});
</script>

<style scoped>
.chat-turn {
  width: 100%;
  background: #fff;
}

.turn-inner {
  max-width: var(--chat-thread-width, 768px);
  margin: 0 auto;
  padding: 20px 16px;
}

.assistant-row {
  display: flex;
  gap: 16px;
  align-items: flex-start;
}

.turn-avatar {
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--primary, #0f766e);
  color: #fff;
  margin-top: 2px;
}

.avatar-icon {
  width: 16px;
  height: 16px;
}

.turn-content {
  flex: 1;
  min-width: 0;
  padding-top: 2px;
}

.thinking-row {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 6px 0;
}

.status-text {
  font-size: 13px;
  color: #6b7280;
}

.typing-dots {
  display: inline-flex;
  gap: 5px;
}

.typing-dots i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #9ca3af;
  animation: bounce 1.2s infinite ease-in-out;
}

.typing-dots i:nth-child(2) { animation-delay: 0.15s; }
.typing-dots i:nth-child(3) { animation-delay: 0.3s; }

@keyframes bounce {
  0%, 80%, 100% { transform: translateY(0); opacity: 0.35; }
  40% { transform: translateY(-4px); opacity: 1; }
}

.streaming-prose :deep(.stream-cursor) {
  display: inline-block;
  color: #0d0d0d;
  animation: blink 1s step-end infinite;
}

@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}

.prose :deep(p) {
  margin: 0 0 0.65em;
  font-size: 15px;
  line-height: 1.65;
  color: #0d0d0d;
}

.prose :deep(p:last-child) {
  margin-bottom: 0;
}

.prose :deep(.inline-code) {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.88em;
  background: #f4f4f4;
  border-radius: 4px;
  padding: 2px 5px;
}

.prose :deep(.code-block) {
  margin: 0 0 0.65em;
  padding: 14px 16px;
  background: #0d0d0d;
  border-radius: 10px;
  overflow: auto;
}

.prose :deep(.code-body) {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 13px;
  line-height: 1.5;
  color: #ececec;
  white-space: pre-wrap;
}
</style>
