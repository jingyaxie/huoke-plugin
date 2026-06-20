<template>
  <div class="crawl-page container">
      <div class="crawl-toolbar">
      <div class="panel page-header">
        <div>
          <h2 class="page-title">数据面板</h2>
          <p class="page-subtitle">
            查看已抓取的视频与评论，可直接回复评论；点击用户可进入用户页进行关注。抖音/快手支持网页私信，小红书 PC 端不支持
          </p>
        </div>
        <el-button :loading="loading" type="primary" @click="loadContents">刷新</el-button>
      </div>

      <div class="panel filter-panel">
        <el-form :inline="true" class="filter-form">
          <el-form-item label="平台">
            <el-select v-model="platformFilter" style="width: 140px" @change="onFilterChange">
              <el-option
                v-for="opt in platformFilterOptions"
                :key="opt.value || 'all'"
                :label="opt.label"
                :value="opt.value"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="最后更新时间">
            <el-select v-model="updatedPreset" style="width: 140px" @change="onFilterChange">
              <el-option label="全部" value="" />
              <el-option label="今天" value="today" />
              <el-option label="最近 3 天" value="3" />
              <el-option label="最近 7 天" value="7" />
              <el-option label="最近 30 天" value="30" />
              <el-option label="自定义" value="custom" />
            </el-select>
          </el-form-item>
          <el-form-item v-if="updatedPreset === 'custom'" label="时间范围">
            <el-date-picker
              v-model="updatedRange"
              type="datetimerange"
              range-separator="至"
              start-placeholder="开始时间"
              end-placeholder="结束时间"
              value-format="YYYY-MM-DDTHH:mm:ss"
              @change="onFilterChange"
            />
          </el-form-item>
          <el-form-item>
            <el-button @click="resetFilters">重置</el-button>
          </el-form-item>
        </el-form>
      </div>

      <el-alert
        v-if="errorMessage"
        :title="errorMessage"
        type="error"
        show-icon
        :closable="false"
        class="status-alert"
      />
      </div>

      <div class="crawl-list-scroll">
      <div v-if="loading && items.length === 0" class="panel loading-panel" v-loading="true" element-loading-text="加载抓取数据中...">
        <div class="loading-placeholder" />
      </div>

      <div v-else-if="!loading && items.length === 0" class="panel empty-panel">
        <el-empty :description="hasActiveFilter ? '当前筛选条件下暂无数据' : '暂无抓取数据'">
          <p class="empty-hint">
            {{
              hasActiveFilter
                ? "可尝试切换为「全部平台」、放宽时间范围，或点击重置。"
                : "请先在「对外接口 API」运行 Pipeline 抓取，或调用平台评论接口。"
            }}
          </p>
        </el-empty>
      </div>

      <div v-else class="video-list">
        <div v-for="item in items" :key="itemRowKey(item)" class="panel video-card">
          <div class="video-head" @click="toggleExpand(item)">
            <div class="video-main">
              <div class="video-title-row">
                <el-tag :type="platformTagType(item.platform)" size="small" effect="dark">
                  {{ platformLabel(item.platform) }}
                </el-tag>
                <el-tag v-if="item.meta?.capture_method" size="small" type="info">
                  {{ item.meta.capture_method }}
                </el-tag>
                <el-tag v-if="item.meta?.guest_mode" size="small">游客态</el-tag>
                <span class="video-id">{{ displayExternalId(item) }}</span>
              </div>
              <div v-if="item.meta?.title" class="video-title">{{ item.meta.title }}</div>
              <div v-if="item.meta?.author_name" class="video-author">作者：{{ item.meta.author_name }}</div>
              <a
                v-if="item.content_url"
                class="video-link"
                :href="item.content_url"
                target="_blank"
                rel="noopener noreferrer"
                @click.stop
              >
                {{ item.content_url }}
              </a>
              <span v-else class="muted">暂无链接</span>
              <div class="video-tags">
                <el-tag v-if="item.meta?.keyword_context?.keyword" size="small" class="tag-gap">
                  关键词：{{ item.meta.keyword_context.keyword }}
                </el-tag>
                <el-tag v-if="item.meta?.keyword_context?.region" size="small" class="tag-gap">
                  地区：{{ item.meta.keyword_context.region }}
                </el-tag>
                <el-tag v-if="item.meta?.keyword_context?.days" size="small" class="tag-gap">
                  最近 {{ item.meta.keyword_context.days }} 天
                </el-tag>
              </div>
              <el-descriptions :column="2" size="small" border class="meta-desc">
                <el-descriptions-item label="内容 ID">{{ item.content_id }}</el-descriptions-item>
                <el-descriptions-item v-if="item.tenant_id" label="租户">{{ item.tenant_id }}</el-descriptions-item>
                <el-descriptions-item v-if="item.meta?.api_total_top_comments != null" label="平台评论数">
                  {{ item.meta.api_total_top_comments }}
                </el-descriptions-item>
                <el-descriptions-item label="已抓取评论">{{ item.comment_count }}</el-descriptions-item>
                <el-descriptions-item v-if="item.top_comment_count" label="顶层评论">
                  {{ item.top_comment_count }}
                </el-descriptions-item>
                <el-descriptions-item v-if="item.meta?.like_count != null" label="点赞">
                  {{ item.meta.like_count }}
                </el-descriptions-item>
                <el-descriptions-item v-if="item.meta?.share_count != null" label="分享">
                  {{ item.meta.share_count }}
                </el-descriptions-item>
                <el-descriptions-item v-if="item.meta?.publish_time" label="发布时间">
                  {{ formatUnix(item.meta.publish_time) }}
                </el-descriptions-item>
                <el-descriptions-item v-if="item.updated_at" label="最后更新时间">
                  {{ formatTime(item.updated_at) }}
                </el-descriptions-item>
                <el-descriptions-item v-if="item.meta?.file_modified_at" label="文件更新时间">
                  {{ formatTime(item.meta.file_modified_at) }}
                </el-descriptions-item>
                <el-descriptions-item v-if="item.last_seen_at" label="最后入库">
                  {{ formatTime(item.last_seen_at) }}
                </el-descriptions-item>
                <el-descriptions-item v-if="item.canonical_file" label="数据文件">
                  {{ item.canonical_file }}
                </el-descriptions-item>
                <el-descriptions-item v-if="item.meta?.session_mode" label="会话模式">
                  {{ item.meta.session_mode }}
                </el-descriptions-item>
                <el-descriptions-item v-if="item.meta?.warning" label="警告" :span="2">
                  {{ item.meta.warning }}
                </el-descriptions-item>
              </el-descriptions>
            </div>
            <div class="video-meta">
              <el-tag size="small">{{ item.comment_count }} 条评论</el-tag>
              <el-icon class="expand-icon" :class="{ expanded: expandedId === itemRowKey(item) }">
                <ArrowDown />
              </el-icon>
            </div>
          </div>

          <div v-if="expandedId === itemRowKey(item)" class="comment-section">
            <div v-if="detailLoading[itemRowKey(item)]" class="comment-loading">
              <el-skeleton :rows="4" animated />
            </div>
            <div v-else-if="detailErrors[itemRowKey(item)]" class="muted empty-comments">
              {{ detailErrors[itemRowKey(item)] }}
            </div>
            <template v-else-if="detailMap[itemRowKey(item)]">
              <div v-if="detailMap[itemRowKey(item)].meta?.extra && Object.keys(detailMap[itemRowKey(item)].meta.extra).length" class="extra-meta">
                <div class="extra-title">其他字段</div>
                <pre class="extra-json">{{ formatJson(detailMap[itemRowKey(item)].meta.extra) }}</pre>
              </div>
              <div v-if="detailMap[itemRowKey(item)].storage_meta" class="extra-meta">
                <div class="extra-title">存储信息</div>
                <pre class="extra-json">{{ formatJson(detailMap[itemRowKey(item)].storage_meta) }}</pre>
              </div>
              <div v-if="detailMap[itemRowKey(item)].comments.length === 0" class="muted empty-comments">
                该视频暂无评论数据
              </div>
              <div
                v-for="comment in detailMap[itemRowKey(item)].comments"
                :key="comment.comment_id"
                class="comment-row"
                :class="{ reply: comment.parent_comment_id }"
              >
                <div class="comment-user" @click="openUser(comment, item)">
                  <el-avatar :size="36" :src="comment.user.avatar || undefined">
                    {{ avatarFallback(comment) }}
                  </el-avatar>
                  <div class="user-info">
                    <div class="nickname">{{ comment.nickname || comment.user.username }}</div>
                    <div class="comment-text">{{ comment.comment }}</div>
                    <div class="comment-foot">
                      <span v-if="comment.digg_count">👍 {{ comment.digg_count }}</span>
                      <span v-if="comment.create_time">{{ formatUnix(comment.create_time) }}</span>
                      <span v-if="comment.reply_comment_total">回复 {{ comment.reply_comment_total }}</span>
                    </div>
                  </div>
                </div>
                <div class="comment-actions">
                  <el-button
                    link
                    type="primary"
                    :disabled="!comment.comment_id"
                    @click.stop="openReplyDialog(comment, item)"
                  >
                    回复
                  </el-button>
                  <el-button link type="primary" @click.stop="openUser(comment, item)">查看用户</el-button>
                </div>
              </div>
            </template>
          </div>
        </div>
      </div>

      <div v-if="total > items.length" class="load-more">
        <el-button :loading="loadingMore" @click="loadMore">加载更多</el-button>
      </div>
      </div>

      <el-dialog
        v-model="replyDialogVisible"
        title="回复评论"
        width="520px"
        destroy-on-close
        @closed="resetReplyDialog"
      >
        <div v-if="replyTarget.comment" class="reply-target">
          <div class="reply-target-label">回复给</div>
          <div class="reply-target-user">{{ replyTarget.nickname || "未知用户" }}</div>
          <div class="reply-target-text">{{ replyTarget.comment }}</div>
        </div>
        <el-input
          v-model="replyText"
          type="textarea"
          :rows="4"
          maxlength="500"
          show-word-limit
          placeholder="输入回复内容（1-500 字）"
        />
        <div class="reply-dialog-foot">
          <el-checkbox v-model="replyShowBrowser">显示浏览器（调试用）</el-checkbox>
        </div>
        <template #footer>
          <el-button @click="replyDialogVisible = false">取消</el-button>
          <el-button type="primary" :loading="replySubmitting" :disabled="!replyText.trim()" @click="submitReply">
            发送回复
          </el-button>
        </template>
      </el-dialog>
    </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { ArrowDown } from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";
