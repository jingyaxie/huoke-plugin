<template>
  <div class="chat-turn" :class="turnClass">
    <!-- 用户：无头像，气泡右对齐 -->
    <div v-if="message.kind === 'user'" class="turn-inner user-row">
      <div class="user-bubble">{{ message.text }}</div>
    </div>

    <!-- 工具：轻量条，无头像 -->
    <div v-else-if="message.kind === 'tool'" class="turn-inner tool-row">
      <div
        class="tool-block"
        :class="{ error: message.hasError, open: expanded }"
      >
        <button type="button" class="tool-head" @click="$emit('toggle')">
          <span class="tool-dot" :class="{ error: message.hasError }" />
          <code class="tool-name">{{ message.toolName }}</code>
          <span class="tool-summary">{{ message.summary }}</span>
          <el-icon class="tool-chevron" :class="{ open: expanded }"><ArrowDown /></el-icon>
        </button>
        <pre v-if="expanded" class="tool-json">{{ message.content }}</pre>
      </div>
    </div>

    <!-- 助手 / 子任务 / 错误 / 结果 -->
    <div v-else class="turn-inner assistant-row">
      <div class="turn-avatar" :class="message.kind">
        <svg v-if="message.kind !== 'error'" viewBox="0 0 24 24" class="avatar-icon" aria-hidden="true">
          <path
            fill="currentColor"
            d="M12 2a7 7 0 0 0-7 7c0 3.2 2.1 5.9 5 6.8V18H7v2h10v-2h-3v-2.2c2.9-.9 5-3.6 5-6.8a7 7 0 0 0-7-7Z"
          />
        </svg>
        <span v-else>!</span>
      </div>

      <div class="turn-content">
        <div v-if="message.kind === 'assistant'" class="prose" v-html="message.html" />

        <div v-else-if="message.kind === 'subagent'" class="subagent-wrap">
          <span class="subagent-badge">子任务</span>
          <div class="prose" v-html="message.html" />
        </div>

        <div v-else-if="message.kind === 'error'" class="error-banner">
          <div class="error-text">{{ message.text }}</div>
        </div>

        <div v-else-if="message.kind === 'result' || message.kind === 'skill_result'" class="result-card">
          <div class="result-card-head">
            <span class="result-badge">{{ message.resultCard.badge || (message.kind === 'skill_result' ? '技能完成' : '任务完成') }}</span>
            <span v-if="message.resultCard.status" class="result-status">
              {{ message.resultCard.status }}
            </span>
          </div>
          <div
            v-if="message.resultCard.summary"
            class="prose result-summary"
            v-html="message.resultCard.summaryHtml"
          />
          <details v-if="message.resultCard.raw" class="json-details">
            <summary>查看原始数据</summary>
            <pre class="json-block">{{ message.resultCard.rawText }}</pre>
          </details>
        </div>

        <div v-else class="prose">{{ message.text }}</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from "vue";
import { ArrowDown } from "@element-plus/icons-vue";

const props = defineProps({
  message: { type: Object, required: true },
  expanded: { type: Boolean, default: false },
});

defineEmits(["toggle"]);

const turnClass = computed(() => {
  if (props.message.kind === "user") return "is-user";
  if (props.message.kind === "tool") return "is-tool";
  if (props.message.kind === "error") return "is-error";
  return "is-assistant";
});
</script>

<style scoped>
.chat-turn {
  width: 100%;
}

