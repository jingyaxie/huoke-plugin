export function validateTaskPresetSelection(settings, commentPresetIds, dmPresetIds) {
  const pct = Math.max(0, Math.min(100, Number(settings?.comment_dm_percentage ?? 50)));
  const needComment = pct > 0;
  const needDm = pct < 100;
  const missing = [];
  if (needComment && !(commentPresetIds || []).length) missing.push("评论模板");
  if (needDm && !(dmPresetIds || []).length) missing.push("私信模板");
  if (!missing.length) return null;
  return `请先前往「评论/私信预设」添加${missing.join("和")}，或在下方勾选要使用的模板。`;
}