import { fetchContentDetail, fetchContentList, replyComment } from "../api/contentLibrary";
import { externalIdLabel, PLATFORM_FILTER_OPTIONS, PLATFORM_IDS, platformLabel, platformTagType } from "../utils/platform";

const router = useRouter();
const platformFilterOptions = PLATFORM_FILTER_OPTIONS;
const platformFilter = ref("");
const mergedItems = ref([]);
const loading = ref(false);
const loadingMore = ref(false);
const errorMessage = ref("");
const items = ref([]);
const total = ref(0);
const offset = ref(0);
const limit = 30;
const expandedId = ref("");
const updatedPreset = ref("");
const updatedRange = ref([]);
const detailMap = reactive({});
const detailLoading = reactive({});
const detailErrors = reactive({});
const replyDialogVisible = ref(false);
const replySubmitting = ref(false);
const replyText = ref("");
const replyShowBrowser = ref(false);
const replyTarget = reactive({
  platform: "",
  contentId: "",
  contentUrl: "",
  commentId: "",
  comment: "",
  nickname: "",
  photoAuthorId: "",
  replyToUserId: "",
});

const hasActiveFilter = computed(() => {
  if (platformFilter.value) return true;
  if (!updatedPreset.value) return false;
  if (updatedPreset.value === "custom") {
    return Boolean(updatedRange.value?.length);
  }
  return true;
});

