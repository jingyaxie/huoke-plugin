import {
  listCollectComments,
  listCollectInteractionsOptional,
  listCollectVideos,
} from "../api/localService";
import {
  getMetricViewCounts,
  getRowsForMetricView,
  OUTREACH_METRIC_VIEWS,
} from "./acquisitionJobs";

function douyinVideoUrl(awemeId) {
  const id = String(awemeId || "").trim();
  return id ? `https://www.douyin.com/video/${id}` : "";
}

function douyinProfileUrl(secUid) {
  const id = String(secUid || "").trim();
  return id ? `https://www.douyin.com/user/${id}` : "";
}

function commentTimestampMs(comment) {
  const raw = Number(comment?.create_time ?? 0);
  if (!Number.isFinite(raw) || raw <= 0) return null;
  return raw > 1e12 ? raw : raw * 1000;
}

function resolveVideoMeta(comment, videoByAweme, fallbackVideos) {
  const awemeId = String(comment.aweme_id || "");
  const direct = videoByAweme.get(awemeId);
  if (direct?.title) {
    return {
      title: direct.title,
      url: direct.video_url || douyinVideoUrl(awemeId),
    };
  }
  if (awemeId && /^\d{8,22}$/.test(awemeId)) {
    const titled = (fallbackVideos || []).find((v) => v.title);
    return {
      title: titled?.title || "",
      url: douyinVideoUrl(awemeId),
    };
  }
  const titled = (fallbackVideos || []).find((v) => v.title);
  return {
    title: titled?.title || "",
    url: titled?.video_url || douyinVideoUrl(awemeId),
  };
}

export function extensionJobTargetCount(job) {
  const fromConfig = Number(job?.config?.target_count);
  if (Number.isFinite(fromConfig) && fromConfig > 0) return fromConfig;
  return Number(job?.limit_videos || 0) * Number(job?.max_comments_per_video || 0) || 0;
}

export function extensionJobMetrics(job) {
  return {
    requested_target: extensionJobTargetCount(job),
    produced_total: Number(job?.comment_count || 0),
    progress_precise: 0,
    comment_count: Number(job?.reply_count || 0),
    dm_count: Number(job?.dm_count || 0),
    follow_count: Number(job?.follow_count || 0),
  };
}

export function extensionMetricViewCount(job, view) {
  if (!job) return 0;
  if (view === OUTREACH_METRIC_VIEWS.ALL) return Number(job.comment_count || 0);
  if (view === OUTREACH_METRIC_VIEWS.PRECISE) return 0;
  if (view === OUTREACH_METRIC_VIEWS.REPLY) return Number(job.reply_count || 0);
  if (view === OUTREACH_METRIC_VIEWS.DM) return Number(job.dm_count || 0);
  if (view === OUTREACH_METRIC_VIEWS.FOLLOW) return Number(job.follow_count || 0);
  return 0;
}

export function buildAgentJobFromCollectJob(collectJob, { comments = [], videos = [], interactions = [] } = {}) {
  const videoByAweme = new Map(
    (videos || []).map((video) => [String(video.aweme_id || ""), video]),
  );

  const outreachByComment = {};
  for (const event of interactions || []) {
    const commentId = String(event?.comment_id || "").trim();
    if (!commentId) continue;
    const bucket = outreachByComment[commentId] || {};
    const action = String(event?.action || "").toLowerCase();
    if (action === "reply") bucket.has_reply = true;
    if (action === "dm") bucket.has_dm = true;
    if (action === "follow") bucket.has_follow = true;
    bucket.executed_at = event.created_at || bucket.executed_at;
    outreachByComment[commentId] = bucket;
  }

  const capturedComments = (comments || []).map((comment) => {
    const awemeId = String(comment.aweme_id || "");
    const videoMeta = resolveVideoMeta(comment, videoByAweme, videos);
    const commentId = String(comment.comment_id || comment.id || "");
    const outreach = outreachByComment[commentId] || {};
    const ts = commentTimestampMs(comment);
    return {
      id: comment.id || commentId,
      comment_id: commentId,
      nickname: comment.username || "—",
      avatar: comment.avatar_url || "",
      avatar_url: comment.avatar_url || "",
      comment_content: comment.content || "",
      comment_at: ts,
      video_title: videoMeta.title,
      video_url: videoMeta.url,
      profile_url: douyinProfileUrl(comment.sec_uid),
      is_precise: false,
      evaluation_reason: "",
      reply_content: outreach.has_reply ? "已回复" : "",
      dm_content: outreach.has_dm ? "已私信" : "",
      executed_at: outreach.executed_at || null,
      digg_count: comment.digg_count,
    };
  });

  const outreachEvents = (interactions || []).map((event) => ({
    id: event.id,
    action: event.action,
    action_type: event.action,
    comment_id: event.comment_id,
    target_user_id: event.user_id,
    status: "ok",
    executed_at: event.created_at,
    created_at: event.created_at,
  }));

  const config = {
    ...(collectJob?.config && typeof collectJob.config === "object" ? collectJob.config : {}),
    task_name: collectJob?.name || collectJob?.keyword,
    keyword: collectJob?.keyword,
    keywords: collectJob?.keyword ? [collectJob.keyword] : [],
    platform: collectJob?.platform,
    target_count: extensionJobTargetCount(collectJob),
  };

  return {
    job_id: collectJob.id,
    platform: collectJob.platform,
    status: collectJob.status,
    created_at: collectJob.created_at,
    message: collectJob.name || collectJob.keyword,
    sync: {
      captured_comments: capturedComments,
      outreach_events: outreachEvents,
    },
    result: {
      orchestration: { config },
    },
  };
}

export async function loadCollectJobForModal(collectJob) {
  const jobId = collectJob.id;
  const [commentsResp, videosResp, interactionsResp] = await Promise.all([
    listCollectComments(jobId, { limit: 2000 }),
    listCollectVideos(jobId),
    listCollectInteractionsOptional(jobId, { limit: 2000 }),
  ]);
  return buildAgentJobFromCollectJob(collectJob, {
    comments: commentsResp.comments || [],
    videos: videosResp.videos || [],
    interactions: interactionsResp.interactions || [],
  });
}

export function getExtensionModalViewCounts(agentJob) {
  return getMetricViewCounts(agentJob);
}

export function getExtensionModalRows(agentJob, view) {
  return getRowsForMetricView(agentJob, view);
}