.chat-turn.is-user {
  background: var(--agent-surface, #f8fafb);
}

.chat-turn.is-assistant,
.chat-turn.is-error {
  background: #fff;
}

.chat-turn.is-tool {
  background: #fff;
}

.turn-inner {
  max-width: var(--chat-thread-width, 768px);
  margin: 0 auto;
  padding: 20px 16px;
}

.user-row {
  display: flex;
  justify-content: flex-end;
}

.user-bubble {
  max-width: min(85%, 560px);
  background: #ecfdf5;
  border: 1px solid #ccfbf1;
  border-radius: 24px;
  padding: 12px 18px;
  font-size: 15px;
  line-height: 1.55;
  color: #134e4a;
  white-space: pre-wrap;
  word-break: break-word;
}

.tool-row {
  padding: 6px 16px 10px;
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

.turn-avatar.error {
  background: #ef4444;
  font-size: 14px;
  font-weight: 700;
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

.subagent-wrap {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.subagent-badge {
  align-self: flex-start;
  font-size: 11px;
  font-weight: 600;
  color: #0369a1;
  background: #e0f2fe;
  padding: 2px 8px;
  border-radius: 4px;
}

.error-banner {
  padding: 12px 14px;
  border-radius: 12px;
  background: #fef2f2;
  border: 1px solid #fecaca;
}

.error-text {
  font-size: 15px;
  line-height: 1.55;
  color: #991b1b;
  white-space: pre-wrap;
}

.result-card {
  border: 1px solid #bbf7d0;
  background: #f0fdf4;
  border-radius: 12px;
  padding: 14px 16px;
}

.result-card-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}

.result-badge {
  font-size: 11px;
  font-weight: 700;
  color: #059669;
  background: #d1fae5;
  padding: 3px 8px;
  border-radius: 4px;
}

.result-status {
  font-size: 11px;
  color: #6b7280;
}

.tool-block {
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  background: #fafafa;
  overflow: hidden;
}

.tool-block.error {
  border-color: #fecaca;
  background: #fef2f2;
}

.tool-head {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border: none;
  background: transparent;
  cursor: pointer;
  text-align: left;
  font-size: 13px;
  color: #374151;
}

.tool-head:hover {
  background: rgba(0, 0, 0, 0.03);
}

.tool-dot {
  flex-shrink: 0;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #9ca3af;
}

.tool-dot.error {
  background: #ef4444;
}

.tool-name {
  flex-shrink: 0;
  font-size: 12px;
  background: #fff;
  border: 1px solid #e5e7eb;
  padding: 2px 7px;
  border-radius: 6px;
  color: #111827;
}

.tool-summary {
  flex: 1;
  min-width: 0;
  color: #6b7280;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tool-chevron {
  flex-shrink: 0;
  color: #9ca3af;
  transition: transform 0.2s;
}

.tool-chevron.open {
  transform: rotate(180deg);
}

.tool-json,
.json-block {
  margin: 0;
  padding: 10px 12px;
  border-top: 1px solid #e5e7eb;
  background: #1e293b;
  color: #e2e8f0;
  font-size: 12px;
  line-height: 1.5;
  overflow: auto;
  max-height: 240px;
  white-space: pre-wrap;
  word-break: break-all;
}

.json-details summary {
  font-size: 12px;
  color: #6b7280;
  cursor: pointer;
  margin-top: 8px;
}

.prose :deep(h1),
.prose :deep(h2),
.prose :deep(h3) {
  margin: 0.55em 0 0.35em;
  font-weight: 650;
  line-height: 1.35;
  color: #0d0d0d;
}

.prose :deep(h1) { font-size: 1.35em; }
.prose :deep(h2) { font-size: 1.15em; }
.prose :deep(h3) { font-size: 1.05em; }

.prose :deep(p) {
  margin: 0 0 0.65em;
  font-size: 15px;
  line-height: 1.65;
  color: #0d0d0d;
}

.prose :deep(p:last-child) {
  margin-bottom: 0;
}

.prose :deep(ul),
.prose :deep(ol) {
  margin: 0 0 0.65em;
  padding-left: 1.4em;
  font-size: 15px;
  line-height: 1.6;
}

.prose :deep(li) {
  margin: 0.2em 0;
}

.prose :deep(blockquote) {
  margin: 0 0 0.65em;
  padding: 8px 12px;
  border-left: 3px solid #d1d5db;
  color: #4b5563;
}

.prose :deep(a) {
  color: #0f766e;
  text-decoration: underline;
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