function itemRowKey(item) {
  return `${item.platform}:${item.content_id}`;
}

function sortByUpdatedAt(rows) {
  return [...rows].sort((a, b) => {
    const ta = a.updated_at ? new Date(a.updated_at).getTime() : 0;
    const tb = b.updated_at ? new Date(b.updated_at).getTime() : 0;
    return tb - ta;
  });
}

function toLocalDateTime(date) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

function startOfToday() {
  const now = new Date();
  return new Date(now.getFullYear(), now.getMonth(), now.getDate());
}

function buildUpdatedFilters() {
  if (!updatedPreset.value) {
    return {};
  }
  if (updatedPreset.value === "custom") {
    const [start, end] = updatedRange.value || [];
    if (!start && !end) return {};
    return {
      updatedAfter: start || undefined,
      updatedBefore: end || undefined,
    };
  }
  if (updatedPreset.value === "today") {
    return { updatedAfter: toLocalDateTime(startOfToday()) };
  }
  const days = Number(updatedPreset.value);
  if (!Number.isFinite(days) || days <= 0) return {};
  const after = new Date();
  after.setDate(after.getDate() - days);
  return { updatedAfter: toLocalDateTime(after) };
}

function onFilterChange() {
  loadContents();
}

function resetFilters() {
  platformFilter.value = "";
  updatedPreset.value = "";
  updatedRange.value = [];
  loadContents();
}

