<template>
  <div class="container">
      <div class="panel page-header">
        <el-button link type="primary" @click="goBack">← 返回数据面板</el-button>
      </div>

      <div class="panel user-card">
        <div class="user-profile">
          <el-avatar :size="72" :src="avatar || undefined">{{ avatarFallback }}</el-avatar>
          <div class="profile-info">
            <h2 class="username">{{ username || "未知用户" }}</h2>
            <div class="user-ids">
              <span v-if="userId">user_id: <code>{{ userId }}</code></span>
              <span v-if="secUid">sec_uid: <code>{{ secUid }}</code></span>
            </div>
            <div v-if="contentUrl" class="source-video">
              来源视频：
              <a :href="contentUrl" target="_blank" rel="noopener noreferrer">{{ contentId }}</a>
            </div>
          </div>
        </div>

        <el-alert
          v-if="!canOperate"
          title="缺少用户标识，无法执行关注或私信。请确认评论数据中包含 user_id（抖音还需 sec_uid）。"
          type="warning"
          show-icon
          :closable="false"
          class="warn-alert"
        />

        <div class="action-section">
          <h3 class="section-title">用户操作</h3>
          <div class="action-row">
            <el-button
              type="primary"
              :loading="followLoading"
              :disabled="!canOperate"
              @click="onFollow"
            >
              关注
            </el-button>
            <el-button
              :loading="unfollowLoading"
              :disabled="!canOperate"
              @click="onUnfollow"
            >
              取消关注
            </el-button>
          </div>
        </div>

        <div v-if="supportsDm" class="action-section">
          <h3 class="section-title">发送私信</h3>
          <el-input
            v-model="message"
            type="textarea"
            :rows="4"
            maxlength="500"
            show-word-limit
            placeholder="输入私信内容（1-500 字）"
          />
          <div class="action-row">
            <el-button
              type="success"
              :loading="dmLoading"
              :disabled="!canOperate || !message.trim()"
              @click="onSendMessage"
            >
              发送私信
            </el-button>
            <el-checkbox v-model="showBrowser">显示浏览器（调试用）</el-checkbox>
          </div>
        </div>

        <el-alert
          v-else
          :title="dmUnsupportedHint"
          type="info"
          show-icon
          :closable="false"
          class="dm-unsupported-alert"
        />

        <el-alert
          v-if="resultText"
          :title="resultText"
          :type="resultOk ? 'success' : 'error'"
          show-icon
          :closable="false"
          class="result-alert"
        />
      </div>
    </div>
</template>

<script setup>
import { computed, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { followUser, sendUserMessage, unfollowUser } from "../api/platformUsers";
import { directMessageUnsupportedHint, supportsDirectMessage } from "../utils/platform";

const route = useRoute();
const router = useRouter();

const platform = computed(() => (route.query.platform || "douyin").toString());
const userId = computed(() => (route.query.user_id || "").toString());
const secUid = computed(() => (route.query.sec_uid || "").toString());
const username = computed(() => (route.query.username || "").toString());
const avatar = computed(() => (route.query.avatar || "").toString());
const contentId = computed(() => (route.query.content_id || "").toString());
const contentUrl = computed(() => (route.query.content_url || "").toString());

const message = ref("");
const showBrowser = ref(false);
const followLoading = ref(false);
const unfollowLoading = ref(false);
const dmLoading = ref(false);
const resultText = ref("");
const resultOk = ref(false);

const avatarFallback = computed(() => (username.value || "?").slice(0, 1));
const supportsDm = computed(() => supportsDirectMessage(platform.value));
const dmUnsupportedHint = computed(() => directMessageUnsupportedHint(platform.value));

const canOperate = computed(() => {
  if (platform.value === "douyin") {
    return Boolean(userId.value && secUid.value);
  }
  return Boolean(userId.value);
});

function buildUserPayload() {
  const payload = {
    user_id: userId.value,
    username: username.value || undefined,
    show_browser: showBrowser.value,
  };
  if (platform.value === "douyin") {
    payload.sec_uid = secUid.value;
  }
  return payload;
}

function goBack() {
  router.push("/crawl-data");
}

function showResult(ok, text) {
  resultOk.value = ok;
  resultText.value = text;
}

async function onFollow() {
  followLoading.value = true;
  resultText.value = "";
  try {
    const { data } = await followUser(platform.value, buildUserPayload());
    const ok = Boolean(data?.ok);
    const follow = data?.result?.follow || {};
    showResult(
      ok,
      ok ? `关注成功：${data?.result?.username || username.value}` : data?.error || follow.error || "关注失败",
    );
    if (ok) ElMessage.success("关注操作已提交");
  } catch (err) {
    showResult(false, err?.response?.data?.detail || err.message || "关注失败");
  } finally {
    followLoading.value = false;
  }
}

async function onUnfollow() {
  unfollowLoading.value = true;
  resultText.value = "";
  try {
    const { data } = await unfollowUser(platform.value, buildUserPayload());
    const ok = Boolean(data?.ok);
    const unfollow = data?.result?.unfollow || {};
    showResult(
      ok,
      ok ? `已取消关注：${data?.result?.username || username.value}` : data?.error || unfollow.error || "取消关注失败",
    );
    if (ok) ElMessage.success("取消关注操作已提交");
  } catch (err) {
    showResult(false, err?.response?.data?.detail || err.message || "取消关注失败");
  } finally {
    unfollowLoading.value = false;
  }
}

async function onSendMessage() {
  const text = message.value.trim();
  if (!text) return;
  dmLoading.value = true;
  resultText.value = "";
  try {
    const { data } = await sendUserMessage(platform.value, { ...buildUserPayload(), message: text });
    const ok = Boolean(data?.ok);
    const dm = data?.result?.message || {};
    showResult(ok, ok ? "私信已发送" : data?.error || dm.error || dm.hint || "私信发送失败");
    if (ok) {
      ElMessage.success("私信发送成功");
      message.value = "";
    }
  } catch (err) {
    showResult(false, err?.response?.data?.detail || err.message || "私信发送失败");
  } finally {
    dmLoading.value = false;
  }
}
</script>

<style scoped>
.page-header {
  padding: 12px 20px;
  margin-bottom: 16px;
}

.user-card {
  padding: 24px;
}

.user-profile {
  display: flex;
  gap: 20px;
  align-items: center;
  margin-bottom: 24px;
}

.username {
  margin: 0 0 8px;
  font-size: 22px;
}

.user-ids {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 13px;
  color: var(--muted);
}

.user-ids code {
  color: var(--text);
  font-size: 12px;
}

.source-video {
  margin-top: 8px;
  font-size: 13px;
  color: var(--muted);
}

.source-video a {
  color: var(--primary);
}

.warn-alert {
  margin-bottom: 20px;
}

.action-section {
  margin-bottom: 24px;
}

.section-title {
  margin: 0 0 12px;
  font-size: 16px;
}

.action-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 12px;
  flex-wrap: wrap;
}

.result-alert {
  margin-top: 8px;
}

.dm-unsupported-alert {
  margin-bottom: 8px;
}
</style>