function displayExternalId(item) {
  const id = item.meta?.external_id || item.content_id;
  return `${externalIdLabel(item.platform)}：${id}`;
}

function formatJson(value) {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function formatTime(value) {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

function formatUnix(ts) {
  if (!ts) return "";
  const date = new Date(Number(ts) * 1000);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleString();
}

function avatarFallback(comment) {
  const name = comment.nickname || comment.user?.username || "?";
  return name.slice(0, 1);
}

async function loadDetail(item) {
  const key = itemRowKey(item);
  if (detailMap[key] || detailLoading[key]) return;
  detailLoading[key] = true;
  delete detailErrors[key];
  try {
    const { data } = await fetchContentDetail(item.platform, item.content_id);
    detailMap[key] = data;
  } catch (err) {
    const detail = err?.response?.data?.detail;
    const message =
      err.code === "ECONNABORTED"
        ? "加载评论超时，请稍后重试"
        : typeof detail === "string"
          ? detail
          : err.message || "加载评论失败";
    detailErrors[key] = message;
    ElMessage.error(message);
  } finally {
    detailLoading[key] = false;
  }
}

function toggleExpand(item) {
  const key = itemRowKey(item);
  if (expandedId.value === key) {
    expandedId.value = "";
    return;
  }
  expandedId.value = key;
  loadDetail(item);
}

function openUser(comment, contentItem) {
  const user = comment.user || {};
  router.push({
    path: "/crawl-data/user",
    query: {
      platform: contentItem.platform,
      user_id: user.user_id || "",
      sec_uid: user.sec_uid || "",
      username: comment.nickname || user.username || "",
      avatar: user.avatar || "",
      content_id: contentItem.content_id,
      content_url: contentItem.content_url || "",
      comment_id: comment.comment_id,
    },
  });
}

function resolveContentUrl(item, detail) {
  return (
    item.content_url ||
    detail?.content_url ||
    detail?.video_url ||
    detail?.note_url ||
    item.meta?.content_url ||
    ""
  );
}

function resolvePhotoAuthorId(item, detail, comment) {
  const extra = detail?.meta?.extra || {};
  return (
    extra.photo_author_id ||
    detail?.meta?.author_id ||
    item.meta?.author_id ||
    comment?.photo_author_id ||
    ""
  );
}

function openReplyDialog(comment, contentItem) {
  if (!comment.comment_id) {
    ElMessage.warning("该评论缺少 comment_id，无法回复");
    return;
  }
  const key = itemRowKey(contentItem);
  const detail = detailMap[key];
  replyTarget.platform = contentItem.platform;
  replyTarget.contentId = contentItem.content_id;
  replyTarget.contentUrl = resolveContentUrl(contentItem, detail);
  replyTarget.commentId = comment.comment_id;
  replyTarget.comment = comment.comment || "";
  replyTarget.nickname = comment.nickname || comment.user?.username || "";
  replyTarget.photoAuthorId = resolvePhotoAuthorId(contentItem, detail, comment);
  replyTarget.replyToUserId = comment.user?.user_id || comment.user_id || "";
  replyText.value = "";
  replyShowBrowser.value = false;
  replyDialogVisible.value = true;
}

function resetReplyDialog() {
  replyText.value = "";
  replyShowBrowser.value = false;
  replyTarget.platform = "";
  replyTarget.contentId = "";
  replyTarget.contentUrl = "";
  replyTarget.commentId = "";
  replyTarget.comment = "";
  replyTarget.nickname = "";
  replyTarget.photoAuthorId = "";
  replyTarget.replyToUserId = "";
}

async function submitReply() {
  const text = replyText.value.trim();
  if (!text) {
    ElMessage.warning("请输入回复内容");
    return;
  }
  if (!replyTarget.commentId) {
    ElMessage.warning("缺少评论 ID");
    return;
  }
  if (!replyTarget.contentUrl) {
    ElMessage.warning("缺少内容链接，无法定位视频/笔记");
    return;
  }

  replySubmitting.value = true;
  try {
    const platform = replyTarget.platform;
    const contentUrl = replyTarget.contentUrl;
    const { data } = await replyComment(platform, {
      comment_id: replyTarget.commentId,
      reply_text: text,
      content_id: replyTarget.contentId,
      content_url: contentUrl,
      video_url: platform !== "xiaohongshu" ? contentUrl : undefined,
      note_url: platform === "xiaohongshu" ? contentUrl : undefined,
      comment_text: replyTarget.comment,
      photo_author_id: replyTarget.photoAuthorId || undefined,
      reply_to_user_id: replyTarget.replyToUserId || undefined,
      show_browser: replyShowBrowser.value,
    });
    const ok = Boolean(data?.ok);
    const inner = data?.result || {};
    const err = data?.error || inner.error || inner.reply?.error;
    if (ok) {
      ElMessage.success(data.summary || "回复已发送");
      replyDialogVisible.value = false;
    } else {
      ElMessage.error(err || data.summary || "回复失败");
    }
  } catch (err) {
    const detail = err?.response?.data?.detail;
    ElMessage.error(
      err.code === "ECONNABORTED"
        ? "回复超时，请确认平台已登录后重试"
        : typeof detail === "string"
          ? detail
          : err.message || "回复失败",
    );
  } finally {
    replySubmitting.value = false;
  }
}

async function loadContents(reset = true) {
  if (reset) {
    loading.value = true;
    offset.value = 0;
    items.value = [];
    expandedId.value = "";
    Object.keys(detailMap).forEach((key) => delete detailMap[key]);
    Object.keys(detailErrors).forEach((key) => delete detailErrors[key]);
  }
  errorMessage.value = "";
  const filters = buildUpdatedFilters();
  try {
    if (platformFilter.value) {
      const { data } = await fetchContentList(platformFilter.value, {
        offset: offset.value,
        limit,
        ...filters,
      });
      mergedItems.value = [];
      total.value = data.total || 0;
      if (reset) {
        items.value = data.items || [];
      } else {
        items.value = [...items.value, ...(data.items || [])];
      }
    } else {
      const platforms = PLATFORM_IDS;
      const batches = await Promise.all(
        platforms.map(async (pid) => {
          try {
            const { data } = await fetchContentList(pid, { offset: 0, limit: 500, ...filters });
            return data.items || [];
          } catch {
            return [];
          }
        })
      );
      const merged = sortByUpdatedAt(batches.flat());
      mergedItems.value = merged;
      total.value = merged.length;
      const end = reset ? limit : offset.value + limit;
      if (reset) {
        offset.value = 0;
      }
      items.value = merged.slice(0, end);
    }
  } catch (err) {
    const detail = err?.response?.data?.detail;
    const status = err?.response?.status;
    if (err.code === "ECONNABORTED") {
      errorMessage.value = "请求超时：后端可能正在重启或 Pipeline 占用中，请稍后点刷新重试";
    } else if (status === 404) {
      errorMessage.value = "抓取数据接口未就绪，请确认后端已更新并重启服务";
    } else if (status === 401 && String(detail || "").includes("登录")) {
      errorMessage.value = "登录已过期，请在「登录中心」重新登录后刷新";
    } else if (detail) {
      errorMessage.value = typeof detail === "string" ? detail : JSON.stringify(detail);
    } else {
      errorMessage.value = err.message || "加载失败";
    }
  } finally {
    loading.value = false;
    loadingMore.value = false;
  }
}

async function loadMore() {
  if (items.value.length >= total.value) return;
  loadingMore.value = true;
  if (platformFilter.value) {
    offset.value += limit;
    await loadContents(false);
    return;
  }
  offset.value += limit;
  items.value = mergedItems.value.slice(0, offset.value + limit);
  loadingMore.value = false;
}

function onTenantChanged() {
  loadContents();
}

onMounted(() => {
  loadContents();
  window.addEventListener("huoke-tenant-changed", onTenantChanged);
});
</script>

<style scoped>
.crawl-page {
  height: 100%;
  min-height: 0;
  max-width: 1280px;
  margin: 0 auto;
  padding: 20px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-sizing: border-box;
}

.crawl-toolbar {
  flex-shrink: 0;
}

.crawl-list-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  padding-right: 4px;
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 20px 24px;
  margin-bottom: 16px;
}

.filter-panel {
  padding: 16px 20px;
  margin-bottom: 16px;
}

.filter-form {
  margin: 0;
}

.status-alert {
  margin-bottom: 16px;
}

.loading-panel {
  min-height: 200px;
  margin-bottom: 16px;
}

.loading-placeholder {
  height: 200px;
}

.empty-panel {
  padding: 40px 20px;
}

.empty-hint {
  color: var(--muted);
  font-size: 13px;
  margin-top: 8px;
}

.video-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.video-card {
  overflow: hidden;
}

.video-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 20px;
  cursor: pointer;
  transition: background 0.15s;
}

.video-head:hover {
  background: #f9fafb;
}

.video-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}

.video-id {
  font-weight: 600;
  font-size: 14px;
  color: var(--text);
}

.video-title {
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 4px;
}

.video-author {
  font-size: 13px;
  color: var(--muted);
  margin-bottom: 4px;
}

.video-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 8px 0;
}

.meta-desc {
  margin-top: 10px;
}

.video-link {
  color: var(--primary);
  font-size: 13px;
  word-break: break-all;
  text-decoration: none;
}

.video-link:hover {
  text-decoration: underline;
}

.video-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.tag-gap {
  margin-left: 0;
}

.time-text {
  font-size: 12px;
}

.expand-icon {
  transition: transform 0.2s;
  color: var(--muted);
}

.expand-icon.expanded {
  transform: rotate(180deg);
}

.comment-section {
  border-top: 1px solid #e5e7eb;
  padding: 12px 20px 16px;
  background: #fafbfc;
}

.comment-loading {
  padding: 8px 0;
}

.comment-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 0;
  border-bottom: 1px solid #eef0f3;
}

.comment-row:last-child {
  border-bottom: none;
}

.comment-row.reply {
  margin-left: 28px;
  padding-left: 12px;
  border-left: 2px solid #e5e7eb;
}

.comment-actions {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
  flex-shrink: 0;
}

.reply-target {
  margin-bottom: 12px;
  padding: 10px 12px;
  background: #f3f4f6;
  border-radius: 6px;
}

.reply-target-label {
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 4px;
}

.reply-target-user {
  font-weight: 600;
  font-size: 14px;
  color: var(--primary);
}

.reply-target-text {
  margin-top: 4px;
  font-size: 13px;
  line-height: 1.5;
  word-break: break-word;
}

.reply-dialog-foot {
  margin-top: 10px;
}

.comment-user {
  display: flex;
  gap: 12px;
  flex: 1;
  min-width: 0;
  cursor: pointer;
}

.user-info {
  min-width: 0;
}

.nickname {
  font-weight: 600;
  font-size: 14px;
  color: var(--primary);
}

.comment-text {
  margin-top: 4px;
  font-size: 14px;
  line-height: 1.5;
  word-break: break-word;
}

.comment-foot {
  margin-top: 6px;
  display: flex;
  gap: 12px;
  font-size: 12px;
  color: var(--muted);
}

.empty-comments {
  padding: 12px 0;
}

.extra-meta {
  margin-bottom: 12px;
  padding: 10px 12px;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
}

.extra-title {
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 6px;
}

.extra-json {
  margin: 0;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-all;
  color: #374151;
}

.muted {
  color: var(--muted);
  font-size: 13px;
}

.load-more {
  display: flex;
  justify-content: center;
  padding: 20px 0;
}
</style>
